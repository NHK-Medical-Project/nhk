"""A technician replaces a device from their job (`nhk.api.replacement`).

The phone follows the desk's Item Replacement: the same rows, the same devices,
the same writes (`.scratch/device-replacement/spec.md`).

Run:  cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_replacement.py
"""

import sys

import frappe

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from test_staff_api import OTHER_TECH, PILOT_TECH, PILOT_USER, _as, _on_duty, _visit

ROW_FIELDS = ("child_status", "item_code", "item_name", "item_group", "replaced_datetime", "old_item_code")
ITEM_FIELDS = ("status", "customer_n", "customer_name", "custom_sales_order_id", "replaced_reason")


def _order(cleanup, child_status):
	"""A real rental with one row put in `child_status`, and a spare Available
	device of that row's product type. Every field touched is put back."""
	found = frappe.db.sql("""
		select so.name so, soi.name row, soi.item_code, ig.product_type1
		from `tabSales Order` so
		join `tabSales Order Item` soi on soi.parent = so.name
		join `tabItem Group` ig on ig.name = soi.item_group
		where so.order_type = 'Rental' and so.docstatus = 1
		  and coalesce(so.outstanding_security_deposit_amount, 0) >= 0
		  and ig.product_type1 is not null and ig.product_type1 != ''
		  and (select count(*) from `tabItem` i where i.status = 'Available' and i.disabled = 0
			   and i.custom_product_type = ig.product_type1) >= 2
		  and (select count(*) from `tabSales Order Item` x where x.parent = so.name) = 1
		order by so.modified desc limit 1""", as_dict=True)[0]

	spares = frappe.get_all("Item", filters={"status": "Available", "disabled": 0,
											 "custom_product_type": found.product_type1},
							pluck="name", order_by="name asc", limit=50)
	from nhk.api.order_steps import device_out_elsewhere
	spares = [s for s in spares if not device_out_elsewhere(s, found.so)][:2]

	cleanup.restore("Sales Order", found.so, "status")
	for field in ROW_FIELDS:
		cleanup.restore("Sales Order Item", found.row, field)
	for item in (found.item_code, *spares):
		for field in ITEM_FIELDS:
			cleanup.restore("Item", item, field)

	frappe.db.set_value("Sales Order Item", found.row, "child_status", child_status, update_modified=False)
	frappe.db.set_value("Sales Order", found.so, "status", child_status, update_modified=False)
	cleanup.since = frappe.utils.now_datetime()
	return found.so, found.row, found.item_code, spares


def _forget(cleanup, so, visit):
	for name in frappe.get_all("Rental Order Replaced Item",
							   filters={"sales_order_id": so, "creation": (">=", cleanup.since)}, pluck="name"):
		cleanup.add("Rental Order Replaced Item", name)
	for doctype, name in (("Sales Order", so), ("Technician Visit Entry", visit)):
		for comment in frappe.get_all("Comment", filters={"reference_doctype": doctype, "reference_name": name,
														   "creation": (">=", cleanup.since)}, pluck="name"):
			cleanup.add("Comment", comment)


def _replace(cleanup, so, visit, row, new_item, old_status="Repair Required", reason=None, **kwargs):
	from nhk.api import staff

	reason = reason or frappe.get_all("Item Replacement Reason", pluck="name", limit=1)[0]
	_as(PILOT_USER)
	try:
		return staff.replace_device(visit, row, new_item, old_status, reason, **kwargs)
	finally:
		frappe.set_user("Administrator")
		_forget(cleanup, so, visit)


def _refused(call, *args, **kwargs):
	try:
		call(*args, **kwargs)
	except frappe.ValidationError:
		return True
	return False


def _row(row):
	return frappe.db.get_value("Sales Order Item", row, ROW_FIELDS, as_dict=True)


def _item(item):
	return frappe.db.get_value("Item", item, ITEM_FIELDS, as_dict=True)


# --------------------------------------------------------------------------
# what the job offers
# --------------------------------------------------------------------------


def test_a_dispatched_delivery_offers_its_row(cleanup):
	from nhk.api import staff

	so, row, _old, _spares = _order(cleanup, "DISPATCHED")
	visit = _visit(cleanup, sales_order=so)
	_on_duty(cleanup)

	offered = staff.job(visit)["replacement"]

	assert [r.name for r in offered["rows"]] == [row]
	assert "Repair Required" in offered["old_item_statuses"]
	assert offered["reasons"], "no Item Replacement Reason to choose"


def test_an_active_row_offers_nothing(cleanup):
	"""The desk offers no Item Replacement on an Active row."""
	from nhk.api import staff

	so, _row_name, _old, _spares = _order(cleanup, "Active")
	visit = _visit(cleanup, sales_order=so)
	_on_duty(cleanup)

	assert staff.job(visit)["replacement"] is None


def test_the_device_list_is_every_available_device(cleanup):
	from nhk.api import staff

	so, row, old, spares = _order(cleanup, "DISPATCHED")
	visit = _visit(cleanup, sales_order=so)
	_on_duty(cleanup)

	found = staff.replaceable_devices(visit, row, txt=spares[0])

	assert [d.name for d in found] == [spares[0]]
	assert old not in [d.name for d in staff.replaceable_devices(visit, row)]


# --------------------------------------------------------------------------
# replacing
# --------------------------------------------------------------------------


def test_a_delivery_replaces_before_handing_over(cleanup):
	so, row, old, spares = _order(cleanup, "DISPATCHED")
	visit = _visit(cleanup, sales_order=so)
	_on_duty(cleanup)

	result = _replace(cleanup, so, visit, row, spares[0])

	assert result["child_status"] == "DISPATCHED"
	after = _row(row)
	assert after.item_code == spares[0] and after.old_item_code == old
	assert after.child_status == "DISPATCHED"
	assert _item(spares[0]).status == "Reserved"
	gone = _item(old)
	assert gone.status == "Repair Required" and not gone.custom_sales_order_id
	assert frappe.db.exists("Rental Order Replaced Item",
							{"sales_order_id": so, "old_item": old, "new_item": spares[0]})
	assert frappe.db.get_value("Sales Order", so, "status") == "DISPATCHED"
	assert frappe.db.exists("Comment", {"reference_doctype": "Sales Order", "reference_name": so,
										 "creation": (">=", cleanup.since)})


def test_a_pickup_replaces_what_it_collected_and_the_order_runs_on(cleanup):
	so, row, old, spares = _order(cleanup, "Picked Up")
	visit = _visit(cleanup, sales_order=so, type_="Pickup", status="Picked up")
	_on_duty(cleanup)

	_replace(cleanup, so, visit, row, spares[0], old_status="Available")

	after = _row(row)
	assert after.child_status == "Active" and after.item_code == spares[0]
	new = _item(spares[0])
	assert new.status == "Rented Out" and new.custom_sales_order_id == so
	assert _item(old).status == "Available"
	assert frappe.db.get_value("Sales Order", so, "status") == "Active"


def test_refusals_write_nothing(cleanup):
	from nhk.api import staff

	so, row, old, spares = _order(cleanup, "DISPATCHED")
	visit = _visit(cleanup, sales_order=so)
	_on_duty(cleanup)
	before = _row(row)

	assert _refused(_replace, cleanup, so, visit, row, old), "replaced a device with itself"
	assert _refused(_replace, cleanup, so, visit, row, spares[0], old_status="Lost")
	assert _refused(_replace, cleanup, so, visit, row, spares[0], reason="not a reason")
	frappe.db.set_value("Item", spares[1], "status", "Rented Out", update_modified=False)
	assert _refused(_replace, cleanup, so, visit, row, spares[1]), "replaced with a device not Available"

	frappe.db.set_value("Sales Order Item", row, "child_status", "Active", update_modified=False)
	assert _refused(_replace, cleanup, so, visit, row, spares[0]), "replaced an Active row"

	frappe.db.set_value("Sales Order Item", row, "child_status", "DISPATCHED", update_modified=False)
	pickup = _visit(cleanup, sales_order=so, type_="Pickup")
	assert _refused(_replace, cleanup, so, pickup, row, spares[0]), "a pickup replaced a DISPATCHED row"

	assert _row(row) == before
	assert not frappe.db.exists("Rental Order Replaced Item",
								{"sales_order_id": so, "creation": (">=", cleanup.since)})


def test_another_technicians_job_is_refused(cleanup):
	so, row, _old, spares = _order(cleanup, "DISPATCHED")
	visit = _visit(cleanup, technician=OTHER_TECH, user="Administrator", sales_order=so)
	_on_duty(cleanup)

	assert _refused(_replace, cleanup, so, visit, row, spares[0])
	assert _row(row).item_code != spares[0]


def test_an_unanswered_delivery_is_refused(cleanup):
	so, row, _old, spares = _order(cleanup, "DISPATCHED")
	visit = _visit(cleanup, sales_order=so, response="Pending")
	_on_duty(cleanup)

	assert _refused(_replace, cleanup, so, visit, row, spares[0])


def test_a_device_of_another_item_group_may_replace(cleanup):
	so, row, _old, _spares = _order(cleanup, "DISPATCHED")
	group = frappe.db.get_value("Sales Order Item", row, "item_group")
	other = frappe.db.get_value("Item", {"status": "Available", "disabled": 0, "item_group": ("!=", group)}, "name")
	for field in ITEM_FIELDS:
		cleanup.restore("Item", other, field)
	visit = _visit(cleanup, sales_order=so)
	_on_duty(cleanup)

	_replace(cleanup, so, visit, row, other)

	after = _row(row)
	assert after.item_code == other
	assert after.item_group == frappe.db.get_value("Item", other, "item_group")


if __name__ == "__main__":
	import harness
	raise SystemExit(harness.run(sys.modules[__name__]))
