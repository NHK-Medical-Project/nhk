"""Submitted to Office frees only this order's own devices, and a renewal only
carries devices that are out with its customer (`nhk.api.submit_to_office`,
`nhk.api.order_steps.refuse_renewing_a_device_not_out`).

Run:  cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_submit_to_office.py

The orders are real; each test sets one up as it needs and puts it back.
"""

import json
import sys

import frappe
from frappe.utils import now_datetime

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from test_order_steps import DEVICE_FIELDS, _device_out, _undo_order

from nhk.api.order_steps import DeviceNotOut, DeviceOnAnotherOrder, refuse_renewing_a_device_not_out
from nhk.api.submit_to_office import submit_order_to_office, submit_row_to_office

OVERRIDES = {
	"erpnext.selling.doctype.sales_order.sales_order.make_submitted_to_office":
		"nhk.api.submit_to_office.submit_order_to_office",
	"erpnext.selling.doctype.sales_order.sales_order.update_status_to_submitted_to_office":
		"nhk.api.submit_to_office.submit_row_to_office",
}


def _device(item):
	return frappe.db.get_value("Item", item, DEVICE_FIELDS)


def _shown():
	return " ".join(str(m.get("message")) for m in frappe.get_message_log())


def _picked_up_with(cleanup, device):
	"""A one-row order, Picked Up, whose row carries `device` (out on another order)."""
	so, row, _item = _undo_order(cleanup, "Picked Up", device=device)
	cleanup.restore("Sales Order", so, "submitted_date")
	return so, row


def test_the_desk_reaches_submitted_to_office_through_nhk(cleanup):
	overrides = frappe.get_hooks("override_whitelisted_methods")
	for core, wrapper in OVERRIDES.items():
		assert overrides.get(core) == [wrapper], (core, overrides.get(core))


def test_order_button_refuses_a_device_out_on_another_order(cleanup):
	"""SAL-ORD-2026-10627 freed .0133493 while it was with Krishnamma on 10592."""
	device, holder, _master = _device_out()
	so, _row = _picked_up_with(cleanup, device)
	before = _device(device)

	try:
		submit_order_to_office(so, json.dumps([device]), now_datetime())
	except DeviceOnAnotherOrder:
		pass
	else:
		raise AssertionError("%s freed %s while it is out on %s" % (so, device, holder))
	finally:
		frappe.db.rollback()

	assert _device(device) == before, "%s -> %s" % (before, _device(device))
	assert frappe.db.get_value("Sales Order", so, "status") == "Picked Up"
	assert holder in _shown(), "the refusal does not name %s: %r" % (holder, _shown())


def test_order_button_leaves_the_device_of_a_row_already_back(cleanup):
	"""SAL-ORD-2026-11251 freed 2000205, whose row had come back weeks before
	and which was then out on SAL-ORD-2026-11428. The row closes; the device
	stays where it is."""
	device, _holder, _master = _device_out()
	so, row = _picked_up_with(cleanup, device)
	frappe.db.set_value("Sales Order Item", row, "child_status", "Submitted to Office", update_modified=False)
	frappe.db.commit()
	before = _device(device)

	try:
		submit_order_to_office(so, json.dumps([device]), now_datetime())
		after = (_device(device), frappe.db.get_value("Sales Order", so, "status"))
	finally:
		frappe.db.rollback()

	assert after == (before, "Submitted to Office"), "%s -> %s" % (before, after)


def test_row_button_refuses_a_device_out_on_another_order_and_says_so(cleanup):
	device, holder, _master = _device_out()
	so, row = _picked_up_with(cleanup, device)
	before = _device(device)

	try:
		submit_row_to_office(device, now_datetime(), so, row)
	except DeviceOnAnotherOrder:
		pass
	else:
		raise AssertionError("the row of %s freed %s while it is out on %s" % (so, device, holder))
	finally:
		frappe.db.rollback()

	assert _device(device) == before
	assert holder in _shown(), "the refusal does not name %s: %r" % (holder, _shown())


def test_row_button_refuses_a_row_already_back(cleanup):
	device, _holder, _master = _device_out()
	so, row = _picked_up_with(cleanup, device)
	frappe.db.set_value("Sales Order Item", row, "child_status", "Submitted to Office", update_modified=False)
	frappe.db.commit()

	try:
		submit_row_to_office(device, now_datetime(), so, row)
	except frappe.ValidationError as exc:
		assert "already Submitted to Office" in str(exc), exc
	else:
		raise AssertionError("a row already back was submitted again")
	finally:
		frappe.db.rollback()


def test_order_button_frees_its_own_device(cleanup):
	"""Nothing else in the way: the button works as it did."""
	found = frappe.db.sql(
		"""
		select so.name, soi.name, soi.item_code from `tabSales Order` so
		join `tabSales Order Item` soi on soi.parent = so.name
		join `tabItem` i on i.name = soi.item_code
		where so.docstatus = 1 and so.order_type = 'Rental' and so.status = 'Active'
		  and soi.child_status = 'Active' and i.status = 'Rented Out' and i.custom_sales_order_id = so.name
		  and (select count(*) from `tabSales Order Item` x where x.parent = so.name) = 1
		order by so.creation limit 1
		""",
	)
	assert found, "the snapshot has no Active one-row order with its own device"
	so, row, device = found[0]
	for field in DEVICE_FIELDS:
		cleanup.restore("Item", device, field)
	for field in ("status", "submitted_date"):
		cleanup.restore("Sales Order", so, field)
	for field in ("child_status", "submitted_date"):
		cleanup.restore("Sales Order Item", row, field)

	try:
		submit_order_to_office(so, json.dumps([device]), now_datetime())
		after = (frappe.db.get_value("Item", device, "status"), frappe.db.get_value("Sales Order", so, "status"))
	finally:
		frappe.db.rollback()

	assert after == ("Available", "Submitted to Office"), after


# ---------------------------------------------------------------------------
# a renewal carries only devices that are out with its customer
# ---------------------------------------------------------------------------

def _renewal(customer, item_code):
	doc = frappe.new_doc("Sales Order")
	doc.update({"order_type": "Rental", "previous_order_id": "SAL-ORD-TEST", "customer": customer})
	doc.append("items", {"item_code": item_code})
	return doc


def test_a_renewal_of_a_device_out_with_its_customer_goes_through(cleanup):
	device, _holder, _master = _device_out()
	refuse_renewing_a_device_not_out(_renewal(frappe.db.get_value("Item", device, "customer_n"), device))


def test_a_renewal_of_a_device_out_with_someone_else_is_refused(cleanup):
	device, _holder, _master = _device_out()
	other = frappe.db.get_value("Customer", {"name": ("!=", frappe.db.get_value("Item", device, "customer_n"))}, "name")
	try:
		refuse_renewing_a_device_not_out(_renewal(other, device))
	except DeviceNotOut:
		return
	raise AssertionError("renewed %s for %s, who does not have it" % (device, other))


def test_a_renewal_of_an_available_device_is_refused(cleanup):
	"""SAL-ORD-2026-12155 and SAL-ORD-2026-13200."""
	device = frappe.db.get_value("Item", {"device_type": "Rental", "status": "Available"}, "name")
	customer = frappe.db.get_value("Customer", {}, "name")
	try:
		refuse_renewing_a_device_not_out(_renewal(customer, device))
	except DeviceNotOut as exc:
		assert device in str(exc), exc
		return
	raise AssertionError("renewed %s, which reads Available" % device)


def test_a_new_order_is_left_alone(cleanup):
	device = frappe.db.get_value("Item", {"device_type": "Rental", "status": "Available"}, "name")
	doc = _renewal(frappe.db.get_value("Customer", {}, "name"), device)
	doc.previous_order_id = None
	refuse_renewing_a_device_not_out(doc)


if __name__ == "__main__":
	import harness

	raise SystemExit(harness.run(sys.modules[__name__]))
