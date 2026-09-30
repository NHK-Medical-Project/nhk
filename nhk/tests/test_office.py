"""The NHK Technician workspace's Technician Visits block (`nhk.api.office`).

Run:  cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_office.py
"""

import sys

import frappe
from frappe.utils import add_days, today

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from test_staff_api import PILOT_USER, _visit


def _order(finished=False):
	"""A real Sales Order that is -- or is not -- finished."""
	from nhk.api.office import FINISHED_ORDER_STATUSES

	op = "in" if finished else "not in"
	return frappe.db.get_value("Sales Order", {"status": (op, FINISHED_ORDER_STATUSES), "docstatus": 1}, "name")


def _day(date=None):
	from nhk.api import office

	return office.technician_visits(date)


def _group_of(result, visit):
	return next((r["group"] for r in result["rows"] if r["name"] == visit), None)


def _completed_today(cleanup, order):
	visit = _visit(cleanup, response="Accepted", status="Delivered", sales_order=order)
	frappe.db.set_value("Technician Visit Entry", visit, "completed_at", frappe.utils.now_datetime(), update_modified=False)
	return visit


def test_the_day_opens_on_today(cleanup):
	assert _day()["date"] == today()


def test_every_visit_of_the_day_is_in_one_group_and_the_total_adds_up(cleanup):
	order = _order()
	pending = _visit(cleanup, response="Pending", sales_order=order)
	accepted = _visit(cleanup, response="Accepted", sales_order=order)
	rejected = _visit(cleanup, response="Rejected", sales_order=order)
	completed = _completed_today(cleanup, order)

	result = _day()
	assert [_group_of(result, v) for v in (pending, accepted, rejected, completed)] == [
		"Pending", "Accepted", "Rejected", "Completed"]
	counts = result["counts"]
	assert counts["Total"] == sum(counts[g] for g in ("Pending", "Accepted", "Rejected", "Completed")) == len(result["rows"])


def test_a_visit_belongs_to_the_day_it_is_scheduled_for_or_completed_on(cleanup):
	order = _order()
	tomorrow = add_days(today(), 1)
	scheduled = _visit(cleanup, response="Pending", sales_order=order)
	frappe.db.set_value("Technician Visit Entry", scheduled, "scheduled_datetime", tomorrow + " 10:00:00")
	done_yesterday = _visit(cleanup, response="Accepted", status="Delivered", sales_order=order)
	frappe.db.set_value("Technician Visit Entry", done_yesterday, "completed_at",
						add_days(today(), -1) + " 12:00:00", update_modified=False)

	assert _group_of(_day(), scheduled) is None
	assert _group_of(_day(tomorrow), scheduled) == "Pending"
	assert _group_of(_day(), done_yesterday) is None
	assert _group_of(_day(add_days(today(), -1)), done_yesterday) == "Completed"


def test_rows_say_what_the_sales_order_says(cleanup):
	"""The same words as the order's visit table, not new ones."""
	from nhk.api.visits import _describe

	visit = _visit(cleanup, response="Rejected", sales_order=_order())
	frappe.db.set_value("Technician Visit Entry", visit, "rejection_reason", "Bike Service")
	row = next(r for r in _day()["rows"] if r["name"] == visit)
	assert (row["stage"], row["next_step"]) == _describe(row), row
	assert "Reassign" in row["next_step"], row


def test_rows_carry_the_payment_status_and_what_was_collected(cleanup):
	from nhk.custom_script import get_sales_order_details
	from test_payment_collection import _collect, _job

	visit, order = _job(cleanup)
	_collect(cleanup, visit, mode_of_payment="Cash", rental_payment_amount=100)

	row = next(r for r in _day()["rows"] if r["name"] == visit)
	d = get_sales_order_details(order)
	owed = d["rental_payment_status"] in ("Unpaid", "Partially Paid") or d["security_deposit_payment_status"] in (
		"Unpaid", "Partially Paid")
	assert row["payment_status"] == ("Pending" if owed else "Paid"), row["payment_status"]
	assert row["payments"] == [{"mode_of_payment": "Cash", "amount": 100, "status": "Draft"}], row["payments"]


def test_visits_left_open_on_a_finished_order_are_not_shown(cleanup):
	visit = _visit(cleanup, response="Pending", sales_order=_order(finished=True))
	assert _group_of(_day(), visit) is None


def test_only_the_office_sees_the_day(cleanup):
	frappe.set_user(PILOT_USER)
	try:
		_day()
	except frappe.PermissionError:
		return
	finally:
		frappe.set_user("Administrator")
	raise AssertionError("a technician read the office's day")


if __name__ == "__main__":
	import harness
	raise SystemExit(harness.run(sys.modules[__name__]))
