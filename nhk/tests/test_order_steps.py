"""A rental order's Ready for Delivery and DISPATCHED steps are refused once the
order has moved past the status they are taken from, and a device cannot be put
on one order while another still has it out (`nhk.api.order_steps`).

Run:  cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_order_steps.py

The orders are real; each test sets one to the status it needs and puts it back.
"""

import sys

import frappe

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from test_staff_api import PILOT_TECH

from nhk.api.order_steps import (
	DeviceOnAnotherOrder,
	OrderMovedOn,
	refuse_out_of_order_step,
	refuse_taking_a_device_from_an_open_order,
)

ORDER_FIELDS = ("status", "dispatch_date", "custom_technician_id_before_delivered")
ITEM_FIELDS = ("child_status", "dispatch_date", "technician_id_before_deliverd")


def _order(cleanup, status):
	"""A real rental order, set to `status` for the test and put back afterwards.

	The oldest one, so it is never the order someone is clicking through on the
	desk right now.
	"""
	so = frappe.db.get_value("Sales Order", {"order_type": "Rental", "docstatus": 1}, "name",
							 order_by="creation asc")
	for field in ORDER_FIELDS:
		cleanup.restore("Sales Order", so, field)
	for item in frappe.get_all("Sales Order Item", filters={"parent": so}, pluck="name"):
		for field in ITEM_FIELDS:
			cleanup.restore("Sales Order Item", item, field)
		frappe.db.set_value("Sales Order Item", item, "child_status", status, update_modified=False)
	frappe.db.set_value("Sales Order", so, "status", status, update_modified=False)
	# `make_ready_for_delivery` opens its own transaction and rolls it back on
	# failure; the fixture must already be in place when it does.
	frappe.db.commit()
	return so


def _state(so):
	return (
		frappe.db.get_value("Sales Order", so, "status"),
		sorted(frappe.get_all("Sales Order Item", filters={"parent": so}, pluck="child_status")),
		frappe.db.count("Technician Visit Entry", {"sales_order_id": so}),
	)


def _refused(cleanup, fn, so, *args):
	"""Run a step that must be refused. If it goes through anyway, the visit it
	made is deleted with the test's other records."""
	visits = set(frappe.get_all("Technician Visit Entry", filters={"sales_order_id": so}, pluck="name"))
	try:
		fn(so, *args)
	except frappe.ValidationError as exc:
		# The fork logs the text as an Error Log title; too long, and the
		# logging fails instead of the step.
		assert not isinstance(exc, frappe.CharacterLengthExceededError), exc
		return exc
	finally:
		frappe.db.rollback()
		for visit in frappe.get_all("Technician Visit Entry", filters={"sales_order_id": so}, pluck="name"):
			if visit not in visits:
				technician = frappe.db.get_value("Technician Visit Entry", visit, "technician_id")
				cleanup.restore_after_delete("Technician Details", technician, "total_amount_settled")
				cleanup.add("Technician Visit Entry", visit)
	raise AssertionError("%s went through" % fn.__name__)


def _check(status, before):
	"""The guard alone, on an order moving from `before` to `status`."""
	doc = frappe.new_doc("Sales Order")
	doc.name, doc.status = "SAL-ORD-TEST", status
	doc._doc_before_save = frappe._dict(status=before)
	refuse_out_of_order_step(doc)


def test_ready_for_delivery_on_an_active_order_is_refused(cleanup):
	"""SAL-ORD-2026-11683: the technician prompt was answered after the order was
	delivered. It must leave the order Active and make no second visit."""
	from erpnext.selling.doctype.sales_order.sales_order import make_ready_for_delivery

	so = _order(cleanup, "Active")
	before = _state(so)

	exc = _refused(cleanup, make_ready_for_delivery, so, "Test", "9000000000", PILOT_TECH, "Order")

	assert "already Active" in str(exc), exc
	assert _state(so) == before, "%s -> %s" % (before, _state(so))


def test_ready_for_delivery_after_submitted_to_office_is_refused(cleanup):
	from erpnext.selling.doctype.sales_order.sales_order import make_ready_for_delivery

	so = _order(cleanup, "Submitted to Office")
	before = _state(so)

	exc = _refused(cleanup, make_ready_for_delivery, so, "Test", "9000000000", PILOT_TECH, "Order")

	assert "already Submitted to Office" in str(exc), exc
	assert _state(so) == before, "%s -> %s" % (before, _state(so))


def test_dispatch_on_an_active_order_is_refused(cleanup):
	"""`make_dispatch` replaces the reason with a generic message; the order still
	must not move."""
	from erpnext.selling.doctype.sales_order.sales_order import make_dispatch

	so = _order(cleanup, "Active")
	before = _state(so)

	_refused(cleanup, make_dispatch, so, frappe.utils.today())

	assert _state(so) == before, "%s -> %s" % (before, _state(so))


def test_each_step_from_the_status_before_it_goes_through(cleanup):
	_check("Ready for Delivery", "Approved")
	_check("DISPATCHED", "Ready for Delivery")


def test_each_step_from_anywhere_else_is_refused(cleanup):
	for status, before in (
		("Ready for Delivery", "Active"),
		("Ready for Delivery", "DISPATCHED"),
		("Ready for Delivery", "Submitted to Office"),
		("DISPATCHED", "Active"),
		("DISPATCHED", "Approved"),
	):
		try:
			_check(status, before)
		except OrderMovedOn:
			continue
		raise AssertionError("%s -> %s went through" % (before, status))


def test_no_pickup_on_a_renewed_order(cleanup):
	"""SAL-ORD-2026-10665: a pickup visit left open on the renewed order was
	closed after the device came back on the renewal."""
	from erpnext.selling.doctype.sales_order.sales_order import make_pickedup

	so = _order(cleanup, "RENEWED")
	before = _state(so)

	_refused(cleanup, make_pickedup, so, frappe.utils.now())

	assert _state(so) == before, "%s -> %s" % (before, _state(so))
	for status, before_status in (("Picked Up", "RENEWED"), ("Ready for Pickup", "RENEWED"),
								  ("Ready for Pickup", "Submitted to Office"), ("Picked Up", "Cancelled")):
		try:
			_check(status, before_status)
		except OrderMovedOn:
			continue
		raise AssertionError("%s -> %s went through" % (before_status, status))


def test_the_pickup_steps_still_go_through(cleanup):
	"""The normal pickup, a per-item pickup that finishes from Active, the
	pickup undo buttons, and a part-returned order."""
	for status, before in (
		("Ready for Pickup", "Active"),
		("Picked Up", "Ready for Pickup"),
		("Picked Up", "Active"),
		("Picked Up", "Submitted to Office"),
		("Ready for Pickup", "Picked Up"),
		("Active", "Ready for Pickup"),
		("Picked Up", "Partially Closed"),
		("Submitted to Office", "Picked Up"),
	):
		_check(status, before)


def test_other_saves_are_left_alone(cleanup):
	"""A save that keeps the status, and every status this does not govern."""
	_check("DISPATCHED", "DISPATCHED")
	_check("Active", "DISPATCHED")
	_check("Ready for Pickup", "Active")
	_check("Approved", "Pending")


# ---------------------------------------------------------------------------
# a device belongs to one open order at a time
# ---------------------------------------------------------------------------

DEVICE_FIELDS = ("status", "customer_n", "customer_name", "custom_sales_order_id")


def _device_out():
	"""A device that is out on a real order: (item_code, order, master_order_id)."""
	return frappe.db.sql(
		"""
		select soi.item_code, so.name, so.master_order_id from `tabSales Order Item` soi
		join `tabSales Order` so on so.name = soi.parent
		join `tabItem` i on i.name = soi.item_code and i.custom_sales_order_id = so.name
		where so.docstatus = 1 and so.order_type = 'Rental' and soi.child_status = 'Active'
		  and so.master_order_id != so.name and coalesce(so.master_order_id, '') != ''
		order by so.creation limit 1
		""",
	)[0]


def _closed_order(not_master):
	"""The oldest one-row rental order already Submitted to Office, in another rental."""
	return frappe.db.sql(
		"""
		select so.name, soi.name from `tabSales Order` so join `tabSales Order Item` soi on soi.parent = so.name
		where so.docstatus = 1 and so.order_type = 'Rental' and so.status = 'Submitted to Office'
		  and so.master_order_id != %s
		  and (select count(*) from `tabSales Order Item` x where x.parent = so.name) = 1
		order by so.creation limit 1
		""",
		not_master,
	)[0]


def _move(item_code, before, after):
	"""The guard alone, on the device moving from order `before` to `after`."""
	doc = frappe.get_doc("Item", item_code)
	doc._doc_before_save = frappe._dict(custom_sales_order_id=before)
	doc.custom_sales_order_id = after
	refuse_taking_a_device_from_an_open_order(doc)


def test_back_to_pickup_cannot_take_a_device_from_another_patient(cleanup):
	"""SAL-ORD-2026-11693: "Back To Pickup" on an order returned three days
	earlier put its device back on it while it was out with the next patient."""
	from erpnext.selling.doctype.sales_order.sales_order import update_status_to_pickup

	device, holder, master = _device_out()
	so, row = _closed_order(master)
	for field in DEVICE_FIELDS:
		cleanup.restore("Item", device, field)
	for field in ("status", "submitted_date"):
		cleanup.restore("Sales Order", so, field)
	for field in ("child_status", "submitted_date"):
		cleanup.restore("Sales Order Item", row, field)
	before = (frappe.db.get_value("Item", device, DEVICE_FIELDS), frappe.db.get_value("Sales Order", so, "status"))

	try:
		went_through = update_status_to_pickup(device, so, row)
	finally:
		frappe.db.rollback()

	after = (frappe.db.get_value("Item", device, DEVICE_FIELDS), frappe.db.get_value("Sales Order", so, "status"))
	assert not went_through and after == before, "%s -> %s" % (before, after)
	shown = " ".join(str(m.get("message")) for m in frappe.get_message_log())
	assert holder in shown, "the refusal does not say which order has the device: %r" % shown


def test_a_device_out_on_an_order_cannot_be_put_on_another_rental(cleanup):
	device, holder, master = _device_out()
	so, _row = _closed_order(master)

	try:
		_move(device, holder, so)
	except DeviceOnAnotherOrder as exc:
		assert holder in str(exc), exc
		return
	raise AssertionError("%s moved from %s to %s" % (device, holder, so))


def test_a_renewal_takes_the_device_within_its_rental(cleanup):
	"""The renewal and its cancellation move the device between orders that
	share a master order."""
	device, holder, master = _device_out()

	_move(device, holder, master)
	_move(device, master, holder)


def test_a_device_whose_order_is_closed_moves_freely(cleanup):
	device, holder, master = _device_out()
	so, _row = _closed_order(master)

	_move(device, so, holder)
	_move(device, None, so)
	_move(device, holder, "")


if __name__ == "__main__":
	import harness

	raise SystemExit(harness.run(sys.modules[__name__]))
