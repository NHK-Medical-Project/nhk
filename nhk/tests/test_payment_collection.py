"""Collecting the patient's payment from the app (`nhk.api.payment_collection`).

Run:  cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_payment_collection.py

Against a real open order with rent and a deposit owed. Every entry a test
makes is a Draft and is deleted afterwards; the order's pending-reason fields
are put back.
"""

import sys

import frappe

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from test_staff_api import OTHER_USER, PILOT_USER, _as, _on_duty, _visit


def _order_owing():
	"""A real open order with rent and a security deposit still owed."""
	from nhk.custom_script import get_sales_order_details

	for name in frappe.get_all(
		"Sales Order",
		filters={"docstatus": 1, "status": ("not in", ("Completed", "Closed", "Cancelled")), "rounded_total": (">", 0)},
		pluck="name", order_by="creation desc", limit=40,
	):
		d = get_sales_order_details(name)
		if d["unpaid_rental_amount"] > 100 and d["unpaid_security_deposit_amount"] > 100:
			return name
	raise AssertionError("no open order owing rent and a deposit on this site")


def _job(cleanup, response="Accepted", duty=True):
	order = _order_owing()
	for field in ("reason_for_payment_pending", "payment_pending_reason"):
		cleanup.restore("Sales Order", order, field)
	visit = _visit(cleanup, response=response, sales_order=order)
	if duty:
		_on_duty(cleanup)
	return visit, order


def _call(fn, *args, **kwargs):
	_as(PILOT_USER)
	try:
		return fn(*args, **kwargs)
	finally:
		_as("Administrator")


def _collect(cleanup, visit, **kwargs):
	from nhk.api import payment_collection

	result = _call(payment_collection.collect, visit, **kwargs)
	for name in result["created"]:
		cleanup.add("Payment Entry" if name.startswith("ACC-PAY") else "Journal Entry", name)
	return result


def test_the_form_shows_what_the_desk_shows(cleanup):
	from nhk.api import payment_collection
	from nhk.custom_script import get_sales_order_details

	visit, order = _job(cleanup)
	summary = _call(payment_collection.for_visit, visit)
	d = get_sales_order_details(order)

	assert summary["rental_balance"] == d["unpaid_rental_amount"]
	assert summary["security_deposit_balance"] == d["unpaid_security_deposit_amount"]
	assert summary["pending"] is True
	assert "Cash" in [m["name"] for m in summary["modes_of_payment"]]
	assert {m["name"]: m["needs_reference"] for m in summary["modes_of_payment"]}.get("Bank Draft") is True
	assert summary["payment_pending_reasons"], "the office's Payment Pending Reason list is empty"


def test_make_payment_leaves_both_entries_in_draft(cleanup):
	visit, order = _job(cleanup)
	before = _call(__import__("nhk.api.payment_collection", fromlist=["x"]).for_visit, visit)

	result = _collect(cleanup, visit, mode_of_payment="Cash", rental_payment_amount=100,
					  security_deposit_payment_amount=50, remark="test")

	assert len(result["created"]) == 2, result["created"]
	pe = frappe.get_doc("Payment Entry", next(n for n in result["created"] if n.startswith("ACC-PAY")))
	assert pe.docstatus == 0, "a technician's payment was submitted"
	assert (pe.paid_amount, pe.mode_of_payment, pe.custom_technician_visit_id) == (100, "Cash", visit)
	je = frappe.get_doc("Journal Entry", next(n for n in result["created"] if not n.startswith("ACC-PAY")))
	assert je.docstatus == 0 and je.total_debit == 50 and je.custom_technician_visit_entry_id == visit
	# Drafts count as paid, as on the desk, so the same money cannot be taken twice.
	assert result["rental_balance"] == before["rental_balance"] - 100
	assert result["security_deposit_balance"] == before["security_deposit_balance"] - 50
	assert {e["name"]: e["status"] for e in result["entries"]}[pe.name] == "Draft"


def test_make_payment_refuses_what_the_desk_refuses(cleanup):
	from nhk.api import payment_collection

	visit, order = _job(cleanup)
	balance = _call(payment_collection.for_visit, visit)["rental_balance"]
	for kwargs, words in (
		({"mode_of_payment": "Cash"}, "Enter the amount"),
		({"mode_of_payment": "Cash", "rental_payment_amount": balance + 1}, "cannot be more than the balance"),
		({"mode_of_payment": "Bank Draft", "rental_payment_amount": 10}, "Cheque/Reference No"),
		({"mode_of_payment": "No Such Mode", "rental_payment_amount": 10}, "Mode Of Payment"),
		({"mode_of_payment": "Cash", "rental_payment_amount": 10, "payment_date": "2099-01-01"}, "future"),
	):
		try:
			_collect(cleanup, visit, **kwargs)
		except frappe.ValidationError as exc:
			assert words in str(exc), (kwargs, str(exc))
			continue
		raise AssertionError("accepted %s" % kwargs)
	assert not frappe.db.exists("Payment Entry", {"custom_technician_visit_id": visit})


def test_pending_needs_a_reason_and_is_written_on_the_order(cleanup):
	from nhk.api import payment_collection

	visit, order = _job(cleanup)
	offered = _call(payment_collection.for_visit, visit)["payment_pending_reasons"]
	assert offered and not set(offered) & set(payment_collection.NOT_PENDING_REASONS), offered
	reason = offered[0]
	for wrong in ("", "Paid"):
		try:
			_call(payment_collection.mark_pending, visit, reason=wrong)
		except frappe.ValidationError:
			continue
		raise AssertionError("pending was accepted with the reason %r" % wrong)

	summary = _call(payment_collection.mark_pending, visit, reason=reason, notes="  Will pay on Friday ")
	assert frappe.db.get_value("Sales Order", order, ["reason_for_payment_pending", "payment_pending_reason"]) == (
		reason, "Will pay on Friday")
	assert (summary["reason_for_payment_pending"], summary["payment_pending_reason"]) == (reason, "Will pay on Friday")


def test_only_the_technician_on_the_job_collects(cleanup):
	from nhk.api import payment_collection
	from nhk.api.guards import OffDuty

	visit, order = _job(cleanup, response="Pending")
	try:
		_call(payment_collection.for_visit, visit)
	except frappe.ValidationError as exc:
		assert "Accept" in str(exc)
	else:
		raise AssertionError("collected on a job not yet accepted")

	accepted, _order = _job(cleanup, duty=False)
	frappe.set_user(OTHER_USER)
	try:
		payment_collection.for_visit(accepted)
	except (frappe.PermissionError, OffDuty, frappe.ValidationError):
		pass
	else:
		raise AssertionError("another technician read this job's payment")
	finally:
		frappe.set_user("Administrator")



def test_a_payment_can_be_taken_after_delivery_or_pickup(cleanup):
	"""The patient often pays when the device arrives or leaves, after the
	technician has marked it (2026-10-10)."""
	from nhk.api import payment_collection, staff

	for done in ("Delivered", "Picked up"):
		visit, _order = _job(cleanup)
		frappe.db.set_value("Technician Visit Entry", visit, "status", done)

		assert _call(staff.job, visit)["can_collect_payment"] is True, done
		result = _collect(cleanup, visit, mode_of_payment="Cash", rental_payment_amount=100)
		assert result["created"], (done, result)
		frappe.set_user("Administrator")
		# Leave the duty check-in for the next round's own `_on_duty`.
		frappe.db.set_value("Technician Check In", {"technician_id": "NHK-TEC-002", "kind": "Duty",
													 "closed_at": ("is", "not set")},
							"closed_at", frappe.utils.now_datetime())


def test_a_visit_closed_from_the_desk_without_an_answer_still_takes_a_payment(cleanup):
	"""TEC-10-26-26352: Delivered from the desk, `technician_response` still
	Pending, rent owed. Most done visits look like this."""
	from nhk.api import staff

	visit, _order = _job(cleanup, response="Pending")
	frappe.db.set_value("Technician Visit Entry", visit, "status", "Delivered")
	assert _call(staff.job, visit)["can_collect_payment"] is True
	assert _collect(cleanup, visit, mode_of_payment="Cash", rental_payment_amount=100)["created"]


def test_a_rejected_done_visit_and_an_unaccepted_open_one_take_none(cleanup):
	from nhk.api import payment_collection, staff

	rejected, _order = _job(cleanup, response="Rejected")
	frappe.db.set_value("Technician Visit Entry", rejected, "status", "Picked up")
	assert payment_collection.can_collect(frappe.get_doc("Technician Visit Entry", rejected)) is False

	open_pending, _order2 = _job(cleanup, response="Pending", duty=False)
	assert _call(staff.job, open_pending)["can_collect_payment"] is False

def test_not_once_the_payout_run_has_the_visit(cleanup):
	from nhk.api import payment_collection, staff

	visit, _order = _job(cleanup)
	frappe.db.set_value("Technician Visit Entry", visit, "status", "Incentive Finalize")
	assert _call(staff.job, visit)["can_collect_payment"] is False
	try:
		_call(payment_collection.for_visit, visit)
	except frappe.ValidationError as exc:
		assert "Incentive Finalize" in str(exc), exc
	else:
		raise AssertionError("a payment was offered on a visit in the payout run")

if __name__ == "__main__":
	import harness
	raise SystemExit(harness.run(sys.modules[__name__]))
