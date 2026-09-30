"""The NHK Technician workspace's Technician Visits block (`nhk.api.office`).

Run:  cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_office.py
"""

import sys

import frappe

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from test_staff_api import PILOT_TECH, PILOT_USER, _visit


def _order(finished=False):
	"""A real Sales Order that is -- or is not -- finished."""
	from nhk.api.office import FINISHED_ORDER_STATUSES

	op = "in" if finished else "not in"
	return frappe.db.get_value("Sales Order", {"status": (op, FINISHED_ORDER_STATUSES), "docstatus": 1}, "name")


def _queue(days=30):
	from nhk.api import office

	return office.technician_visits(days)


def _names(result, response):
	return {r["name"] for r in result["rows"] if r["technician_response"] == response}


def test_open_visits_are_sorted_by_the_technicians_answer(cleanup):
	order = _order()
	before = _queue()["counts"]
	pending = _visit(cleanup, response="Pending", sales_order=order)
	rejected = _visit(cleanup, response="Rejected", sales_order=order)
	accepted = _visit(cleanup, response="Accepted", sales_order=order)
	_visit(cleanup, response="Accepted", status="Delivered", sales_order=order)  # done: not open

	result = _queue()
	assert pending in _names(result, "Pending") and rejected in _names(result, "Rejected")
	assert accepted in _names(result, "Accepted")
	assert result["counts"] == {k: before[k] + 1 for k in before}, (before, result["counts"])


def test_rows_say_what_the_sales_order_says(cleanup):
	"""The same words as the order's visit table, not new ones."""
	from nhk.api.visits import _describe

	visit = _visit(cleanup, response="Rejected", sales_order=_order())
	frappe.db.set_value("Technician Visit Entry", visit, "rejection_reason", "Bike Service")
	row = next(r for r in _queue()["rows"] if r["name"] == visit)
	assert (row["stage"], row["next_step"]) == _describe(row), row
	assert "Reassign" in row["next_step"], row


def test_old_visits_wait_for_all_open_but_rejected_ones_never_do(cleanup):
	order = _order()
	old_pending = _visit(cleanup, response="Pending", age_days=90, sales_order=order)
	old_rejected = _visit(cleanup, response="Rejected", age_days=90, sales_order=order)

	recent = _queue(30)
	assert old_pending not in _names(recent, "Pending")
	assert old_rejected in _names(recent, "Rejected"), "a rejected visit needs reassigning, however old"
	assert old_pending in _names(_queue(0), "Pending")


def test_visits_left_open_on_a_finished_order_are_not_in_the_queue(cleanup):
	finished = _order(finished=True)
	visit = _visit(cleanup, response="Pending", sales_order=finished)
	assert visit not in {r["name"] for r in _queue(0)["rows"]}


def test_a_past_scheduled_time_is_flagged(cleanup):
	visit = _visit(cleanup, response="Accepted", sales_order=_order())
	frappe.db.set_value("Technician Visit Entry", visit, "scheduled_datetime", "2020-01-01 10:00:00")
	row = next(r for r in _queue(0)["rows"] if r["name"] == visit)
	assert row["past_scheduled"] is True


def test_every_technician_is_listed_with_their_open_jobs(cleanup):
	order = _order()
	before = next(t for t in _queue()["technicians"] if t["name"] == PILOT_TECH)
	_visit(cleanup, response="Pending", sales_order=order)
	_visit(cleanup, response="Rejected", sales_order=order)            # not theirs to do now
	after = next(t for t in _queue()["technicians"] if t["name"] == PILOT_TECH)

	assert (after["pending"], after["accepted"]) == (before["pending"] + 1, before["accepted"]), (before, after)
	assert len(_queue()["technicians"]) == frappe.db.count("Technician Details")


def test_the_technicians_numbers_add_up_to_the_tabs(cleanup):
	"""Picking a technician shows exactly the visits their numbers promise, in
	either window -- found 2026-09-30: 7 Pending beside a name, 0 rows."""
	order = _order()
	_visit(cleanup, response="Pending", age_days=90, sales_order=order)
	for days in (30, 0):
		result = _queue(days)
		people = result["technicians"]
		for response, key in (("Pending", "pending"), ("Accepted", "accepted")):
			assert sum(t[key] for t in people) == result["counts"][response], (days, response)
		if not result["limited"]:
			pilot = next(t for t in people if t["name"] == PILOT_TECH)
			shown = [r for r in result["rows"] if r["technician_id"] == PILOT_TECH and r["technician_response"] == "Pending"]
			assert pilot["pending"] == len(shown), (days, pilot, len(shown))


def test_only_the_office_sees_the_queue(cleanup):
	frappe.set_user(PILOT_USER)
	try:
		_queue()
	except frappe.PermissionError:
		return
	finally:
		frappe.set_user("Administrator")
	raise AssertionError("a technician read the office's queue")


if __name__ == "__main__":
	import harness
	raise SystemExit(harness.run(sys.modules[__name__]))
