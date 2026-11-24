"""The office schedules a device replacement on a technician (`nhk.api.replacement`).

A device at the patient's home (row Active) is swapped on a `Replacement` visit:
the new device is Reserved when the office assigns it, and the swap happens when
the visit is completed (`.scratch/device-replacement-visit/spec.md`).

Run:  cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_replacement_visit.py
"""

import sys

import frappe

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from test_replacement import ITEM_FIELDS, _forget, _item, _order, _refused, _row
from test_staff_api import PILOT_TECH

CATEGORY = "Order"


def _reason():
	return frappe.get_all("Item Replacement Reason", pluck="name", limit=1)[0]


def _schedule(cleanup, so, row, new_item, **kwargs):
	from nhk.api import replacement

	kwargs.setdefault("technician_id", PILOT_TECH)
	kwargs.setdefault("technician_category", CATEGORY)
	kwargs.setdefault("reason", _reason())
	before = set(frappe.get_all("Technician Visit Entry", filters={"sales_order_id": so}, pluck="name"))
	try:
		return replacement.schedule_replacement(so, row, new_item, **kwargs)
	finally:
		for name in set(frappe.get_all("Technician Visit Entry", filters={"sales_order_id": so}, pluck="name")) - before:
			cleanup.add("Technician Visit Entry", name)
			_forget(cleanup, so, name)
		cleanup.restore_after_delete("Technician Details", PILOT_TECH, "total_amount_settled")


def _complete(cleanup, so, visit_name):
	from nhk.api.visits import complete_visit

	try:
		complete_visit(frappe.get_doc("Technician Visit Entry", visit_name), 5)
	finally:
		_forget(cleanup, so, visit_name)


# --------------------------------------------------------------------------
# scheduling
# --------------------------------------------------------------------------


def test_scheduling_reserves_the_new_device_and_leaves_the_row(cleanup):
	so, row, old, spares = _order(cleanup, "Active")

	result = _schedule(cleanup, so, row, spares[0], remark="Bring the charger back")

	visit = frappe.get_doc("Technician Visit Entry", result["name"])
	assert visit.type == "Replacement" and visit.status == "Assigned"
	assert visit.technician_id == PILOT_TECH and visit.technician_category == CATEGORY
	assert [r.sales_order_item for r in visit.items] == [row]
	assert visit.items[0].item_code == old
	assert visit.new_item == spares[0] and visit.old_item_status == "Available"
	assert visit.order_notes == "Bring the charger back"

	new = _item(spares[0])
	assert new.status == "Reserved" and new.custom_sales_order_id == so
	after = _row(row)
	assert after.item_code == old and after.child_status == "Active"


def test_scheduling_refusals_write_nothing(cleanup):
	so, row, old, spares = _order(cleanup, "Active")
	before = _row(row)

	assert _refused(_schedule, cleanup, so, row, old), "replaced a device with itself"
	assert _refused(_schedule, cleanup, so, row, spares[0], old_item_status="Lost")
	assert _refused(_schedule, cleanup, so, row, spares[0], reason="not a reason")
	frappe.db.set_value("Item", spares[1], "status", "Rented Out", update_modified=False)
	assert _refused(_schedule, cleanup, so, row, spares[1]), "scheduled a device not Available"

	frappe.db.set_value("Sales Order Item", row, "child_status", "Ready for Pickup", update_modified=False)
	assert _refused(_schedule, cleanup, so, row, spares[0]), "scheduled a row not Active"
	frappe.db.set_value("Sales Order Item", row, "child_status", "Active", update_modified=False)

	assert _row(row) == before
	assert _item(spares[0]).status == "Available"
	assert not frappe.db.exists("Technician Visit Entry", {"sales_order_id": so, "type": "Replacement",
															"creation": (">=", cleanup.since)})


def test_a_row_takes_one_open_replacement(cleanup):
	so, row, _old, spares = _order(cleanup, "Active")
	_schedule(cleanup, so, row, spares[0])

	assert _refused(_schedule, cleanup, so, row, spares[1]), "two open replacements on one row"


def test_a_row_being_replaced_cannot_be_given_to_a_pickup(cleanup):
	from nhk.api import pickup

	so, row, _old, spares = _order(cleanup, "Active")
	_schedule(cleanup, so, row, spares[0])

	assert _refused(pickup.assign_item_pickup, so, [row], PILOT_TECH, technician_category=CATEGORY,
					pickup_reason=None, pickup_remark="test")
	assert _row(row).child_status == "Active"


def test_the_device_list_is_every_group(cleanup):
	from nhk.api import replacement

	so, row, _old, _spares = _order(cleanup, "Active")
	group = frappe.db.get_value("Sales Order Item", row, "item_group")
	other = frappe.db.get_value("Item", {"status": "Available", "disabled": 0, "item_group": ("!=", group)}, "name")

	assert [d.name for d in replacement.available_devices(so, txt=other)][:1] == [other]


# --------------------------------------------------------------------------
# completing
# --------------------------------------------------------------------------


def test_completing_swaps_the_device_and_returns_the_old_to_stock(cleanup):
	so, row, old, spares = _order(cleanup, "Active")
	status_before = frappe.db.get_value("Sales Order", so, "status")
	name = _schedule(cleanup, so, row, spares[0])["name"]

	_complete(cleanup, so, name)

	visit = frappe.get_doc("Technician Visit Entry", name)
	assert visit.status == "Delivered" and visit.completed_at
	after = _row(row)
	assert after.item_code == spares[0] and after.old_item_code == old and after.child_status == "Active"
	assert after.item_group == frappe.db.get_value("Item", spares[0], "item_group")
	new = _item(spares[0])
	assert new.status == "Rented Out" and new.custom_sales_order_id == so
	gone = _item(old)
	assert gone.status == "Available" and not gone.custom_sales_order_id and not gone.customer_n
	assert frappe.db.exists("Rental Order Replaced Item",
							{"sales_order_id": so, "old_item": old, "new_item": spares[0]})
	assert frappe.db.get_value("Sales Order", so, "status") == status_before


def test_the_old_device_takes_the_status_the_office_chose(cleanup):
	so, row, old, spares = _order(cleanup, "Active")
	name = _schedule(cleanup, so, row, spares[0], old_item_status="Repair Required")["name"]

	_complete(cleanup, so, name)

	assert _item(old).status == "Repair Required"


def test_completing_after_the_row_moved_on_is_refused(cleanup):
	so, row, old, spares = _order(cleanup, "Active")
	name = _schedule(cleanup, so, row, spares[0])["name"]
	frappe.db.set_value("Sales Order Item", row, "child_status", "Picked Up", update_modified=False)

	# A real request rolls the closed visit back with the refusal.
	assert _refused(_complete, cleanup, so, name)

	assert _row(row).item_code == old


def test_a_replacement_pays_delivery_plus_pickup(cleanup):
	so, row, _old, spares = _order(cleanup, "Active")
	name = _schedule(cleanup, so, row, spares[0])["name"]

	_complete(cleanup, so, name)

	slab = next(r for r in frappe.get_single("Admin Settings").technician_charges_table
				if r.category == CATEGORY and r.from_distance <= 5 <= r.to_distance)
	assert frappe.db.get_value("Technician Visit Entry", name, "charges") == slab.delivery + slab.pickup


def test_an_item_replacement_extra_is_refused_on_a_replacement(cleanup):
	so, row, _old, spares = _order(cleanup, "Active")
	name = _schedule(cleanup, so, row, spares[0])["name"]
	visit = frappe.get_doc("Technician Visit Entry", name)
	visit.extra_payment = 100
	visit.extra_payment_reason = "Item Replacement"

	assert _refused(visit.save, ignore_permissions=True), "paid the replacement twice"
	visit = frappe.get_doc("Technician Visit Entry", name)
	visit.extra_payment = 100
	visit.extra_payment_reason = "Waiting"
	visit.save(ignore_permissions=True)


# --------------------------------------------------------------------------
# cancelling
# --------------------------------------------------------------------------


def test_cancelling_releases_the_device(cleanup):
	from nhk.api import replacement

	so, row, old, spares = _order(cleanup, "Active")
	name = _schedule(cleanup, so, row, spares[0])["name"]

	replacement.cancel_replacement(name, note="Patient fixed it")
	_forget(cleanup, so, name)

	assert frappe.db.get_value("Technician Visit Entry", name, "status") == "Closed"
	released = _item(spares[0])
	assert released.status == "Available" and not released.custom_sales_order_id
	assert _row(row).item_code == old
	# And the row may be scheduled again.
	_schedule(cleanup, so, row, spares[0])


if __name__ == "__main__":
	import harness
	raise SystemExit(harness.run(sys.modules[__name__]))
