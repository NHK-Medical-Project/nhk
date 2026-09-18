"""Behaviour of the technician staff app API (`nhk.api.staff`).

Run:  cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_staff_api.py
"""

import sys
from datetime import datetime, timedelta

import frappe

sys.path.insert(0, __file__.rsplit("/", 1)[0])

PILOT_TECH = "NHK-TEC-002"  # Basawaraj -- the one technician with real assignments
PILOT_USER = "basawaraja.nhkmedical@gmail.com"
OTHER_TECH = "NHK-TEC-003"
OTHER_USER = "suvam.nirmalhealthcare@gmail.com"


def _visit(cleanup, technician=PILOT_TECH, user=PILOT_USER, age_days=0, status="Assigned",
		   type_="Delivery", response="Accepted"):
	"""Create a Technician Visit Entry owned by `technician`, `age_days` old.

	Accepted by default: most tests here are about what happens *after* the
	technician has taken the job on, and the acceptance gate has its own tests.
	"""
	so = frappe.db.get_value("Technician Visit Entry", {"sales_order_id": ("is", "set")}, "sales_order_id")
	doc = frappe.get_doc({
		"doctype": "Technician Visit Entry",
		"technician_id": technician,
		"technician_user_id": user,
		"sales_order_id": so,
		"type": type_,
		"status": status,
		"technician_category": "Order",
		"kilometers": 5,
		"technician_response": response,
	}).insert(ignore_permissions=True)
	cleanup.add("Technician Visit Entry", doc.name)

	if age_days:
		old = datetime.now() - timedelta(days=age_days)
		frappe.db.set_value("Technician Visit Entry", doc.name, "creation", old, update_modified=False)
		frappe.db.set_value("Technician Visit Entry", doc.name, "scheduled_datetime", old, update_modified=False)

	frappe.share.add("Technician Visit Entry", doc.name, user, read=1, write=1)
	return doc.name


def _as(user):
	frappe.set_user(user)


def _on_duty(cleanup, user=PILOT_USER):
	"""Put `user` on duty and register the check-in for cleanup.

	Reading anything at all needs this now: `my_jobs` and `job` refuse off duty.
	"""
	from nhk.api import staff

	_as(user)
	return cleanup.add("Technician Check In", staff.start_duty()["name"])


# --------------------------------------------------------------------------
# identity and ownership
# --------------------------------------------------------------------------

def test_my_jobs_returns_only_the_callers_jobs(cleanup):
	from nhk.api import staff

	mine = _visit(cleanup)
	theirs = _visit(cleanup, technician=OTHER_TECH, user=OTHER_USER)

	_on_duty(cleanup)
	names = {j["name"] for j in staff.my_jobs()}
	assert mine in names, "own job missing from my_jobs"
	assert theirs not in names, "my_jobs leaked another technician's job"


def test_job_refuses_a_foreign_visit(cleanup):
	from nhk.api import staff

	theirs = _visit(cleanup, technician=OTHER_TECH, user=OTHER_USER)
	_on_duty(cleanup)
	try:
		staff.job(theirs)
	except frappe.DoesNotExistError:
		return
	raise AssertionError("staff.job returned another technician's visit")


def test_my_jobs_hides_the_stale_backlog_by_default(cleanup):
	from nhk.api import staff

	fresh = _visit(cleanup, age_days=1)
	stale = _visit(cleanup, age_days=40)

	_on_duty(cleanup)
	names = {j["name"] for j in staff.my_jobs()}
	assert fresh in names, "fresh job missing"
	assert stale not in names, "40-day-old job should be in the backlog, not the day list"

	backlog = {j["name"] for j in staff.my_jobs(include_backlog=True)}
	assert stale in backlog, "backlog view should include the stale job"


# --------------------------------------------------------------------------
# duty check-in
# --------------------------------------------------------------------------

def test_start_duty_creates_a_duty_checkin(cleanup):
	from nhk.api import staff

	_as(PILOT_USER)
	res = staff.start_duty(latitude=12.97, longitude=77.59, accuracy=8.0)
	cleanup.add("Technician Check In", res["name"])

	assert res["kind"] == "Duty"
	assert staff.duty_status()["on_duty"] is True


def test_duty_from_yesterday_does_not_count_as_on_duty(cleanup):
	from nhk.api import staff

	_as(PILOT_USER)
	res = staff.start_duty(latitude=12.97, longitude=77.59)
	cleanup.add("Technician Check In", res["name"])

	yesterday = datetime.now() - timedelta(days=1)
	frappe.db.set_value("Technician Check In", res["name"], "checked_in_at", yesterday)

	assert staff.duty_status()["on_duty"] is False, "duty must expire at local midnight"


def test_my_jobs_refuses_off_duty(cleanup):
	"""Off duty there is nothing to read -- not a filtered list, nothing.

	A phone that is not on shift should not be holding patient names, addresses
	and outstanding balances on screen.
	"""
	from nhk.api import staff
	from nhk.api.guards import OffDuty

	_visit(cleanup)
	_as(PILOT_USER)
	try:
		staff.my_jobs()
	except OffDuty:
		return
	raise AssertionError("my_jobs answered off duty")


def test_job_refuses_off_duty(cleanup):
	from nhk.api import staff
	from nhk.api.guards import OffDuty

	visit = _visit(cleanup)
	_as(PILOT_USER)
	try:
		staff.job(visit)
	except OffDuty:
		return
	raise AssertionError("job answered off duty")


def test_end_duty_closes_the_day_and_records_where(cleanup):
	from nhk.api import staff

	duty = _on_duty(cleanup)
	res = staff.end_duty(latitude=12.34, longitude=77.65, accuracy=9.0)

	assert res["on_duty"] is False
	assert staff.duty_status()["on_duty"] is False

	closed = frappe.get_doc("Technician Check In", duty)
	assert closed.closed_at, "end_duty should close the duty check-in"
	assert closed.close_reason == "Day ended"
	assert round(closed.closed_latitude, 2) == 12.34, "going off duty must record where"
	assert round(closed.closed_longitude, 2) == 77.65


def test_end_duty_closes_an_open_visit_checkin(cleanup):
	"""An arrival must not outlive the shift it happened in."""
	from nhk.api import staff

	visit = _visit(cleanup)
	_on_duty(cleanup)
	ci = cleanup.add("Technician Check In", staff.check_in(visit, latitude=12.9, longitude=77.5)["name"])

	res = staff.end_duty(latitude=12.9, longitude=77.5)
	assert res["closed_visit"] == visit

	closed = frappe.get_doc("Technician Check In", ci)
	assert closed.closed_at, "the open visit check-in should have been closed with the day"
	assert closed.close_reason == "Day ended"


def test_end_duty_is_idempotent(cleanup):
	from nhk.api import staff

	_on_duty(cleanup)
	staff.end_duty()
	again = staff.end_duty()
	assert again["already_off_duty"] is True, "a second end_duty should not be an error"


# --------------------------------------------------------------------------
# accepting and rejecting
# --------------------------------------------------------------------------

def test_checkin_requires_accepting_the_job_first(cleanup):
	from nhk.api import staff

	visit = _visit(cleanup, response="Pending")
	_on_duty(cleanup)
	try:
		staff.check_in(visit, latitude=12.9, longitude=77.5)
	except frappe.ValidationError as exc:
		assert "accept" in str(exc).lower(), "the message should say to accept first, got: %s" % exc
		return
	raise AssertionError("check_in should refuse a job the technician has not accepted")


def test_accept_then_check_in(cleanup):
	from nhk.api import staff

	visit = _visit(cleanup, response="Pending")
	_on_duty(cleanup)

	res = staff.accept_job(visit)
	assert res["technician_response"] == "Accepted"
	assert res["already_accepted"] is False

	cleanup.add("Technician Check In", staff.check_in(visit, latitude=12.9, longitude=77.5)["name"])
	assert frappe.db.get_value("Technician Visit Entry", visit, "started_at")


def test_accept_is_idempotent(cleanup):
	from nhk.api import staff

	visit = _visit(cleanup, response="Pending")
	_on_duty(cleanup)

	staff.accept_job(visit)
	assert staff.accept_job(visit)["already_accepted"] is True


def test_reject_needs_a_reason(cleanup):
	from nhk.api import staff

	visit = _visit(cleanup, response="Pending")
	_on_duty(cleanup)
	try:
		staff.reject_job(visit, reason="   ")
	except frappe.ValidationError:
		return
	raise AssertionError("a rejection with no reason gives the office nothing to act on")


def test_reject_hides_the_job_but_leaves_it_assigned(cleanup):
	"""Reassignment is the office's decision -- rejecting must not unassign."""
	from nhk.api import staff

	visit = _visit(cleanup, response="Pending")
	_on_duty(cleanup)

	staff.reject_job(visit, reason="Customer asked to come tomorrow")

	row = frappe.db.get_value(
		"Technician Visit Entry", visit,
		["status", "technician_id", "technician_user_id", "technician_response", "rejection_reason"],
		as_dict=True,
	)
	assert row.status == "Assigned", "rejecting must not move the status"
	assert row.technician_id == PILOT_TECH, "rejecting must not unassign the visit"
	assert row.technician_user_id == PILOT_USER
	assert row.technician_response == "Rejected"
	assert row.rejection_reason

	assert visit not in {j["name"] for j in staff.my_jobs()}, "a rejected job should drop out of the day list"


def test_rejected_job_cannot_be_checked_in(cleanup):
	from nhk.api import staff

	visit = _visit(cleanup, response="Pending")
	_on_duty(cleanup)
	staff.reject_job(visit, reason="Wrong area")

	try:
		staff.check_in(visit, latitude=12.9, longitude=77.5)
	except frappe.ValidationError:
		return
	raise AssertionError("check_in should refuse a rejected job")


def test_cannot_reject_after_arriving(cleanup):
	"""Arriving is a commitment; unwinding one is the office's job."""
	from nhk.api import staff

	visit = _visit(cleanup)
	_on_duty(cleanup)
	cleanup.add("Technician Check In", staff.check_in(visit, latitude=12.9, longitude=77.5)["name"])

	try:
		staff.reject_job(visit, reason="Changed my mind")
	except frappe.ValidationError:
		return
	raise AssertionError("a job already under way should not be rejectable")


# --------------------------------------------------------------------------
# visit check-in
# --------------------------------------------------------------------------

def test_visit_checkin_requires_being_on_duty(cleanup):
	from nhk.api import staff

	visit = _visit(cleanup)
	_as(PILOT_USER)
	try:
		staff.check_in(visit, latitude=12.97, longitude=77.59)
	except frappe.ValidationError:
		return
	raise AssertionError("check_in should require an open duty check-in")


def test_second_visit_checkin_auto_closes_the_first(cleanup):
	from nhk.api import staff

	a, b = _visit(cleanup), _visit(cleanup)
	_on_duty(cleanup)

	first = staff.check_in(a, latitude=12.9, longitude=77.5)
	cleanup.add("Technician Check In", first["name"])
	second = staff.check_in(b, latitude=12.9, longitude=77.5)
	cleanup.add("Technician Check In", second["name"])

	closed = frappe.get_doc("Technician Check In", first["name"])
	assert closed.closed_at, "the first visit check-in should have been auto-closed"
	assert closed.close_reason == "Auto closed", "auto-close must be distinguishable from a real completion"


def test_undo_checkin_works_inside_the_window_and_not_outside(cleanup):
	from nhk.api import staff

	visit = _visit(cleanup)
	_on_duty(cleanup)

	ci = staff.check_in(visit, latitude=12.9, longitude=77.5)
	cleanup.add("Technician Check In", ci["name"])
	staff.undo_check_in(ci["name"])
	assert frappe.db.get_value("Technician Check In", ci["name"], "close_reason") == "Reversed by technician"

	ci2 = staff.check_in(visit, latitude=12.9, longitude=77.5)
	cleanup.add("Technician Check In", ci2["name"])
	old = datetime.now() - timedelta(minutes=30)
	frappe.db.set_value("Technician Check In", ci2["name"], "checked_in_at", old)
	try:
		staff.undo_check_in(ci2["name"])
	except frappe.ValidationError:
		return
	raise AssertionError("undo should be refused after the 15 minute window")


# --------------------------------------------------------------------------
# completion
# --------------------------------------------------------------------------

def test_complete_job_requires_a_visit_checkin(cleanup):
	from nhk.api import staff

	visit = _visit(cleanup)
	_on_duty(cleanup)
	try:
		staff.complete_job(visit, kilometers=12)
	except frappe.ValidationError:
		return
	raise AssertionError("complete_job should require a visit check-in")


def test_complete_job_rejects_a_non_integer_distance(cleanup):
	from nhk.api import staff

	visit = _visit(cleanup)
	_on_duty(cleanup)
	cleanup.add("Technician Check In", staff.check_in(visit, latitude=12.9, longitude=77.5)["name"])
	try:
		staff.complete_job(visit, kilometers=12.4)
	except frappe.ValidationError:
		return
	raise AssertionError("distance must be a whole number so it cannot fall in a slab gap")


def test_complete_job_ignores_a_client_supplied_charge(cleanup):
	from nhk.api import staff
	import inspect

	sig = inspect.signature(staff.complete_job)
	assert "charges" not in sig.parameters, (
		"complete_job must not accept charges -- the slab calculation is the only source"
	)


def test_complete_job_reports_an_office_completion(cleanup):
	from nhk.api import staff

	visit = _visit(cleanup)
	_on_duty(cleanup)
	cleanup.add("Technician Check In", staff.check_in(visit, latitude=12.9, longitude=77.5)["name"])

	frappe.set_user("Administrator")
	frappe.db.set_value("Technician Visit Entry", visit, "status", "Delivered")
	_as(PILOT_USER)

	try:
		staff.complete_job(visit, kilometers=12)
	except frappe.ValidationError as exc:
		assert "office" in str(exc).lower(), "the message should say the office completed it, got: %s" % exc
		return
	raise AssertionError("complete_job should refuse a visit the office already completed")


def test_a_failed_sales_order_leaves_the_visit_untouched(cleanup):
	"""The bug this ordering exists to prevent.

	`nhk.custom_script.change_status` commits. When it ran before the Sales
	Order was advanced, a `make_delivered` failure -- "Item Is Not Reserved",
	which happens routinely -- left the visit `Delivered` in the database while
	the request rolled back and the app was told the job had failed. The office
	saw a completed job; the technician saw an error and a job still open.
	"""
	from nhk.api import staff

	visit = _visit(cleanup)
	_on_duty(cleanup)
	ci = cleanup.add("Technician Check In", staff.check_in(visit, latitude=12.9, longitude=77.5)["name"])

	# Commit the fixture so the rollback below only takes back what complete_job
	# did -- anything it left behind survived a commit of its own, which is the
	# failure being tested.
	frappe.db.commit()

	original = staff._advance_sales_order
	staff._advance_sales_order = lambda *a, **kw: frappe.throw("Item Is Not Reserved")
	try:
		staff.complete_job(visit, kilometers=12)
	except frappe.ValidationError:
		pass
	else:
		raise AssertionError("complete_job should have surfaced the Sales Order failure")
	finally:
		staff._advance_sales_order = original
		# What the request handler does when an endpoint throws.
		frappe.db.rollback()

	status = frappe.db.get_value("Technician Visit Entry", visit, "status")
	assert status == "Assigned", (
		"the visit was left %s after the Sales Order failed -- the app says the job "
		"is open and the desk says it is done" % status
	)
	assert not frappe.db.get_value("Technician Check In", ci, "closed_at"), (
		"the arrival was closed for a completion that did not happen"
	)


def test_delivery_hands_the_sales_order_a_customer_it_can_link(cleanup):
	"""`make_delivered` writes its `customer_name` argument into `Item.customer_n`,
	which is a **Link to Customer** -- so it wants the docname (NHK-CUS-0105), not
	the display name. Customers here are named by series, so passing
	`patient_name` threw `Could not find Customer: <person>` on every delivery.

	Captures the argument instead of letting the call run: whether the real
	`make_delivered` gets far enough to validate the link depends on the order's
	stock state, and the contract being pinned here does not.
	"""
	from nhk.api import staff
	from erpnext.selling.doctype.sales_order import sales_order as so_module

	visit = _visit(cleanup)
	doc = frappe.get_doc("Technician Visit Entry", visit)
	if not doc.sales_order_id:
		raise AssertionError("fixture visit carries no sales order")

	# A display name that is deliberately not any Customer's docname.
	frappe.db.set_value("Technician Visit Entry", visit, "patient_name", "Dr Not A Docname")
	doc.reload()

	captured = {}
	original = so_module.make_delivered
	so_module.make_delivered = lambda docname, customer_name, *a, **kw: captured.update(
		docname=docname, customer_name=customer_name
	)
	try:
		staff._advance_sales_order(doc, "Delivered")
	finally:
		so_module.make_delivered = original
		frappe.db.rollback()

	passed = captured.get("customer_name")
	assert frappe.db.exists("Customer", passed), (
		"make_delivered was handed %r, which is not a Customer docname -- "
		"Item.customer_n is a Link and this throws 'Could not find Customer'" % passed
	)
	assert passed == frappe.db.get_value("Sales Order", doc.sales_order_id, "customer"), (
		"the delivery should name the order's own customer, got %r" % passed
	)


def test_distance_drives_the_slab_charge(cleanup):
	"""The payout must come from the distance, not from a default or a caller."""
	name = _visit(cleanup)
	doc = frappe.get_doc("Technician Visit Entry", name)

	# Order / Delivery / 21-40 km is the 200 rupee slab.
	doc.kilometers = 25
	doc.save(ignore_permissions=True)
	assert doc.charges == 200, "expected the 21-40km delivery slab (200), got %s" % doc.charges

	# Moving into the next band must re-price.
	doc.kilometers = 45
	doc.save(ignore_permissions=True)
	assert doc.charges == 300, "expected the 41-50km delivery slab (300), got %s" % doc.charges


def test_pickup_prices_from_the_pickup_column(cleanup):
	name = _visit(cleanup, type_="Pickup")
	doc = frappe.get_doc("Technician Visit Entry", name)
	doc.kilometers = 25
	doc.save(ignore_permissions=True)
	assert doc.charges == 150, "pickup at 21-40km should be 150, got %s" % doc.charges


def test_endpoints_reject_a_caller_who_is_not_a_technician(cleanup):
	from nhk.api import staff
	from nhk.api.guards import NotATechnician

	frappe.set_user("Administrator")
	try:
		staff.my_jobs()
	except NotATechnician:
		return
	raise AssertionError("my_jobs must not answer for a non-technician")


def test_duty_is_idempotent(cleanup):
	from nhk.api import staff

	_as(PILOT_USER)
	first = staff.start_duty()
	cleanup.add("Technician Check In", first["name"])
	second = staff.start_duty()

	assert second["name"] == first["name"], "a second start_duty should not open a new day"
	assert second["already_on_duty"] is True


if __name__ == "__main__":
	import harness
	raise SystemExit(harness.run(sys.modules[__name__]))
