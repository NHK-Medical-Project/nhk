"""Readying some of a rental's items for Pickup (`nhk.api.pickup.assign_item_pickup`).

Built on a three-item rental with a categorised delivery, as SAL-ORD-2026-12054
was when its per-row pickups came out unpaid and closing one moved all three
items (`.scratch/per-item-pickup/spec.md`).

Run:  cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_per_item_pickup.py
"""

import sys

import frappe
from frappe.utils import now_datetime

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from test_staff_api import OTHER_TECH, PILOT_TECH

OFFICE_USER = "Administrator"
CATEGORY = "Order"

ORDER_FIELDS = ("status", "pickup_date", "pickup_reason", "pickup_remark", "custom_technician_id_pickup",
				"picked_up")
ITEM_FIELDS = ("child_status", "pickup_date", "pickup_reason", "pickup_remark",
			   "technician_id_after_delivered", "submitted_date")


def _order(cleanup):
	"""A real rental of three or more items, all Active, with a delivery visit.

	Its fields are put back afterwards; the visits and comments the test makes
	are deleted (`_forget_what_it_made`).
	"""
	so = frappe.db.sql("""
		select so.name from `tabSales Order` so
		where so.order_type = 'Rental' and so.docstatus = 1
		  and (select count(*) from `tabSales Order Item` i where i.parent = so.name) >= 3
		  and not exists (select 1 from `tabTechnician Visit Entry` v
						  where v.sales_order_id = so.name and v.type = 'Pickup' and v.status = 'Assigned')
		  -- Some snapshot orders cannot be saved at all.
		  and coalesce(so.outstanding_security_deposit_amount, 0) >= 0
		  -- Its devices out on no other rental, or Back To Active is refused
		  -- (`nhk.api.order_undo`).
		  and not exists (select 1 from `tabSales Order Item` mine
						  join `tabSales Order Item` other on other.item_code = mine.item_code
						  join `tabSales Order` o on o.name = other.parent
						  where mine.parent = so.name and o.name != so.name and o.docstatus = 1
							and coalesce(o.master_order_id, o.name) != coalesce(so.master_order_id, so.name)
							and other.child_status in ('Ready for Delivery', 'DISPATCHED', 'Active',
													   'Ready for Pickup', 'Picked Up'))
		order by so.modified desc limit 1""")[0][0]

	for field in ORDER_FIELDS:
		cleanup.restore("Sales Order", so, field)
	rows = frappe.get_all("Sales Order Item", filters={"parent": so}, pluck="name", order_by="idx asc")
	for row in rows:
		for field in ITEM_FIELDS:
			cleanup.restore("Sales Order Item", row, field)
		frappe.db.set_value("Sales Order Item", row, "child_status", "Active", update_modified=False)
	frappe.db.set_value("Sales Order", so, "status", "Active", update_modified=False)

	frappe.set_user(OFFICE_USER)
	delivery = frappe.get_doc({
		"doctype": "Technician Visit Entry",
		"technician_id": PILOT_TECH,
		"sales_order_id": so,
		"type": "Delivery",
		"status": "Delivered",
		"technician_category": CATEGORY,
		"kilometers": 5,
		"technician_response": "Accepted",
	}).insert(ignore_permissions=True)
	cleanup.add("Technician Visit Entry", delivery.name)
	for tech in (PILOT_TECH, OTHER_TECH):
		cleanup.restore_after_delete("Technician Details", tech, "total_amount_settled")

	cleanup.since = now_datetime()
	return so, rows


def _forget_what_it_made(cleanup, so):
	"""Register the pickup visits made on `so` during the test, and their comments."""
	frappe.set_user("Administrator")
	visits = frappe.get_all("Technician Visit Entry",
							filters={"sales_order_id": so, "type": "Pickup", "creation": (">=", cleanup.since)},
							pluck="name")
	known = {name for doctype, name in cleanup._records if doctype == "Technician Visit Entry"}
	for name in visits:
		if name not in known:
			cleanup.add("Technician Visit Entry", name)
	for doctype, names in (("Sales Order", [so]), ("Technician Visit Entry", visits)):
		if names:
			for name in frappe.get_all("Comment",
									   filters={"reference_doctype": doctype, "reference_name": ("in", names),
												"creation": (">=", cleanup.since)}, pluck="name"):
				cleanup.add("Comment", name)


def _assign(cleanup, so, rows, technician=PILOT_TECH, **kwargs):
	from nhk.api import pickup

	frappe.set_user(OFFICE_USER)
	try:
		return pickup.assign_item_pickup(so, rows, technician, **kwargs)
	finally:
		_forget_what_it_made(cleanup, so)


def _release(cleanup, so, row):
	from nhk.api import pickup

	frappe.set_user(OFFICE_USER)
	try:
		return pickup.release_item_pickup(so, row)
	finally:
		_forget_what_it_made(cleanup, so)


def _close(name):
	from nhk.api import visits

	frappe.set_user(OFFICE_USER)
	visits.complete_visit(frappe.get_doc("Technician Visit Entry", name), kilometers=5)


def _refused(call, *args, **kwargs):
	try:
		call(*args, **kwargs)
	except frappe.ValidationError:
		return True
	return False


def _visit(name):
	return frappe.get_doc("Technician Visit Entry", name)


def _rows_of(name):
	return [r.sales_order_item for r in _visit(name).items]


def _status(row):
	return frappe.db.get_value("Sales Order Item", row, "child_status")


def _order_status(so):
	return frappe.db.get_value("Sales Order", so, "status")


# --------------------------------------------------------------------------
# readying items
# --------------------------------------------------------------------------


def test_two_items_on_one_trip_are_one_paid_visit(cleanup):
	so, rows = _order(cleanup)

	result = _assign(cleanup, so, rows[:2])

	assert result["created"]
	visit = _visit(result["name"])
	assert visit.type == "Pickup" and visit.status == "Assigned"
	assert _rows_of(visit.name) == rows[:2]
	assert visit.technician_category == CATEGORY, "the pickup did not take the delivery's category"
	assert visit.charges > 0, "the pickup is unpaid"
	assert visit.item_code and "," in visit.item_code, "the app's tile would not show both items"
	assert [_status(r) for r in rows[:2]] == ["Ready for Pickup"] * 2
	assert _status(rows[2]) == "Active"
	assert _order_status(so) == "Active", "the order is ready for pickup while an item is still unassigned"


def test_another_item_for_the_same_technician_joins_their_visit(cleanup):
	so, rows = _order(cleanup)
	first = _assign(cleanup, so, rows[:1])

	second = _assign(cleanup, so, rows[1:2])

	assert second["name"] == first["name"] and not second["created"]
	assert _rows_of(first["name"]) == rows[:2]


def test_an_item_for_another_technician_is_a_second_visit(cleanup):
	so, rows = _order(cleanup)
	first = _assign(cleanup, so, rows[:1])

	second = _assign(cleanup, so, rows[1:2], technician=OTHER_TECH)

	assert second["name"] != first["name"] and second["created"]
	assert _rows_of(second["name"]) == rows[1:2]


def test_the_last_item_readied_readies_the_order(cleanup):
	so, rows = _order(cleanup)

	_assign(cleanup, so, rows)

	assert _order_status(so) == "Ready for Pickup"
	# Saving a stale copy of the order once wrote its rows back to Active.
	assert [_status(r) for r in rows] == ["Ready for Pickup"] * len(rows)


def test_an_item_already_on_a_pickup_is_refused(cleanup):
	so, rows = _order(cleanup)
	_assign(cleanup, so, rows[:1])

	# Ready for Pickup now, so the row check refuses it before the visit check.
	assert _refused(_assign, cleanup, so, rows[:1], technician=OTHER_TECH)


def test_no_category_and_no_delivery_is_refused(cleanup):
	so, rows = _order(cleanup)
	fixture = frappe.db.get_value("Technician Visit Entry", {"sales_order_id": so, "type": "Delivery"},
								  "name", order_by="creation desc")
	frappe.db.set_value("Technician Visit Entry", fixture, "technician_category", None, update_modified=False)
	if frappe.db.get_value("Technician Visit Entry",
						   {"sales_order_id": so, "type": "Delivery", "technician_category": ("is", "set")}):
		return  # the order's real delivery still carries a category to fall back on

	assert _refused(_assign, cleanup, so, rows[:1])


def test_a_row_not_on_the_order_is_refused(cleanup):
	so, rows = _order(cleanup)

	assert _refused(_assign, cleanup, so, ["not-a-row"])


# --------------------------------------------------------------------------
# Back To Active
# --------------------------------------------------------------------------


def test_releasing_one_of_two_items_keeps_the_visit(cleanup):
	so, rows = _order(cleanup)
	result = _assign(cleanup, so, rows[:2])

	_release(cleanup, so, rows[0])

	assert _status(rows[0]) == "Active"
	visit = _visit(result["name"])
	assert visit.status == "Assigned"
	assert _rows_of(visit.name) == rows[1:2]


def test_releasing_the_last_item_closes_the_visit(cleanup):
	so, rows = _order(cleanup)
	result = _assign(cleanup, so, rows)

	for row in rows:
		_release(cleanup, so, row)

	assert _visit(result["name"]).status == "Closed", "an empty pickup was left open"
	assert _order_status(so) == "Active"


def test_a_row_whose_pickup_is_closed_cannot_be_released(cleanup):
	so, rows = _order(cleanup)
	result = _assign(cleanup, so, rows[:1])
	_close(result["name"])

	assert _refused(_release, cleanup, so, rows[0])


# --------------------------------------------------------------------------
# closing a pickup
# --------------------------------------------------------------------------


def test_closing_a_one_item_pickup_moves_that_item_only(cleanup):
	so, rows = _order(cleanup)
	result = _assign(cleanup, so, rows[:1])

	_close(result["name"])

	assert _status(rows[0]) == "Picked Up"
	assert [_status(r) for r in rows[1:]] == ["Active"] * (len(rows) - 1), "items at home were marked picked up"
	assert _order_status(so) == "Active"


def test_closing_the_last_pickup_picks_up_the_order(cleanup):
	so, rows = _order(cleanup)
	first = _assign(cleanup, so, rows[:1])
	rest = _assign(cleanup, so, rows[1:], technician=OTHER_TECH)

	_close(first["name"])
	assert _order_status(so) != "Picked Up"
	_close(rest["name"])

	assert _order_status(so) == "Picked Up"
	assert frappe.db.get_value("Sales Order", so, "picked_up")


def test_a_row_submitted_to_office_is_not_put_back(cleanup):
	so, rows = _order(cleanup)
	result = _assign(cleanup, so, rows[:2])
	frappe.db.set_value("Sales Order Item", rows[0], "child_status", "Submitted to Office", update_modified=False)

	_close(result["name"])

	assert _status(rows[0]) == "Submitted to Office"
	assert _status(rows[1]) == "Picked Up"


def test_a_visit_from_the_old_row_button_moves_its_own_item(cleanup):
	"""Old per-row visits carry the item on `item_code` alone, as on SAL-ORD-2026-12054."""
	so, rows = _order(cleanup)
	row = frappe.db.get_value("Sales Order Item", rows[1], ["name", "item_code"], as_dict=True)
	if frappe.db.count("Sales Order Item", {"parent": so, "item_code": row.item_code}) != 1:
		return
	frappe.db.set_value("Sales Order Item", row.name, "child_status", "Ready for Pickup", update_modified=False)
	frappe.set_user(OFFICE_USER)
	legacy = frappe.get_doc({
		"doctype": "Technician Visit Entry",
		"technician_id": PILOT_TECH,
		"sales_order_id": so,
		"type": "Pickup",
		"status": "Assigned",
		"item_code": row.item_code,
		"technician_response": "Accepted",
	}).insert(ignore_permissions=True)
	cleanup.add("Technician Visit Entry", legacy.name)

	_close(legacy.name)

	assert _status(row.name) == "Picked Up"
	assert _status(rows[0]) == "Active" and _status(rows[2]) == "Active"


def test_a_whole_order_pickup_still_moves_every_item(cleanup):
	from nhk.api import pickup

	so, rows = _order(cleanup)
	frappe.set_user(OFFICE_USER)
	try:
		result = pickup.assign_pickup_for_order(so, PILOT_TECH)
	finally:
		_forget_what_it_made(cleanup, so)

	_close(result["name"])

	assert [_status(r) for r in rows] == ["Picked Up"] * len(rows)
	assert _order_status(so) == "Picked Up"


# --------------------------------------------------------------------------
# the desk's per-row Picked Up (issue 07)
# --------------------------------------------------------------------------


def _pick_up(cleanup, so, row, kilometers=None):
	from nhk.api import pickup

	frappe.set_user(OFFICE_USER)
	try:
		return pickup.pick_up_item(so, row, kilometers=kilometers)
	finally:
		_forget_what_it_made(cleanup, so)


def test_picked_up_on_a_row_closes_its_visit_with_every_item(cleanup):
	so, rows = _order(cleanup)
	result = _assign(cleanup, so, rows[:2])

	_pick_up(cleanup, so, rows[0], kilometers=12)

	visit = _visit(result["name"])
	assert visit.status == "Picked up", "the pickup was left open, so it would never be paid"
	assert visit.kilometers == 12 and visit.charges > 0
	assert [_status(r) for r in rows[:2]] == ["Picked Up"] * 2, "the trip's other item was left behind"
	assert _status(rows[2]) == "Active"
	assert _order_status(so) == "Active"


def test_picked_up_on_a_row_with_a_pickup_needs_the_distance(cleanup):
	so, rows = _order(cleanup)
	_assign(cleanup, so, rows[:1])

	assert _refused(_pick_up, cleanup, so, rows[0])
	assert _status(rows[0]) == "Ready for Pickup"


def test_picked_up_on_a_row_with_no_pickup_moves_that_row_only(cleanup):
	so, rows = _order(cleanup)
	frappe.db.set_value("Sales Order Item", rows[1], "child_status", "Ready for Pickup", update_modified=False)

	result = _pick_up(cleanup, so, rows[1])

	assert result["pickup_visit"] is None
	assert _status(rows[1]) == "Picked Up"
	assert _status(rows[0]) == "Active" and _status(rows[2]) == "Active"


# --------------------------------------------------------------------------
# the order-level buttons after an item came back (SAL-ORD-2026-11982)
# --------------------------------------------------------------------------


def test_the_orders_buttons_leave_a_collected_item_alone(cleanup):
	"""Item pickup, closed; then the order's Ready for Pickup and Assign Pickup.

	Both used to set every row Ready for Pickup, the collected one too, and the
	whole-order visit they made would have marked every row Picked Up again.
	"""
	from nhk.api import pickup

	so, rows = _order(cleanup)
	first = _assign(cleanup, so, rows[:1])
	_close(first["name"])
	frappe.db.set_value("Sales Order Item", rows[0], "child_status", "Submitted to Office", update_modified=False)

	frappe.set_user(OFFICE_USER)
	pickup.ready_order_for_pickup(so, now_datetime(), "Patient recovered", "rest of the order")
	assert _status(rows[0]) == "Submitted to Office", "Ready for Pickup moved an item already back"
	assert [_status(r) for r in rows[1:]] == ["Ready for Pickup"] * (len(rows) - 1)
	assert _order_status(so) == "Ready for Pickup"

	try:
		rest = pickup.assign_pickup_for_order(so, OTHER_TECH)
	finally:
		_forget_what_it_made(cleanup, so)
	assert _status(rows[0]) == "Submitted to Office", "Assign Pickup moved an item already back"
	assert _rows_of(rest["name"]) == rows[1:], "the order's pickup does not name what it collects"
	assert "Sleep study" not in (frappe.db.get_value("Sales Order", so, "pickup_remark") or "")

	_close(rest["name"])
	assert _status(rows[0]) == "Submitted to Office"
	assert [_status(r) for r in rows[1:]] == ["Picked Up"] * (len(rows) - 1)


if __name__ == "__main__":
	import harness
	raise SystemExit(harness.run(sys.modules[__name__]))
