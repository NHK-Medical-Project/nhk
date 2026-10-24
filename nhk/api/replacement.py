"""A technician replaces a device from the job they are on.

A technician finds out that a device has to be replaced only at the patient's
home: the cylinder leaks, the machine is faulty. The desk's "Item Replacement"
on the device table (Client Script "sales order html table") was the only way,
so the office replayed it afterwards. This module gives the phone the same
action with the same rules (`.scratch/device-replacement/spec.md`):

* the same rows: Ready for Delivery, DISPATCHED or Picked Up -- here, the rows
  of the Delivery or Pickup job the technician is on;
* new devices: Available, of any item group -- wider than the desk, which
  offers only the row's product type (decided 2026-10-24);
* the same fields: replacement date, old device status, reason;
* the same writes as the fork's `item_replacement` (`sales_order.py:4176`).

That function is not called: it saves the Item and the Sales Order without
`ignore_permissions`, which a technician has neither, and it turns every error
into "Please try again later". `_replace` writes what it writes, for one row.
"""

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from nhk.api.order_steps import device_out_elsewhere
from nhk.api.visits import pickup_rows

#: The row statuses the desk offers Item Replacement on, by the job that may
#: replace them. A delivery swaps a device before handing it over; a pickup
#: swaps the device it collected, and the row goes back to Active.
REPLACEABLE = {
	"Delivery": ("Ready for Delivery", "DISPATCHED"),
	"Pickup": ("Picked Up",),
}

#: The desk prompt's "Old Item Status" options.
OLD_ITEM_STATUSES = ("Available", "Sold", "Damaged", "Repair Required", "Retired")

#: How many devices the picker shows at a time; the technician types the serial.
DEVICE_LIST_LIMIT = 20


def options(visit):
	"""What the job screen needs to offer a replacement, or None when it has nothing to replace."""
	rows = replaceable_rows(visit)
	if not rows:
		return None
	return {
		"rows": rows,
		"old_item_statuses": OLD_ITEM_STATUSES,
		"reasons": frappe.get_all("Item Replacement Reason", pluck="name", order_by="name asc"),
	}


def replaceable_rows(visit):
	"""The rows of the visit's order its technician may replace now."""
	statuses = REPLACEABLE.get(visit.type)
	if not statuses or not visit.sales_order_id:
		return []
	if frappe.db.get_value("Sales Order", visit.sales_order_id, "docstatus") != 1:
		return []
	filters = {"parent": visit.sales_order_id, "child_status": ("in", statuses)}
	if visit.type == "Pickup":
		# An item pickup collects only its own rows; empty means the whole order.
		rows = pickup_rows(visit)
		if rows:
			filters["name"] = ("in", rows)
	return frappe.get_all(
		"Sales Order Item",
		filters=filters,
		fields=["name", "item_code", "item_name", "item_group", "child_status"],
		order_by="idx asc",
	)


def devices(visit, row, txt=None):
	"""Devices that may replace `row`: Available, of any item group."""
	row = _replaceable_row(visit, row)
	or_filters = None
	if txt and txt.strip():
		like = "%{0}%".format(txt.strip())
		or_filters = {"name": ("like", like), "item_name": ("like", like)}
	found = frappe.get_all(
		"Item",
		filters={"status": "Available", "disabled": 0},
		or_filters=or_filters,
		fields=["name", "item_name", "item_group"],
		order_by="name asc",
		limit=DEVICE_LIST_LIMIT,
	)
	# Available but still out on an order is a record gone wrong; offering it
	# would only end in a refusal.
	return [d for d in found if not device_out_elsewhere(d.name, visit.sales_order_id)]


def replace(visit, row, new_item, old_item_status, reason, replacement_date=None):
	"""Replace `row`'s device with `new_item`, as the desk's Item Replacement does."""
	row = _replaceable_row(visit, row)

	if old_item_status not in OLD_ITEM_STATUSES:
		frappe.throw(_("Choose what happens to {0}: {1}.").format(row.item_code, ", ".join(OLD_ITEM_STATUSES)))
	if not reason or not frappe.db.exists("Item Replacement Reason", reason):
		frappe.throw(_("Choose a reason for the replacement."))
	if not new_item or not frappe.db.exists("Item", new_item):
		frappe.throw(_("Device {0} does not exist.").format(new_item or ""))
	if new_item == row.item_code:
		frappe.throw(_("{0} is the device being replaced. Choose another.").format(new_item))

	new = frappe.get_doc("Item", new_item)
	if new.status != "Available":
		frappe.throw(_("{0} is {1}, not Available. Choose another device.").format(new.name, new.status))
	out = device_out_elsewhere(new.name, visit.sales_order_id)
	if out:
		frappe.throw(_("{0} is still out on {1} with {2} ({3}). Choose another device.").format(
			new.name, out.name, out.customer_name, out.child_status))

	when = get_datetime(replacement_date) if replacement_date else now_datetime()
	if when > now_datetime():
		frappe.throw(_("The replacement date cannot be in the future."))

	old_item = row.item_code
	status = _replace(visit.sales_order_id, row.name, new, old_item_status, reason, when)

	text = _("Device replaced on {0} by {1}: {2} -> {3}. Old device {4}. Reason: {5}.").format(
		visit.name, frappe.utils.get_fullname(frappe.session.user), old_item, new.name, old_item_status, reason)
	for doctype, name in (("Sales Order", visit.sales_order_id), ("Technician Visit Entry", visit.name)):
		frappe.get_doc(doctype, name).add_comment(
			"Comment", frappe.utils.escape_html(text), comment_email=frappe.session.user,
			comment_by=frappe.utils.get_fullname(frappe.session.user))

	return {"row": row.name, "old_item": old_item, "new_item": new.name, "child_status": status}


def _replaceable_row(visit, row):
	for r in replaceable_rows(visit):
		if r.name == row:
			return r
	status = frappe.db.get_value("Sales Order Item", {"name": row, "parent": visit.sales_order_id}, "child_status")
	if not status:
		frappe.throw(_("That device is not on {0}.").format(visit.sales_order_id))
	frappe.throw(_("A device that is {0} cannot be replaced from a {1} job. Reload the job.").format(
		status, visit.type))


def _replace(sales_order, row_name, new, old_item_status, reason, when):
	"""What the fork's `item_replacement` writes, for one row. Returns the row's status.

	Kept to its writes, including a Reserved new device getting no order link;
	a change there in the fork needs the same change here.
	"""
	order = frappe.get_doc("Sales Order", sales_order)
	row = frappe.get_doc("Sales Order Item", row_name)
	old_item = row.item_code

	frappe.get_doc({
		"doctype": "Rental Order Replaced Item",
		"master_order_id": order.master_order_id,
		"sales_order_id": order.name,
		"replaced_datetime": when,
		"old_item": old_item,
		"new_item": new.name,
		"reason": reason,
	}).insert(ignore_permissions=True)

	if row.child_status == "Picked Up":
		row.child_status = "Active"
		new.status = "Rented Out"
		new.customer_n = order.customer
		new.custom_sales_order_id = order.name
	else:
		new.status = "Reserved"
	row.replaced_datetime = when
	row.old_item_code = old_item
	row.item_group = new.item_group
	row.item_code = new.name
	row.item_name = new.item_name
	row.save(ignore_permissions=True)
	new.save(ignore_permissions=True)

	old = frappe.get_doc("Item", old_item)
	old.status = old_item_status
	old.customer_n = ""
	old.customer_name = ""
	old.custom_sales_order_id = ""
	old.replaced_reason = reason
	old.save(ignore_permissions=True)

	statuses = frappe.get_all("Sales Order Item", filters={"parent": order.name}, pluck="child_status")
	if any(s not in ("Ready for Delivery", "DISPATCHED") for s in statuses):
		order.reload()
		if all(s == "Active" for s in statuses):
			order.status = "Active"
		elif any(s == "Submitted to Office" for s in statuses):
			order.status = "Partially Closed"
		else:
			order.status = "Active"
		order.flags.ignore_permissions = True
		order.save()

	return row.child_status
