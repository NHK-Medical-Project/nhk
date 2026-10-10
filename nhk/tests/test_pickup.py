"""Behaviour of a technician assigning a sleep study pickup (`nhk.api.pickup`).

None of the calls here put the technician on duty: assigning a pickup works off
duty, because the delivery ends at night.

Run:  cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_pickup.py
"""

import sys

import frappe
from frappe.utils import add_days, get_datetime, getdate, today

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from test_staff_api import OTHER_TECH, OTHER_USER, PILOT_TECH, PILOT_USER

OFFICE_USER = "Administrator"

ORDER_FIELDS = ("status", "pickup_date", "pickup_reason", "pickup_remark", "custom_technician_id_pickup")
ITEM_FIELDS = ("child_status", "pickup_date", "pickup_reason", "pickup_remark",
			   "technician_id_after_delivered")


def _order(cleanup, status="Active"):
	"""A real rental order with no open pickup, set to `status` for the test and
	put back afterwards."""
	so = frappe.db.sql("""
		select so.name from `tabSales Order` so
		where so.order_type = 'Rental' and so.docstatus = 1
		  and not exists (select 1 from `tabTechnician Visit Entry` v
						  where v.sales_order_id = so.name and v.type = 'Pickup' and v.status = 'Assigned')
		order by so.modified desc limit 1""")[0][0]

	for field in ORDER_FIELDS:
		cleanup.restore("Sales Order", so, field)
	for item in frappe.get_all("Sales Order Item", filters={"parent": so}, pluck="name"):
		for field in ITEM_FIELDS:
			cleanup.restore("Sales Order Item", item, field)

	frappe.db.set_value("Sales Order", so, "status", status, update_modified=False)
	return so


def _delivery(cleanup, so, category="Sleep Study Level 2", status="Delivered",
			  technician=PILOT_TECH, user=PILOT_USER):
	"""A delivery the office gave out to `technician`, already in `status`."""
	frappe.set_user(OFFICE_USER)
	doc = frappe.get_doc({
		"doctype": "Technician Visit Entry",
		"technician_id": technician,
		"sales_order_id": so,
		"type": "Delivery",
		"status": status,
		"technician_category": category,
		"kilometers": 5,
		"technician_response": "Accepted",
	}).insert(ignore_permissions=True)
	cleanup.add("Technician Visit Entry", doc.name)
	for tech in (PILOT_TECH, OTHER_TECH):
		cleanup.restore_after_delete("Technician Details", tech, "total_amount_settled")
	frappe.share.add_docshare("Technician Visit Entry", doc.name, user, read=1, write=1,
							  flags={"ignore_share_permission": True})
	return doc.name


def _forget_what_it_made(cleanup, so):
	"""Register the pickup visits `assign_pickup` and `assign_pickup_for_order`
	wrote, and their comments.

	Every open pickup on `so`: `_order` picks an order with none. Filtering on
	`pickup_arranged_by` missed the ones the office assigns, which leave it blank,
	so each run of `test_assign_pickup_for_order_from_desk` left one behind.
	"""
	frappe.set_user("Administrator")
	visits = frappe.get_all("Technician Visit Entry",
							filters={"sales_order_id": so, "type": "Pickup", "status": "Assigned"}, pluck="name")
	for doctype, names in (("Sales Order", [so]), ("Technician Visit Entry", visits)):
		if names:
			for name in frappe.get_all("Comment",
									   filters={"reference_doctype": doctype, "reference_name": ("in", names),
												"content": ("like", "Pickup assigned%")}, pluck="name"):
				cleanup.add("Comment", name)
	for name in visits:
		cleanup.add("Technician Visit Entry", name)


def _assign(cleanup, so, *args, user=PILOT_USER, **kwargs):
	from nhk.api import staff

	frappe.set_user(user)
	try:
		return staff.assign_pickup(*args, **kwargs)
	finally:
		_forget_what_it_made(cleanup, so)


def _refused(cleanup, so, *args, **kwargs):
	try:
		_assign(cleanup, so, *args, **kwargs)
	except (frappe.ValidationError, frappe.PermissionError):
		return True
	return False


def _visit(name):
	return frappe.db.get_value("Technician Visit Entry", name, "*", as_dict=True)


def _shares(name):
	rows = frappe.get_all("DocShare", filters={"share_doctype": "Technician Visit Entry",
											   "share_name": name}, fields=["user", "write"])
	return {r.user: r.write for r in rows}


# --------------------------------------------------------------------------
# assigning
# --------------------------------------------------------------------------


def test_assigning_to_another_technician_readies_the_order_and_gives_them_the_job(cleanup):
	so = _order(cleanup)
	delivery = _delivery(cleanup, so)

	result = _assign(cleanup, so, delivery, OTHER_TECH)

	assert result["created"]
	pickup = _visit(result["name"])
	assert pickup.type == "Pickup" and pickup.status == "Assigned"
	assert pickup.technician_id == OTHER_TECH
	assert pickup.technician_category == "Sleep Study Level 2", "the pickup lost the study's category"
	assert pickup.technician_response == "Pending", "another technician still has to accept"
	assert pickup.pickup_arranged_by == PILOT_TECH
	assert _shares(pickup.name).get(OTHER_USER) == 1, "the pickup technician cannot see the job"

	order = frappe.db.get_value("Sales Order", so, ["status", "custom_technician_id_pickup"], as_dict=True)
	assert order.status == "Ready for Pickup"
	assert order.custom_technician_id_pickup == OTHER_TECH


def test_the_pickup_defaults_to_tomorrow_morning(cleanup):
	so = _order(cleanup)
	result = _assign(cleanup, so, _delivery(cleanup, so), OTHER_TECH)

	pickup = _visit(result["name"])
	assert pickup.slot == "Morning"
	assert getdate(pickup.scheduled_datetime) == getdate(add_days(today(), 1))


def test_the_office_owns_the_pickup_and_hears_the_answer(cleanup):
	"""`if_owner` would give the arranging technician write on someone else's job,
	and `tell_office` writes to `assigned_by`."""
	so = _order(cleanup)
	result = _assign(cleanup, so, _delivery(cleanup, so), OTHER_TECH)

	pickup = _visit(result["name"])
	assert pickup.owner == OFFICE_USER, "the technician who arranged it owns it"
	assert pickup.assigned_by == OFFICE_USER, "accept / reject would go to the technician, not the office"
	# Not checked through `has_permission`: the pilot technician also holds
	# `NHK Admin`, which writes every visit whoever owns it.
	assert PILOT_USER not in _shares(pickup.name), "the arranging technician was given a share"


def test_taking_your_own_pickup_accepts_it(cleanup):
	so = _order(cleanup)
	result = _assign(cleanup, so, _delivery(cleanup, so), PILOT_TECH)

	pickup = _visit(result["name"])
	assert pickup.technician_id == PILOT_TECH
	assert pickup.technician_response == "Accepted"
	assert pickup.technician_response_at


def test_the_assignment_is_in_the_timelines(cleanup):
	so = _order(cleanup)
	result = _assign(cleanup, so, _delivery(cleanup, so), OTHER_TECH)

	for doctype, name in (("Technician Visit Entry", result["name"]), ("Sales Order", so)):
		assert frappe.db.exists("Comment", {"reference_doctype": doctype, "reference_name": name,
											"content": ("like", "Pickup assigned%")}), \
			"%s %s has no record of who assigned the pickup" % (doctype, name)


# --------------------------------------------------------------------------
# what it refuses
# --------------------------------------------------------------------------


def test_only_a_sleep_study_delivery(cleanup):
	so = _order(cleanup)
	assert _refused(cleanup, so, _delivery(cleanup, so, category="Order"), OTHER_TECH)
	assert frappe.db.get_value("Sales Order", so, "status") == "Active"


def test_only_once_the_delivery_is_done(cleanup):
	so = _order(cleanup)
	assert _refused(cleanup, so, _delivery(cleanup, so, status="Assigned"), OTHER_TECH)


def test_only_the_technician_who_delivered(cleanup):
	so = _order(cleanup)
	delivery = _delivery(cleanup, so, technician=OTHER_TECH, user=OTHER_USER)
	assert _refused(cleanup, so, delivery, PILOT_TECH)


def test_not_once_the_order_has_moved_on(cleanup):
	so = _order(cleanup, status="Picked Up")
	assert _refused(cleanup, so, _delivery(cleanup, so), OTHER_TECH)


def test_not_a_date_in_the_past(cleanup):
	so = _order(cleanup)
	assert _refused(cleanup, so, _delivery(cleanup, so), OTHER_TECH,
					pickup_date=add_days(today(), -1))


def test_not_a_pickup_the_office_assigned(cleanup):
	so = _order(cleanup)
	delivery = _delivery(cleanup, so)
	frappe.set_user(OFFICE_USER)
	office_pickup = frappe.get_doc({
		"doctype": "Technician Visit Entry", "technician_id": OTHER_TECH, "sales_order_id": so,
		"type": "Pickup", "status": "Assigned", "technician_category": "Sleep Study Level 2",
		"kilometers": 5,
	}).insert(ignore_permissions=True)
	cleanup.add("Technician Visit Entry", office_pickup.name)

	assert _refused(cleanup, so, delivery, PILOT_TECH)
	assert _visit(office_pickup.name).technician_id == OTHER_TECH


# --------------------------------------------------------------------------
# changing it
# --------------------------------------------------------------------------


def test_it_can_be_moved_until_the_pickup_technician_accepts(cleanup):
	so = _order(cleanup)
	delivery = _delivery(cleanup, so)
	first = _assign(cleanup, so, delivery, OTHER_TECH)

	second = _assign(cleanup, so, delivery, PILOT_TECH, slot="Evening")

	assert second["name"] == first["name"], "a second pickup was created instead of moving the first"
	pickup = _visit(first["name"])
	assert pickup.technician_id == PILOT_TECH
	assert pickup.slot == "Evening"
	assert pickup.technician_response == "Accepted"
	assert pickup.assigned_by == OFFICE_USER, "the move handed the office's answers to the technician"
	assert _shares(pickup.name).get(OTHER_USER) == 0, "the previous pickup technician kept write"
	assert frappe.db.get_value("Sales Order", so, "custom_technician_id_pickup") == PILOT_TECH


def test_a_pickup_you_took_yourself_can_still_be_given_away(cleanup):
	so = _order(cleanup)
	delivery = _delivery(cleanup, so)
	_assign(cleanup, so, delivery, PILOT_TECH)

	result = _assign(cleanup, so, delivery, OTHER_TECH)
	pickup = _visit(result["name"])
	assert pickup.technician_id == OTHER_TECH
	assert pickup.technician_response == "Pending"


def test_once_accepted_it_is_the_offices_to_change(cleanup):
	from nhk.api import staff

	so = _order(cleanup)
	delivery = _delivery(cleanup, so)
	result = _assign(cleanup, so, delivery, OTHER_TECH)

	frappe.set_user(OTHER_USER)
	staff.accept_job(result["name"])

	assert _refused(cleanup, so, delivery, PILOT_TECH)
	assert _visit(result["name"]).technician_id == OTHER_TECH


# --------------------------------------------------------------------------
# what the app is told
# --------------------------------------------------------------------------


def test_pickup_state_says_when_the_app_may_assign(cleanup):
	from nhk.api import pickup

	so = _order(cleanup)
	delivery = _delivery(cleanup, so)

	frappe.set_user(PILOT_USER)
	before = pickup.pickup_state(_visit(delivery), PILOT_TECH)
	assert before["can_assign"] and not before["pickup_visit"]

	_assign(cleanup, so, delivery, OTHER_TECH)
	frappe.set_user(PILOT_USER)
	after = pickup.pickup_state(_visit(delivery), PILOT_TECH)
	assert after["can_assign"], "it should still be movable while unanswered"
	assert after["technician_id"] == OTHER_TECH and after["arranged_by_me"]


def test_pickup_state_is_none_for_other_visits(cleanup):
	from nhk.api import pickup

	so = _order(cleanup)
	frappe.set_user(PILOT_USER)
	assert pickup.pickup_state(_visit(_delivery(cleanup, so, category="Order")), PILOT_TECH) is None


def test_the_list_of_technicians_starts_with_me(cleanup):
	from nhk.api import staff

	frappe.set_user(PILOT_USER)
	rows = staff.pickup_technicians()
	assert rows[0]["technician_id"] == PILOT_TECH and rows[0]["is_me"]
	assert OTHER_TECH in {r["technician_id"] for r in rows}


def test_ready_for_pickup_unassigned_and_then_assigned(cleanup):
	from nhk.api import pickup, staff

	so = _order(cleanup)
	delivery = _delivery(cleanup, so)

	frappe.set_user(PILOT_USER)
	# 1. Leave to office / ready for pickup without assigning technician
	staff.ready_for_pickup(delivery)
	assert frappe.db.get_value("Sales Order", so, "status") == "Ready for Pickup"
	assert not frappe.db.get_value("Sales Order", so, "custom_technician_id_pickup")

	# 2. State still permits assigning later
	state = pickup.pickup_state(_visit(delivery), PILOT_TECH)
	assert state["can_assign"] and not state["pickup_visit"]

	# 3. Technician assigns it after Ready for Pickup stage
	result = _assign(cleanup, so, delivery, OTHER_TECH)
	pickup_doc = _visit(result["name"])
	assert pickup_doc.technician_id == OTHER_TECH
	assert frappe.db.get_value("Sales Order", so, "custom_technician_id_pickup") == OTHER_TECH


def test_assign_pickup_for_order_from_desk(cleanup):
	from nhk.api import pickup

	so = _order(cleanup, status="Ready for Pickup")
	delivery = _delivery(cleanup, so)
	_forget_what_it_made(cleanup, so)

	frappe.set_user(OFFICE_USER)
	try:
		result = pickup.assign_pickup_for_order(so, OTHER_TECH, slot="Afternoon")
	finally:
		_forget_what_it_made(cleanup, so)
	pickup_doc = _visit(result["name"])

	assert pickup_doc.technician_id == OTHER_TECH
	assert pickup_doc.slot == "Afternoon"
	assert not pickup_doc.pickup_arranged_by, "office assignment should leave pickup_arranged_by blank"
	assert frappe.db.get_value("Sales Order", so, "custom_technician_id_pickup") == OTHER_TECH



# --------------------------------------------------------------------------
# the office's workspace block (`nhk.api.office.sleep_study_pickups`)
# --------------------------------------------------------------------------


def _group_of(so):
	from nhk.api import office

	frappe.set_user(OFFICE_USER)
	row = next((r for r in office.sleep_study_pickups()["rows"] if r["sales_order_id"] == so), None)
	return row and row["group"]


def test_the_block_follows_a_study_from_patient_to_pickup(cleanup):
	from nhk.api import staff

	so = _order(cleanup)
	delivery = _delivery(cleanup, so)
	assert _group_of(so) == "With Patient"

	frappe.set_user(PILOT_USER)
	staff.ready_for_pickup(delivery)
	assert _group_of(so) == "To Assign", "a pickup left to the office is not shown as needing a technician"

	_assign(cleanup, so, delivery, OTHER_TECH)
	assert _group_of(so) == "Assigned"


def test_a_rejected_pickup_goes_back_to_assign(cleanup):
	from nhk.api import staff

	so = _order(cleanup)
	delivery = _delivery(cleanup, so)
	result = _assign(cleanup, so, delivery, OTHER_TECH)

	frappe.set_user(OTHER_USER)
	staff.reject_job(result["name"], "Feeling unwell")
	assert _group_of(so) == "To Assign"


def test_the_block_leaves_out_other_orders(cleanup):
	"""Checked by the delivery, not the order: the order borrowed from the
	snapshot may carry a real sleep study of its own."""
	from nhk.api import office

	so = _order(cleanup)
	delivery = _delivery(cleanup, so, category="Order")
	frappe.set_user(OFFICE_USER)
	shown = {r["delivery_visit"] for r in office.sleep_study_pickups()["rows"]}
	assert delivery not in shown


def test_the_block_and_the_desk_assign_are_the_offices(cleanup):
	"""OTHER_USER holds only `NHK Technician`, which has no `share`."""
	from nhk.api import office, pickup

	so = _order(cleanup)
	_delivery(cleanup, so)
	for call in (office.sleep_study_pickups,
				 lambda: pickup.assign_pickup_for_order(so, OTHER_TECH)):
		# Every call: `_forget_what_it_made` switches back to Administrator.
		frappe.set_user(OTHER_USER)
		try:
			call()
		except frappe.PermissionError:
			continue
		finally:
			_forget_what_it_made(cleanup, so)
		raise AssertionError("a technician got through an office-only call")


if __name__ == "__main__":
	import harness
	raise SystemExit(harness.run(sys.modules[__name__]))

