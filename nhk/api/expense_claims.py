"""Technician expense claims, for the NHK Technician app (`nhk.api.expense_claims`).

A technician pays for petrol, a porter or a Rapido, a battery, out of their own
pocket, usually by UPI, and files a claim here with the payment screenshot.

A claim is a plain HRMS **Expense Claim** with one expense row and
`custom_technician_id` set (ADR 0008, 2026-10-19). Everything after filing is
HRMS on the desk, untouched: the office sets Approval Status, submits, and pays
(Is Paid with a Mode of Payment, or a Payment Entry). The app only reads where
the claim stands:

	Draft, not yet approved        -> Pending   (the technician may edit or withdraw it)
	Approved, not yet paid         -> Approved
	HRMS status Paid               -> Paid
	Rejected                       -> Rejected

Only Paid claims reach the payout page (`nhk.api.payouts`), outside the total.

Expense types are HRMS Expense Claim Types with a default account for the
company: HRMS refuses to save a claim without one. Not gated on duty: a claim
is often filed after the shift.
"""

import functools

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, fmt_money, getdate

from nhk.api.guards import current_technician
from nhk.api.ops import OFFICE_ROLE
from nhk.api.staff import ATTACHMENT_IS_PRIVATE, _validated_attachment

CLAIM = "Expense Claim"

PENDING, APPROVED, PAID, REJECTED = "Pending", "Approved", "Paid", "Rejected"

#: The type whose note is required: nothing else says what it was.
OTHER = "Others"

#: A typing guard, not a policy: a petrol bill is hundreds, not lakhs.
MAX_AMOUNT = 50000

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


# ---------------------------------------------------------------------------
# reading claims
# ---------------------------------------------------------------------------

def app_status(approval_status, status):
	"""Where a claim stands, as the app shows it, from HRMS's own two fields."""
	if approval_status == "Rejected":
		return REJECTED
	if status == "Paid":
		return PAID
	if approval_status == "Approved":
		return APPROVED
	return PENDING


def _rows(conditions, values, limit=DEFAULT_LIMIT):
	"""Technician claims matching `conditions` (SQL on `ec` / `d`), newest first, as the app reads them."""
	rows = frappe.db.sql(
		f"""
		select ec.name, ec.custom_technician_id as technician_id, ec.employee_name as technician_name,
			ec.approval_status, ec.status as hrms_status, ec.docstatus,
			d.expense_date, d.expense_type, d.amount, d.sanctioned_amount, ec.remark as note,
			ec.custom_visit as visit, ec.custom_receipt as receipt, ec.creation, ec.modified
		from `tabExpense Claim` ec
		join `tabExpense Claim Detail` d on d.parent = ec.name and d.parenttype = 'Expense Claim'
		where ec.custom_technician_id is not null and ec.custom_technician_id != ''
			and ec.docstatus < 2 {"and " + conditions if conditions else ""}
		order by ec.creation desc
		limit {min(cint(limit) or DEFAULT_LIMIT, MAX_LIMIT)}
		""",
		values,
		as_dict=True,
	)
	for row in rows:
		row.status = app_status(row.pop("approval_status"), row.pop("hrms_status"))
		row.can_edit = row.status == PENDING and row.pop("docstatus") == 0
		row.patient_name = (
			frappe.db.get_value("Technician Visit Entry", row.visit, "patient_name") if row.visit else None
		)
	return rows


def _one(claim_id):
	rows = _rows("ec.name = %(name)s", {"name": claim_id}, 1)
	if not rows:
		frappe.throw(_("Claim {0} not found.").format(claim_id), frappe.DoesNotExistError)
	return rows[0]


def _editable(claim_id, technician):
	"""The caller's claim while still Pending; "not found" for missing and not theirs alike."""
	if claim_id and frappe.db.exists(CLAIM, {"name": claim_id, "custom_technician_id": technician}):
		claim = frappe.get_doc(CLAIM, claim_id)
		if claim.docstatus != 0 or claim.approval_status != "Draft":
			frappe.throw(_("{0} is {1} and can no longer change.").format(
				claim.name, _(app_status(claim.approval_status, claim.status))))
		return claim
	frappe.throw(_("Claim {0} not found.").format(claim_id), frappe.DoesNotExistError)


def technician_user(technician_id):
	"""The login of a technician: `user_mail_id` is their NHK User, named by the email."""
	return frappe.db.get_value("Technician Details", technician_id, "user_mail_id") if technician_id else None


def _employee(technician_id):
	"""The technician's Employee (NHK User creates one per login) and its company."""
	user = technician_user(technician_id)
	employee = user and frappe.db.get_value("Employee", {"user_id": user}, ["name", "company"], as_dict=True)
	if not employee:
		frappe.throw(_("{0} has no Employee record; the office must create one before claims can be filed.")
					 .format(technician_id))
	return employee


def _default_company():
	return frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")


def expense_types(company=None):
	"""Expense Claim Types the claim can be saved with: those with an account for `company`."""
	return frappe.get_all(
		"Expense Claim Account",
		filters={"parenttype": "Expense Claim Type", "company": company or _default_company(),
				 "default_account": ("is", "set")},
		pluck="parent", order_by="parent", distinct=True,
	)


# ---------------------------------------------------------------------------
# the screenshot
# ---------------------------------------------------------------------------

def _uploaded():
	"""The screenshot from the phone's multipart POST, checked; None when no file came."""
	uploaded = (frappe.request.files or {}).get("file") if frappe.request else None
	if uploaded is None:
		return None
	filename = (uploaded.filename or "").strip()
	content = uploaded.stream.read()
	_validated_attachment(filename, content)
	return filename, content


def _attach(claim, upload):
	filename, content = upload
	return frappe.get_doc({
		"doctype": "File",
		"attached_to_doctype": CLAIM,
		"attached_to_name": claim.name,
		"attached_to_field": "custom_receipt",
		"file_name": filename,
		"is_private": ATTACHMENT_IS_PRIVATE,
		"content": content,
	}).insert(ignore_permissions=True)


def _delete_files(claim_name, keep_url=None):
	for file in frappe.get_all("File", filters={"attached_to_doctype": CLAIM, "attached_to_name": claim_name},
							   fields=["name", "file_url"]):
		if file.file_url != keep_url:
			frappe.delete_doc("File", file.name, ignore_permissions=True, delete_permanently=True)


# ---------------------------------------------------------------------------
# what the phone sends
# ---------------------------------------------------------------------------

def _apply(claim, values, technician):
	"""Copy the form fields the phone sent onto `claim` and its one expense row, checked."""
	row = claim.expenses[0]
	expense_type = values.get("expense_type")
	if expense_type is not None:
		allowed = expense_types(claim.company)
		if expense_type not in allowed:
			frappe.throw(_("Expense type must be one of {0}.").format(", ".join(allowed) or _("(none set up)")))
		if expense_type != row.expense_type:
			row.expense_type, row.default_account = expense_type, None  # HRMS fills the type's account
	if values.get("amount") is not None:
		row.amount = flt(values.get("amount"))
		# The desk form copies the amount into the sanctioned amount as it is typed
		# (HRMS `expense_claim.js`); filed from here, nothing did. Approved and
		# submitted as it stood, the claim was sanctioned at 0: neither Unpaid nor
		# Paid, and 0 on the payout page. The office can still lower it.
		row.sanctioned_amount = row.amount
	if values.get("expense_date"):
		row.expense_date = getdate(values.get("expense_date"))
	if values.get("note") is not None:
		claim.remark = cstr(values.get("note")).strip() or None
	if values.get("visit_id") is not None:
		claim.custom_visit = values.get("visit_id") or None

	if flt(row.amount) <= 0:
		frappe.throw(_("Amount must be more than zero."))
	if flt(row.amount) > MAX_AMOUNT:
		frappe.throw(_("Amount cannot be more than {0}.").format(MAX_AMOUNT))
	if row.expense_date and getdate(row.expense_date) > getdate():
		frappe.throw(_("Expense date cannot be in the future."))
	if row.expense_type == OTHER and not claim.remark:
		frappe.throw(_("Say what the expense was for."))
	if claim.custom_visit and frappe.db.get_value(
			"Technician Visit Entry", claim.custom_visit, "technician_id") != technician:
		frappe.throw(_("{0} is not your visit.").format(claim.custom_visit))


def _form(**passed):
	"""Arguments as passed, else from the multipart form, as `upload_document` reads them."""
	form = frappe.form_dict
	return {k: (v if v is not None else form.get(k)) for k, v in passed.items()}


# ---------------------------------------------------------------------------
# the technician
# ---------------------------------------------------------------------------

@frappe.whitelist()
def my_claims(limit=DEFAULT_LIMIT):
	"""The caller's claims, newest first, and the types a new one may take."""
	technician = current_technician()
	return {"claims": _rows("ec.custom_technician_id = %(t)s", {"t": technician}, limit),
			"expense_types": expense_types(), "other_type": OTHER}


@frappe.whitelist()
def submit_claim(expense_type=None, amount=None, expense_date=None, note=None, visit_id=None):
	"""File a claim with its payment screenshot (the `file` part, required). The office takes it from the desk."""
	technician = current_technician()
	employee = _employee(technician)
	values = _form(expense_type=expense_type, amount=amount, expense_date=expense_date,
				   note=note, visit_id=visit_id)
	upload = _uploaded()
	if upload is None:
		frappe.throw(_("Attach the payment screenshot."))
	if values.get("expense_type") is None:
		frappe.throw(_("Choose an expense type."))

	company = frappe.get_cached_doc("Company", employee.company)
	claim = frappe.new_doc(CLAIM)
	claim.employee = employee.name
	claim.company = company.name
	claim.custom_technician_id = technician
	claim.posting_date = getdate()
	# What the desk's form would fill, so the office can submit it as it stands.
	claim.payable_account = company.default_expense_claim_payable_account
	claim.cost_center = company.cost_center
	claim.append("expenses", {"expense_date": getdate(), "cost_center": company.cost_center})
	_apply(claim, values, technician)
	claim.insert(ignore_permissions=True)
	# The screenshot is attached to the claim, so it needs the claim's name first.
	claim.db_set("custom_receipt", _attach(claim, upload).file_url, update_modified=False)

	_tell_office(claim.name)
	return _one(claim.name)


@frappe.whitelist()
def update_claim(claim_id, expense_type=None, amount=None, expense_date=None, note=None, visit_id=None):
	"""Change a Pending claim of the caller's; a new `file` part replaces the screenshot."""
	technician = current_technician()
	claim = _editable(claim_id, technician)
	_apply(claim, _form(expense_type=expense_type, amount=amount, expense_date=expense_date,
						note=note, visit_id=visit_id), technician)
	upload = _uploaded()
	if upload is not None:
		claim.custom_receipt = _attach(claim, upload).file_url
	claim.save(ignore_permissions=True)
	if upload is not None:
		_delete_files(claim.name, keep_url=claim.custom_receipt)
	return _one(claim.name)


@frappe.whitelist()
def withdraw_claim(claim_id):
	"""Delete a Pending claim of the caller's and its screenshot."""
	claim = _editable(claim_id, current_technician())
	_delete_files(claim.name)
	frappe.delete_doc(CLAIM, claim.name, ignore_permissions=True)
	return {"name": claim.name, "withdrawn": True}


# ---------------------------------------------------------------------------
# telling the office: a bell on the desk, after commit, never failing the request
# ---------------------------------------------------------------------------

def office_users():
	"""Every enabled NHK Admin login, Administrator excepted."""
	holders = frappe.get_all("Has Role", filters={"role": OFFICE_ROLE, "parenttype": "User"}, pluck="parent")
	people = [u for u in holders if u not in ("Administrator", "Guest")]
	return frappe.get_all("User", filters={"name": ("in", people or [""]), "enabled": 1}, pluck="name")


def _tell_office(claim_name):
	if frappe.flags.nhk_mute_notifications:
		return
	frappe.db.after_commit.add(functools.partial(_notify_office, claim_name, frappe.session.user))


def _notify_office(claim_name, technician_user):
	try:
		claim = _one(claim_name)
		subject = _("Expense claim: {0} {1} from {2}").format(
			fmt_money(claim.amount, currency="INR"), _(claim.expense_type),
			claim.technician_name or claim.technician_id)
		for user in set(office_users()) - {technician_user}:
			_office_alert(user, subject, claim)
	except Exception:
		frappe.log_error(title="Expense claim notification failed", message=frappe.get_traceback())


def _office_alert(user, subject, claim):
	"""The desk's bell notification, opening the claim. Tests replace this."""
	frappe.get_doc({
		"doctype": "Notification Log",
		"for_user": user,
		"type": "Alert",
		"document_type": CLAIM,
		"document_name": claim.name,
		"subject": subject,
	}).insert(ignore_permissions=True)
	frappe.db.commit()
