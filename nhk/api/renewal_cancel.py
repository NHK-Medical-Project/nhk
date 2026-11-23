"""What happens to a rental's devices when one of its orders is cancelled.

The fork's `SalesOrder.before_cancel` (`sales_order.py:750`) hands a cancelled
renewal back to the order it renewed by walking the *previous* order's rows:
each row takes the status of the same device on the renewal, or Active when
the renewal has no such device, and its device is linked back to the previous
order. `on_cancel` (`sales_order.py:886`) then frees the devices only for an
order that is not a renewal.

A device swapped with Item Replacement during the rental is on the renewal but
not on the order it renewed, so neither step sees it. SAL-ORD-2026-06921 swapped
20112100298 for Mindray Monitor - 1702 on 2026-06-27; when it was cancelled on
2026-08-22 the monitor stayed Rented Out on a cancelled order for three months,
and 20112100298, by then out with another patient on SAL-ORD-2026-08278, was
linked back to SAL-ORD-2026-05506 and that order's row reactivated.

`hand_back_to_previous_order` replaces the fork's hand-back
(`nhk.overrides.sales_order.NHKSalesOrder.before_cancel`): it walks the
*cancelled* order's devices, and a swapped-in device takes over the row of the
device it replaced. `release_devices_left_on_cancelled_order` (`on_cancel`)
frees any device still linked to an order once it is cancelled.
"""

import frappe
from frappe import _

from nhk.api.order_steps import DEVICE_OUT

#: Item statuses that tie a device to an order.
HELD = ("Rented Out", "Reserved", "Pre Reserved")

#: Order statuses that no longer hold their devices, whatever the rows say.
#: Rows on these orders are often left Active (SAL-ORD-2026-08388 kept its row
#: Active after it was cancelled), so the order status decides.
CLOSED = ("Rental SO Completed", "Submitted to Office", "RENEWED", "Completed", "Closed", "Cancelled")


# ---------------------------------------------------------------------------
# a cancelled renewal hands its devices back to the order it renewed
# ---------------------------------------------------------------------------

def hand_back_to_previous_order(doc):
	"""`before_cancel` on a renewal: the previous order takes the rental back.

	As in the fork, the previous order takes the cancelled order's status, each
	of its rows the status of the matching row, and each device is linked back
	to it unless the cancelled order is Submitted to Office. Unlike the fork:

	* rows are matched from the cancelled order's devices, so a device swapped
	  in on the renewal takes over the row of the device it replaced;
	* a row of the previous order with no device on the renewal is left as it
	  is, and its device is not touched: it was swapped out and may be with
	  another patient now.
	"""
	prev = frappe.get_doc("Sales Order", doc.previous_order_id)
	by_device = {r.item_code: r for r in prev.items}
	master = doc.get("master_order_id") or prev.get("master_order_id") or prev.name

	matched = {}  # previous row name -> cancelled order's row
	for row in doc.items:
		target = by_device.get(row.item_code)
		if target is None:
			origin = replaced_from(master, row.item_code, row.get("old_item_code"), set(by_device))
			target = by_device.get(origin) if origin else None
		if target is not None and target.name not in matched:
			matched[target.name] = row

	prev.status = doc.status
	for target in prev.items:
		if target.name in matched:
			target.child_status = matched[target.name].child_status
	prev.flags.ignore_permissions = True
	prev.save()

	# Written after the save: the in-memory rows still name the old device, and
	# saving them afterwards would put it back.
	taken_over = []
	for target in prev.items:
		row = matched.get(target.name)
		if row is None or row.item_code == target.item_code:
			continue
		frappe.db.set_value("Sales Order Item", target.name, {
			"item_code": row.item_code,
			"item_name": row.item_name,
			"item_group": row.item_group,
			"old_item_code": target.item_code,
			"replaced_datetime": row.get("replaced_datetime"),
		})
		taken_over.append((target.item_code, row.item_code))

	if doc.status != "Submitted to Office":
		for row in matched.values():
			device = frappe.get_doc("Item", row.item_code)
			if device.custom_sales_order_id != prev.name:
				device.custom_sales_order_id = prev.name
				device.flags.ignore_permissions = True
				device.save()

	for old, new in taken_over:
		frappe.msgprint(_("{0} now holds {1}, which replaced {2} during the rental. {2} was left as it is.").format(
			prev.name, new, old))
	for target in prev.items:
		if target.name not in matched:
			frappe.msgprint(_("{0} on {1} is not on {2} and was left as it is ({3}). Check where it is.").format(
				target.item_code, prev.name, doc.name, target.child_status))


def replaced_from(master, device, old_item_code, candidates):
	"""The device in `candidates` that `device` replaced, through any number of
	Item Replacements in the rental `master`, or None.

	Walks the replacement records backwards in time, so a device swapped out
	and back in again (SAL-ORD-2026-08388: the monitor out on 07-30, back on
	08-02) is followed to where it first came in. Falls back to the row's
	`old_item_code` when the rental has no record of it.
	"""
	# Each step goes strictly back in time, so the walk ends even when a device
	# comes up twice.
	before = None
	while device not in candidates:
		filters = {"master_order_id": master, "new_item": device}
		if before:
			filters["replaced_datetime"] = ("<", before)
		record = frappe.db.get_value(
			"Rental Order Replaced Item", filters, ("old_item", "replaced_datetime"),
			order_by="replaced_datetime desc", as_dict=True)
		if not record:
			return old_item_code if old_item_code in candidates else None
		device, before = record.old_item, record.replaced_datetime
	return device


# ---------------------------------------------------------------------------
# a device is never left on a cancelled order
# ---------------------------------------------------------------------------

def release_devices_left_on_cancelled_order(doc, method=None):
	"""`on_cancel` on Sales Order, after the fork's own.

	A device still linked to this order, and out on no other open order, goes
	back to Available. One that another open order has out is left alone and
	named on screen.
	"""
	if doc.get("order_type") != "Rental":
		return

	for code in sorted({r.item_code for r in doc.get("items") or []}):
		device = frappe.db.get_value("Item", code, ("status", "custom_sales_order_id"), as_dict=True)
		if not device or device.custom_sales_order_id != doc.name or device.status not in HELD:
			continue
		holder = open_order_with(code, doc.name)
		if holder:
			frappe.msgprint(_("{0} is still linked to {1}, but {2} has it out ({3}). Correct the device by hand.").format(
				code, doc.name, holder.name, holder.child_status))
			continue
		release(code, _("Released when {0} was cancelled.").format(doc.name))


def open_order_with(item_code, other_than):
	"""The open submitted order that has `item_code` out, if any."""
	out = frappe.db.sql(
		"""
		select so.name, soi.child_status
		from `tabSales Order Item` soi join `tabSales Order` so on so.name = soi.parent
		where soi.item_code = %s and so.name != %s and so.docstatus = 1
		  and so.status not in %s and soi.child_status in %s
		order by so.creation desc limit 1
		""",
		(item_code, other_than, CLOSED, DEVICE_OUT),
		as_dict=True,
	)
	return out[0] if out else None


def release(item_code, note):
	"""Available, with the customer and order cleared, and a comment saying why."""
	frappe.db.set_value("Item", item_code, {
		"status": "Available",
		"customer_n": "",
		"customer_name": "",
		"custom_sales_order_id": "",
	})
	frappe.get_doc("Item", item_code).add_comment("Info", note)


# ---------------------------------------------------------------------------
# repair: devices already left on cancelled orders
# ---------------------------------------------------------------------------

def stuck_devices():
	"""Devices Rented Out / Reserved on an order that is cancelled, and which
	open order (if any) has each one out. Read-only.

	bench --site <site> execute nhk.api.renewal_cancel.stuck_devices
	"""
	rows = frappe.db.sql(
		"""
		select i.name as item_code, i.status, i.customer_name, i.custom_sales_order_id as sales_order
		from `tabItem` i join `tabSales Order` so on so.name = i.custom_sales_order_id
		where i.status in %s and so.docstatus = 2
		order by i.name
		""",
		(HELD,),
		as_dict=True,
	)
	for r in rows:
		holder = open_order_with(r.item_code, r.sales_order)
		r.out_on = "%s (%s)" % (holder.name, holder.child_status) if holder else None
	return rows
