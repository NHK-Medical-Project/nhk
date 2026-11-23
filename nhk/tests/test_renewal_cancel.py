"""A cancelled renewal hands its devices back from its own rows, and a device is
never left linked to a cancelled order (`nhk.api.renewal_cancel`).

Run:  cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_renewal_cancel.py

The orders and devices are real; each test snapshots what it changes and puts
it back. The hand-back is called directly rather than through a real cancel,
which cannot be undone.
"""

import sys

import frappe
from frappe.utils import now_datetime

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from nhk.api.order_steps import DEVICE_OUT
from nhk.api.renewal_cancel import (
	hand_back_to_previous_order,
	release_devices_left_on_cancelled_order,
	replaced_from,
	stuck_devices,
)

DEVICE_FIELDS = ("status", "customer_n", "customer_name", "custom_sales_order_id")
ROW_FIELDS = ("child_status", "item_code", "item_name", "item_group", "old_item_code", "replaced_datetime")


def _renewal():
	"""A one-device renewal that is Active, its previous order RENEWED, the same
	device on both and linked to the renewal: (renewal, previous, device)."""
	return frappe.db.sql(
		"""
		select r.name, p.name, ri.item_code
		from `tabSales Order` r
		join `tabSales Order` p on p.name = r.previous_order_id
		join `tabSales Order Item` ri on ri.parent = r.name
		join `tabSales Order Item` pi on pi.parent = p.name and pi.item_code = ri.item_code
		join `tabItem` i on i.name = ri.item_code
		where r.docstatus = 1 and r.order_type = 'Rental' and r.status = 'Active' and ri.child_status = 'Active'
		  and p.docstatus = 1 and p.status = 'RENEWED' and r.master_order_id = p.master_order_id
		  and i.status = 'Rented Out' and i.custom_sales_order_id = r.name
		  and (select count(*) from `tabSales Order Item` x where x.parent = r.name) = 1
		  and (select count(*) from `tabSales Order Item` x where x.parent = p.name) = 1
		  and not exists (select 1 from `tabSales Order` n where n.previous_order_id = r.name and n.docstatus = 1)
		order by r.creation limit 1
		""",
	)[0]


def _spare(*not_these):
	"""An Available rental device that no open order has out."""
	return frappe.db.sql(
		"""
		select i.name from `tabItem` i
		where i.device_type = 'Rental' and i.status = 'Available' and i.disabled = 0 and i.name not in %s
		  and not exists (
			select 1 from `tabSales Order Item` soi join `tabSales Order` so on so.name = soi.parent
			where soi.item_code = i.name and so.docstatus = 1 and soi.child_status in %s)
		order by i.creation limit 1
		""",
		(not_these or ("",), DEVICE_OUT),
	)[0][0]


def _snapshot(cleanup, orders=(), devices=()):
	for so in orders:
		cleanup.restore("Sales Order", so, "status")
		for row in frappe.get_all("Sales Order Item", filters={"parent": so}, pluck="name"):
			for field in ROW_FIELDS:
				cleanup.restore("Sales Order Item", row, field)
	for device in devices:
		for field in DEVICE_FIELDS:
			cleanup.restore("Item", device, field)
	# Saves write Version and Comment rows; `_drop_trail` takes them away again.
	return now_datetime()


def _drop_trail(cleanup, since, names):
	for doctype in ("Version", "Comment"):
		field = "docname" if doctype == "Version" else "reference_name"
		for name in frappe.get_all(doctype, filters={field: ("in", list(names)), "creation": (">=", since)},
								   pluck="name"):
			cleanup.add(doctype, name)


def _row(so):
	return frappe.db.get_value("Sales Order Item", {"parent": so}, ROW_FIELDS + ("name",), as_dict=True)


def _device(code):
	return frappe.db.get_value("Item", code, DEVICE_FIELDS, as_dict=True)


def test_a_renewal_with_the_same_device_hands_it_back(cleanup):
	"""SAL-ORD-2026-13090: the device goes back to the order the renewal renewed."""
	renewal, prev, device = _renewal()
	since = _snapshot(cleanup, (renewal, prev), (device,))
	try:
		hand_back_to_previous_order(frappe.get_doc("Sales Order", renewal))
		assert frappe.db.get_value("Sales Order", prev, "status") == "Active"
		row = _row(prev)
		assert (row.item_code, row.child_status) == (device, "Active"), row
		got = _device(device)
		assert (got.status, got.custom_sales_order_id) == ("Rented Out", prev), got
	finally:
		_drop_trail(cleanup, since, (renewal, prev, device))


def test_a_device_swapped_in_on_the_renewal_moves_to_the_previous_order(cleanup):
	"""SAL-ORD-2026-06921: the monitor that replaced 20112100298 was left on the
	cancelled renewal, and 20112100298, by then with another patient, was
	linked back to the previous order."""
	renewal, prev, old = _renewal()
	new = _spare(old)
	elsewhere = frappe.db.get_value(
		"Sales Order", {"docstatus": 1, "order_type": "Rental", "name": ("not in", (renewal, prev))}, "name")
	since = _snapshot(cleanup, (renewal, prev), (old, new))
	master = frappe.db.get_value("Sales Order", renewal, "master_order_id")
	when = now_datetime()

	# What Item Replacement writes on the renewal, then the old device going
	# out to someone else.
	cleanup.add("Rental Order Replaced Item", frappe.get_doc({
		"doctype": "Rental Order Replaced Item", "master_order_id": master, "sales_order_id": renewal,
		"replaced_datetime": when, "old_item": old, "new_item": new, "reason": None,
	}).insert(ignore_permissions=True).name)
	row = _row(renewal)
	frappe.db.set_value("Sales Order Item", row.name, {
		"item_code": new, "item_name": frappe.db.get_value("Item", new, "item_name"),
		"old_item_code": old, "replaced_datetime": when})
	customer = frappe.db.get_value("Sales Order", renewal, "customer")
	frappe.db.set_value("Item", new, {"status": "Rented Out", "customer_n": customer, "custom_sales_order_id": renewal})
	frappe.db.set_value("Item", old, {"status": "Rented Out", "customer_n": "", "custom_sales_order_id": elsewhere})
	old_before = _device(old)

	try:
		hand_back_to_previous_order(frappe.get_doc("Sales Order", renewal))
		got = _row(prev)
		assert (got.item_code, got.old_item_code, got.child_status) == (new, old, "Active"), got
		dev = _device(new)
		assert (dev.status, dev.custom_sales_order_id) == ("Rented Out", prev), dev
		assert _device(old) == old_before, "the swapped-out device was touched: %s" % _device(old)
	finally:
		_drop_trail(cleanup, since, (renewal, prev, old, new))


def test_a_device_swapped_out_and_back_is_followed_to_where_it_came_in(cleanup):
	"""SAL-ORD-2026-08388 swapped the monitor out on 07-30 and back in on 08-02."""
	if not frappe.db.exists("Item", "Mindray Monitor - 1702"):
		return
	assert replaced_from("SAL-ORD-2026-05506", "Mindray Monitor - 1702", None, {"20112100298"}) == "20112100298"
	assert replaced_from("SAL-ORD-2026-05506", "Mindray Monitor - 1702", None, {"nothing"}) is None


def test_a_device_left_on_a_cancelled_order_is_released(cleanup):
	cancelled = frappe.db.get_value("Sales Order", {"docstatus": 2, "order_type": "Rental"}, "name")
	device = _spare()
	since = _snapshot(cleanup, (), (device,))
	frappe.db.set_value("Item", device, {"status": "Rented Out", "customer_n": "x", "custom_sales_order_id": cancelled})
	try:
		release_devices_left_on_cancelled_order(frappe._dict(
			name=cancelled, order_type="Rental", items=[frappe._dict(item_code=device)]))
		got = _device(device)
		assert (got.status, got.customer_n, got.custom_sales_order_id) == ("Available", "", ""), got
	finally:
		_drop_trail(cleanup, since, (device,))


def test_a_device_out_on_another_open_order_is_not_released(cleanup):
	renewal, _prev, device = _renewal()
	cancelled = frappe.db.get_value("Sales Order", {"docstatus": 2, "order_type": "Rental"}, "name")
	since = _snapshot(cleanup, (), (device,))
	frappe.db.set_value("Item", device, "custom_sales_order_id", cancelled)
	try:
		release_devices_left_on_cancelled_order(frappe._dict(
			name=cancelled, order_type="Rental", items=[frappe._dict(item_code=device)]))
		got = _device(device)
		assert (got.status, got.custom_sales_order_id) == ("Rented Out", cancelled), got
		shown = " ".join(str(m.get("message")) for m in frappe.get_message_log())
		assert renewal in shown, shown
	finally:
		_drop_trail(cleanup, since, (device,))


def test_the_repair_report_lists_devices_on_cancelled_orders(cleanup):
	rows = stuck_devices()
	for r in rows:
		assert frappe.db.get_value("Sales Order", r.sales_order, "docstatus") == 2, r


def test_sales_order_uses_the_nhk_class(cleanup):
	from nhk.overrides.sales_order import NHKSalesOrder

	so = frappe.db.get_value("Sales Order", {}, "name")
	assert isinstance(frappe.get_doc("Sales Order", so), NHKSalesOrder)


if __name__ == "__main__":
	import harness

	raise SystemExit(harness.run(sys.modules[__name__]))
