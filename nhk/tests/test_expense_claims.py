"""Technician expense claims (`nhk.api.expense_claims`) and their place on the payout page.

Run:  cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_expense_claims.py

A claim is a plain HRMS Expense Claim: the technician files it from the app,
the office approves, submits and pays it on the desk. The site needs at least
two Expense Claim Types with a default account for the company, one of them
`Others`, and one Mode of Payment with an account; these tests use what the
site has.

Payout tests use months in 2019 only, as `test_payouts` does.
"""

import sys

import frappe

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from test_payouts import _done, _row
from test_staff_api import OTHER_TECH, OTHER_USER, PILOT_TECH, PILOT_USER, _visit
from test_technician_documents import _PNG, _MultipartPost

CLAIM = "Expense Claim"


def _as(user, fn, *args, **kwargs):
	frappe.set_user(user)
	try:
		return fn(*args, **kwargs)
	finally:
		frappe.set_user("Administrator")


def _refused(exc_type, user, fn, *args, **kwargs):
	try:
		_as(user, fn, *args, **kwargs)
	except exc_type:
		return True
	return False


def _type():
	"""An expense type other than Others that the site can save a claim with."""
	from nhk.api.expense_claims import OTHER, expense_types

	usable = [t for t in expense_types() if t != OTHER]
	assert usable, "no Expense Claim Type has an account for the company: set one up first"
	return usable[0]


def _mode():
	"""A Mode of Payment with an account for the company, as HRMS needs to pay."""
	from nhk.api.expense_claims import _default_company

	modes = frappe.get_all("Mode of Payment Account",
						   filters={"company": _default_company(), "default_account": ("is", "set")}, pluck="parent")
	modes = [m for m in modes if frappe.db.get_value("Mode of Payment", m, "enabled")]
	assert modes, "no Mode of Payment has an account for the company"
	return sorted(modes)[0]


def _forget(cleanup, claim_name):
	"""The claim, its row, its files and anything it posted, deleted as rows."""
	for file in frappe.get_all("File", filters={"attached_to_doctype": CLAIM, "attached_to_name": claim_name},
							   pluck="name"):
		cleanup.add("File", file)
	for row in frappe.get_all("Expense Claim Detail", filters={"parent": claim_name, "parenttype": CLAIM},
							  pluck="name"):
		cleanup.add_row("Expense Claim Detail", row)
	cleanup.add_row(CLAIM, claim_name)


def _forget_after(cleanup, claim_name):
	"""What deciding a claim wrote: GL and payment ledger rows, HRMS's PWA notes."""
	for doctype, filters in (("GL Entry", {"voucher_type": CLAIM, "voucher_no": claim_name}),
							 ("Payment Ledger Entry", {"voucher_type": CLAIM, "voucher_no": claim_name}),
							 ("PWA Notification", {"reference_document_type": CLAIM,
												   "reference_document_name": claim_name})):
		for name in frappe.get_all(doctype, filters=filters, pluck="name"):
			cleanup.add_row(doctype, name)


def _submit(cleanup, user=PILOT_USER, filename="upi.png", content=_PNG, **fields):
	from nhk.api import expense_claims as api

	fields = {"expense_type": _type(), "amount": "500", **fields}
	frappe.set_user(user)
	try:
		with _MultipartPost(fields, filename, content):
			res = api.submit_claim()
	finally:
		frappe.set_user("Administrator")
	_forget(cleanup, res["name"])
	return res


def _payable_account_set(cleanup):
	"""The company's Default Expense Claim Payable Account, set for the test if the site has none."""
	from nhk.api.expense_claims import _default_company

	company = _default_company()
	if not frappe.db.get_value("Company", company, "default_expense_claim_payable_account"):
		account = frappe.db.get_value("Account", {"company": company, "account_type": "Payable", "is_group": 0})
		assert account, "the company has no Payable account"
		cleanup.restore("Company", company, "default_expense_claim_payable_account")
		frappe.db.set_value("Company", company, "default_expense_claim_payable_account", account)
		frappe.clear_document_cache("Company", company)


def _on_the_desk(cleanup, claim_name, approval_status, paid=False):
	"""What the office does on the desk, plain HRMS: set Approval Status (and Is Paid), Submit."""
	doc = frappe.get_doc(CLAIM, claim_name)
	if not doc.payable_account:
		doc.payable_account = frappe.db.get_value("Company", doc.company, "default_expense_claim_payable_account")
	doc.approval_status = approval_status
	# Nothing else: the office approves the row as filed. Copying the amount into
	# the sanctioned amount here hid that the app never set it (claims approved at 0).
	if paid:
		doc.is_paid, doc.mode_of_payment = 1, _mode()
	try:
		doc.submit()
	finally:
		_forget_after(cleanup, claim_name)
	return doc


def _paid(cleanup, technician=PILOT_TECH, amount=500, expense_date="2019-05-10", status="Paid"):
	"""A claim in HRMS status `status`, written directly, dated `expense_date`; nothing posted."""
	from nhk.api.expense_claims import _employee

	employee = _employee(technician)
	approval = {"Paid": "Approved", "Unpaid": "Approved", "Rejected": "Rejected"}.get(status, "Draft")
	doc = frappe.get_doc({
		"doctype": CLAIM, "employee": employee.name, "company": employee.company,
		"custom_technician_id": technician, "custom_receipt": "/private/files/fixture.png",
		"approval_status": approval,
		"expenses": [{"expense_type": _type(), "amount": amount, "sanctioned_amount": amount,
					  "expense_date": expense_date}],
	})
	doc.insert(ignore_permissions=True)
	_forget(cleanup, doc.name)
	_forget_after(cleanup, doc.name)
	if status != "Draft":
		frappe.db.set_value(CLAIM, doc.name, {"docstatus": 1, "status": status}, update_modified=False)
		frappe.db.set_value("Expense Claim Detail", {"parent": doc.name}, "docstatus", 1, update_modified=False)
	return doc.name


# --------------------------------------------------------------------------
# the technician
# --------------------------------------------------------------------------

def test_a_claim_is_filed_pending_with_a_private_screenshot(cleanup):
	from nhk.api import expense_claims as api

	res = _submit(cleanup, note="Bunk near Hebbal")

	assert res["status"] == "Pending" and res["can_edit"], res
	assert res["technician_id"] == PILOT_TECH, res
	assert res["amount"] == 500 and res["expense_type"] == _type(), res
	assert res["receipt"].startswith("/private/files/"), res["receipt"]
	attached = frappe.db.get_value("File", {"file_url": res["receipt"]}, ["attached_to_doctype", "attached_to_name"],
								   as_dict=True)
	assert (attached.attached_to_doctype, attached.attached_to_name) == (CLAIM, res["name"]), attached

	doc = frappe.get_doc(CLAIM, res["name"])
	assert doc.docstatus == 0 and doc.approval_status == "Draft", "a new claim is an unsubmitted Draft"
	assert frappe.db.get_value("Employee", doc.employee, "user_id") == PILOT_USER, doc.employee

	mine = _as(PILOT_USER, api.my_claims)
	assert res["name"] in [c.name for c in mine["claims"]]
	assert _type() in mine["expense_types"] and mine["other_type"] == "Others", mine
	assert res["name"] not in [c.name for c in _as(OTHER_USER, api.my_claims)["claims"]]


def test_a_claim_needs_an_amount_a_known_type_and_a_note_for_others(cleanup):
	before = frappe.db.count(CLAIM)
	for fields in ({"amount": "0"}, {"amount": "-5"}, {"amount": "60000"},
				   {"expense_type": "Others"}, {"expense_type": "Lunch"},
				   {"expense_date": "2099-01-01"}):
		try:
			_submit(cleanup, **fields)
		except frappe.ValidationError:
			continue
		raise AssertionError("accepted a claim with %s" % fields)
	assert frappe.db.count(CLAIM) == before, "a refused claim left a row behind"

	ok = _submit(cleanup, expense_type="Others", note="Cannula for the patient")
	assert ok["note"] == "Cannula for the patient"


def test_a_claim_can_only_name_the_claimants_own_visit(cleanup):
	mine = _visit(cleanup)
	theirs = _visit(cleanup, technician=OTHER_TECH, user=OTHER_USER)

	assert _submit(cleanup, visit_id=mine)["visit"] == mine
	try:
		_submit(cleanup, visit_id=theirs)
	except frappe.ValidationError:
		return
	raise AssertionError("a claim named another technician's visit")


def test_a_pending_claim_is_edited_or_withdrawn_by_its_technician_only(cleanup):
	from nhk.api import expense_claims as api

	res = _submit(cleanup)
	edited = _as(PILOT_USER, api.update_claim, res["name"], amount="650", expense_type="Others", note="Battery")
	assert (edited["amount"], edited["expense_type"], edited["note"]) == (650, "Others", "Battery"), edited
	account = frappe.db.get_value("Expense Claim Detail", {"parent": res["name"]}, "default_account")
	assert account == frappe.db.get_value("Expense Claim Account", {"parent": "Others"}, "default_account"), \
		"the row kept the old type's account"

	assert _refused(frappe.DoesNotExistError, OTHER_USER, api.update_claim, res["name"], amount="1")
	assert _refused(frappe.DoesNotExistError, OTHER_USER, api.withdraw_claim, res["name"])

	receipt = res["receipt"]
	_as(PILOT_USER, api.withdraw_claim, res["name"])
	assert not frappe.db.exists(CLAIM, res["name"])
	assert not frappe.db.exists("File", {"file_url": receipt}), "the screenshot outlived the claim"


# --------------------------------------------------------------------------
# the office, on the desk
# --------------------------------------------------------------------------

def test_the_office_approves_submits_and_pays_on_the_desk(cleanup):
	from nhk.api import expense_claims as api

	_payable_account_set(cleanup)
	paid, approved = _submit(cleanup), _submit(cleanup)

	_on_the_desk(cleanup, paid["name"], "Approved", paid=True)
	_on_the_desk(cleanup, approved["name"], "Approved")

	now = {c.name: c for c in _as(PILOT_USER, api.my_claims)["claims"]}
	assert (now[paid["name"]].status, now[paid["name"]].can_edit) == ("Paid", False), now[paid["name"]]
	assert now[approved["name"]].status == "Approved", "approved but not yet paid"
	desk = frappe.db.get_value(CLAIM, approved["name"], ["status", "total_claimed_amount", "total_sanctioned_amount"],
							   as_dict=True)
	assert desk.total_sanctioned_amount == desk.total_claimed_amount > 0, "approved as filed, sanctioned at 0"
	assert desk.status == "Unpaid", "HRMS left it neither Unpaid nor Paid"
	assert frappe.db.exists("GL Entry", {"voucher_type": CLAIM, "voucher_no": paid["name"]}), "paid posted nothing"

	# Decided: the technician can no longer change or withdraw it.
	assert _refused(frappe.ValidationError, PILOT_USER, api.update_claim, paid["name"], amount="1")
	assert _refused(frappe.ValidationError, PILOT_USER, api.withdraw_claim, approved["name"])


def test_the_office_rejects_on_the_desk(cleanup):
	from nhk.api import expense_claims as api

	_payable_account_set(cleanup)  # HRMS wants it to submit, even a rejection
	res = _submit(cleanup)
	_on_the_desk(cleanup, res["name"], "Rejected")
	assert api._one(res["name"])["status"] == "Rejected"
	assert not frappe.db.exists("GL Entry", {"voucher_type": CLAIM, "voucher_no": res["name"]})
	assert _refused(frappe.ValidationError, PILOT_USER, api.withdraw_claim, res["name"])


def test_an_approved_claim_not_yet_submitted_is_no_longer_the_technicians(cleanup):
	from nhk.api import expense_claims as api

	res = _submit(cleanup)
	frappe.db.set_value(CLAIM, res["name"], "approval_status", "Approved")
	assert api._one(res["name"])["status"] == "Approved"
	assert _refused(frappe.ValidationError, PILOT_USER, api.update_claim, res["name"], amount="1")


def test_the_office_gets_a_bell_for_a_new_claim(cleanup):
	from nhk.api import expense_claims as api

	alerts, real = [], api._office_alert
	api._office_alert = lambda user, subject, claim: alerts.append((user, subject))
	try:
		res = _submit(cleanup)
		api._notify_office(res["name"], PILOT_USER)
	finally:
		api._office_alert = real
	told = {u for u, _ in alerts}
	assert told and PILOT_USER not in told, alerts
	assert set(api.office_users()) - {PILOT_USER} == told


# --------------------------------------------------------------------------
# the payout page
# --------------------------------------------------------------------------

def test_expenses_show_on_the_month_but_not_in_the_total(cleanup):
	from nhk.api import payouts
	from test_visits import _office_user

	month = "2019-05"
	_done(cleanup, month, charges=100)
	paid = [_paid(cleanup, amount=300), _paid(cleanup, amount=200, expense_date="2019-05-31")]
	_paid(cleanup, amount=999, expense_date="2019-06-01")              # another month
	_paid(cleanup, technician=OTHER_TECH, amount=150)                  # expenses only, no visits
	paid.append(_paid(cleanup, amount=40, status="Draft"))             # pending: counted, as claimed
	paid.append(_paid(cleanup, amount=60, status="Unpaid"))            # submitted, not yet paid: counted
	_paid(cleanup, amount=7000, status="Rejected")                     # rejected: not counted

	summary = _as(_office_user(), payouts.month_summary, month)
	mine, theirs = _row(summary, PILOT_TECH), _row(summary, OTHER_TECH)
	assert (mine.expense_count, mine.expenses) == (4, 600), mine
	assert mine.total == 100, "expenses were added to the total: %s" % mine
	assert (theirs.expenses, theirs.total, theirs.visit_count) == (150, 0, 0), theirs
	assert summary["totals"]["expenses"] == 750 and summary["totals"]["total"] == 100, summary["totals"]

	drill = _as(_office_user(), payouts.technician_expenses, month, PILOT_TECH)
	assert sorted(c.name for c in drill) == sorted(paid), drill
	assert {c.status for c in drill} == {"Paid", "Unpaid", "Draft"}, drill

	# The popup names the patient of the visit a claim was for.
	visit = _visit(cleanup)
	frappe.db.set_value(CLAIM, paid[0], "custom_visit", visit, update_modified=False)
	row = next(c for c in _as(_office_user(), payouts.technician_expenses, month, PILOT_TECH) if c.name == paid[0])
	assert (row.visit, row.patient_name) == (visit, frappe.db.get_value("Technician Visit Entry", visit, "patient_name"))


if __name__ == "__main__":
	import harness
	raise SystemExit(harness.run(sys.modules[__name__]))
