"""Collecting the patient's payment from the technician app.

The desk already does this. The visit form's "Create Payment Entry" opens
"Enter Payment Details" and calls the ERPNext fork's
`sales_order.process_payment` with `from_technician_portal=1`, which makes a
Payment Entry for the rent and a Journal Entry for the security deposit and
**leaves both in Draft** for the office to check and submit. The app takes the
same road with the same numbers -- `nhk.custom_script.get_sales_order_details`,
whose unpaid amounts already subtract earlier drafts, so nothing is collected
twice -- and the same accounts (`sales_order.get_default_account`).

When the patient does not pay, the technician says why, in the Sales Order's
own "Payment Pending Reason" section: **Reason For Payment Pending** (a
`Payment Pending Reason` from the office's list) and **Payment Pending Reason**
(the note). The desk's DELIVERED dialog asks for the same two.

Gates are the app's usual ones: on duty, the caller's own visit, still
`Assigned` -- the desk only offers "Create Payment Entry" then -- and accepted.
Nothing here is submitted, and nothing needs the technician to have
permission on Sales Order, Payment Entry or Journal Entry.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from nhk.api import notify
from nhk.api.guards import assert_accepted, assert_on_duty, current_technician, owned_visit

#: Modes the desk asks a Cheque/Reference No and Date for (the visit form's
#: `create_payment_entry`).
REFERENCE_MODES = ("Bank Draft", "Kotak Bank", "Razorpay")

#: Words the desk shows for a document's `docstatus`.
DOC_STATUS = {0: "Draft", 1: "Submitted", 2: "Cancelled"}

#: `Payment Pending Reason` records that are not reasons -- statuses and a test
#: entry, still linked from thousands of orders so they cannot be deleted. Not
#: offered in the app (decided 2026-09-30).
NOT_PENDING_REASONS = ("test", "Paid", "DELIVERED", "DELIVERED DONE")

#: `get_sales_order_details` statuses that mean something is still owed.
OWED = ("Unpaid", "Partially Paid")


def _open_visit(visit_id):
	technician = current_technician()
	assert_on_duty(technician)
	visit = owned_visit(visit_id, technician=technician)
	if visit.status != "Assigned":
		frappe.throw(_("The office already marked this job {0}.").format(visit.status))
	assert_accepted(visit)
	if not visit.sales_order_id:
		frappe.throw(_("Visit {0} has no Sales Order to collect for.").format(visit.name))
	return visit


def _details(sales_order):
	from nhk.custom_script import get_sales_order_details

	return frappe._dict(get_sales_order_details(sales_order))


@frappe.whitelist()
def for_visit(visit_id):
	"""What the patient owes on the visit's order, the entries made so far, and
	the lists the form needs: modes of payment and pending reasons."""
	visit = _open_visit(visit_id)
	return _summary(visit)


def _summary(visit):
	d = _details(visit.sales_order_id)
	pending = frappe.db.get_value(
		"Sales Order", visit.sales_order_id,
		["reason_for_payment_pending", "payment_pending_reason"], as_dict=True,
	) or {}
	entries = [
		{"type": "Payment Entry", "name": e.name, "posting_date": e.posting_date,
		 "amount": flt(e.amount), "status": DOC_STATUS.get(e.docstatus, "")}
		for e in d.payment_entries
	] + [
		{"type": "Journal Entry", "name": e.name, "posting_date": e.posting_date,
		 "amount": flt(e.amount), "status": DOC_STATUS.get(e.docstatus, "")}
		for e in d.journal_entries
	]
	entries.sort(key=lambda e: (str(e["posting_date"] or ""), e["name"]), reverse=True)

	return {
		"sales_order": visit.sales_order_id,
		"customer": d.customer,
		"customer_name": d.customer_name,
		"rental_payment_status": d.rental_payment_status,
		"rental_balance": flt(d.unpaid_rental_amount),
		"security_deposit_payment_status": d.security_deposit_payment_status,
		"security_deposit_balance": flt(d.unpaid_security_deposit_amount),
		# "Pending" while anything is owed: the section's own word on the order.
		"pending": d.rental_payment_status in OWED or d.security_deposit_payment_status in OWED,
		"reason_for_payment_pending": pending.get("reason_for_payment_pending"),
		"payment_pending_reason": pending.get("payment_pending_reason"),
		"entries": entries,
		"modes_of_payment": _modes(),
		"payment_pending_reasons": _pending_reasons(),
	}


def _pending_reasons():
	return [
		name for name in frappe.get_all("Payment Pending Reason", pluck="name", order_by="creation")
		if name not in NOT_PENDING_REASONS
	]


def _modes():
	"""Enabled modes with an account to receive into; the rest would post to a
	guessed account."""
	with_account = set(frappe.get_all(
		"Mode of Payment Account", filters={"default_account": ("is", "set")}, pluck="parent"
	))
	return [
		{"name": name, "needs_reference": name in REFERENCE_MODES}
		for name in frappe.get_all("Mode of Payment", filters={"enabled": 1}, pluck="name", order_by="name")
		if name in with_account
	]


@frappe.whitelist()
def collect(visit_id, mode_of_payment, rental_payment_amount=0, security_deposit_payment_amount=0,
			reference_no=None, reference_date=None, payment_date=None, remark=None):
	"""Make Payment: the desk's `process_payment`, from the technician portal, so
	the entries stay in Draft."""
	from erpnext.selling.doctype.sales_order.sales_order import get_default_account, process_payment

	visit = _open_visit(visit_id)
	d = _details(visit.sales_order_id)
	rent, deposit = flt(rental_payment_amount), flt(security_deposit_payment_amount)
	payment_date = payment_date or today()

	if rent < 0 or deposit < 0:
		frappe.throw(_("Payment amounts cannot be negative."))
	if rent + deposit <= 0:
		frappe.throw(_("Enter the amount collected."))
	if rent > flt(d.unpaid_rental_amount):
		frappe.throw(_("Rental Payment Amount cannot be more than the balance, {0}.").format(
			frappe.format_value(d.unpaid_rental_amount, "Currency")))
	if deposit > flt(d.unpaid_security_deposit_amount):
		frappe.throw(_("Security Deposit Payment Amount cannot be more than the balance, {0}.").format(
			frappe.format_value(d.unpaid_security_deposit_amount, "Currency")))
	if mode_of_payment not in {m["name"] for m in _modes()}:
		frappe.throw(_("Choose a Mode Of Payment."))
	if mode_of_payment in REFERENCE_MODES and not (reference_no and reference_date):
		frappe.throw(_("{0} needs the Cheque/Reference No and Date.").format(mode_of_payment))
	if getdate(payment_date) > getdate(today()):
		frappe.throw(_("Payment Date cannot be in the future."))

	accounts = get_default_account(mode_of_payment)
	started = frappe.utils.now_datetime()
	process_payment(
		balance_amount=flt(d.balance_amount),
		outstanding_security_deposit_amount=flt(d.outstanding_security_deposit_amount),
		customer_name=d.customer,
		rental_payment_amount=rent,
		sales_order_name=visit.sales_order_id,
		master_order_id=d.master_order_id,
		security_deposit_status=d.security_deposit_status,
		customer=d.customer,
		payment_date=payment_date,
		payment_account=accounts.get("default_account") if rent else None,
		security_deposit_account=accounts.get("journal_entry_default_account") if deposit else None,
		reference_no=reference_no,
		reference_date=reference_date,
		mode_of_payment=mode_of_payment,
		security_deposit_payment_amount=deposit,
		remark=remark,
		from_technician_portal=1,
		technician_id=visit.technician_id,
		technician_visit_id=visit.name,
	)
	# process_payment says "created successfully" through msgprint; the app
	# shows its own confirmation.
	frappe.local.message_log = []

	made = frappe.get_all(
		"Payment Entry", filters={"custom_technician_visit_id": visit.name, "creation": (">=", started)}, pluck="name"
	) + frappe.get_all(
		"Journal Entry", filters={"custom_technician_visit_entry_id": visit.name, "creation": (">=", started)}, pluck="name"
	)
	amount = frappe.format_value(rent + deposit, "Currency")
	visit.add_comment("Comment", _("Payment collected: {0} by {1}. Draft {2}, for the office to submit.").format(
		amount, mode_of_payment, ", ".join(made)))
	notify.tell_office_about(visit, _("{0} collected {1} ({2}) on {3}. Submit draft {4}.").format(
		visit.technician_name or visit.technician_id, amount, mode_of_payment, visit.sales_order_id, ", ".join(made)))

	summary = _summary(visit)
	summary["created"] = made
	return summary


@frappe.whitelist()
def mark_pending(visit_id, reason, notes=None):
	"""The patient did not pay: why, on the order's Payment Pending Reason section."""
	visit = _open_visit(visit_id)
	if reason not in _pending_reasons():
		frappe.throw(_("Choose the Reason For Payment Pending."))
	notes = (notes or "").strip() or None

	# The order is submitted and the technician holds no permission on it; the
	# desk's DELIVERED writes the same two fields the same way.
	frappe.db.set_value("Sales Order", visit.sales_order_id, {
		"reason_for_payment_pending": reason,
		"payment_pending_reason": notes,
	})
	text = reason + (": " + notes if notes else "")
	visit.add_comment("Comment", _("Payment pending: {0}").format(text))
	notify.tell_office_about(visit, _("{0}: payment pending on {1}. {2}").format(
		visit.technician_name or visit.technician_id, visit.sales_order_id, text))
	return _summary(visit)
