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


def _replace(sales_order, row_name, new, old_item_status, reason, when, delivered=False):
	"""What the fork's `item_replacement` writes, for one row. Returns the row's status.

	Kept to its writes, including a Reserved new device getting no order link;
	a change there in the fork needs the same change here.

	`delivered`: the new device has been handed over at the patient's home (a
	completed Replacement visit). The row stays Active, the new device is Rented
	Out, and the order's status is left alone -- nothing about it changed.
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

	if delivered or row.child_status == "Picked Up":
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

	if delivered:
		return row.child_status

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


# ---------------------------------------------------------------------------
# A replacement the office schedules (`.scratch/device-replacement-visit`)
#
# A device at the patient's home (row Active) is faulty. The office picks the
# new device and a technician on the desk; the new device is Reserved for the
# order at once, so nobody else hands it out. The technician carries it to the
# patient on a `Replacement` visit, and completing that visit makes the swap:
# the row takes the new device, which goes Rented Out, and the old one gets the
# status the office chose -- Available by default, i.e. back in stock.
#
# Until then the row and both devices stay as they are. Cancelling the visit
# releases the reserved device.
# ---------------------------------------------------------------------------

#: The visit type a scheduled replacement travels on.
REPLACEMENT = "Replacement"

#: Rows a technician can take a replacement to: the device is at the home.
SCHEDULABLE_ROW_STATUSES = ("Active",)

#: What the old device becomes unless the office says otherwise: back in stock.
DEFAULT_OLD_ITEM_STATUS = "Available"


@frappe.whitelist()
def available_devices(sales_order_id, txt=None, limit=DEVICE_LIST_LIMIT):
	"""Devices the desk may offer as the new device: Available, any item group.

	The desk prompt used to offer only the row's product type; every group is
	offered now (decided 2026-10-24 for the phone, 2026-11-23 for the desk).
	"""
	or_filters = None
	if txt and txt.strip():
		like = "%{0}%".format(txt.strip())
		or_filters = {"name": ("like", like), "item_name": ("like", like), "item_group": ("like", like)}
	found = frappe.get_all(
		"Item",
		filters={"status": "Available", "disabled": 0},
		or_filters=or_filters,
		fields=["name", "item_name", "item_group"],
		order_by="name asc",
		limit=frappe.utils.cint(limit) or DEVICE_LIST_LIMIT,
	)
	return [d for d in found if not device_out_elsewhere(d.name, sales_order_id)]


@frappe.whitelist()
def schedule_replacement(sales_order_id, row, new_item, technician_id=None, technician_category=None,
						 replacement_date=None, slot=None, old_item_status=DEFAULT_OLD_ITEM_STATUS,
						 reason=None, remark=None):
	"""Replace one Active row's device: on a technician's visit, or at once.

	With a technician: creates a `Replacement` visit carrying the row (in
	`items`), the new device, what the old device becomes and why. The new
	device is Reserved for the order now; the swap itself happens when the
	visit is completed (`complete_scheduled`).

	Without one: the swap happens now, as Item Replacement does on the other
	stages, where a visit was never required (decided by the user 2026-11-25).
	`replacement_date` is then when it was replaced, and the category and slot
	are not used.
	"""
	# Imported here: `pickup` imports `visits`, which imports this module lazily.
	from nhk.api.pickup import _create_office_pickup, _pickup_category, _pickup_technician

	if technician_id:
		frappe.has_permission("Technician Visit Entry", "share", throw=True)

	order = _rental(sales_order_id)
	item = _schedulable_row(order, row)
	open_visit = open_replacement_of(item.name)
	if open_visit:
		frappe.throw(_("{0} already has replacement {1} open with {2}. Cancel it first.").format(
			item.item_code, open_visit.name, open_visit.technician_name or open_visit.technician_id))

	old_item_status = old_item_status or DEFAULT_OLD_ITEM_STATUS
	_check_choices(old_item_status, reason)
	new = _free_device(new_item, item.item_code, sales_order_id)

	if not technician_id:
		return _replace_now(order, item, new, old_item_status, reason, replacement_date, remark)

	target = _pickup_technician(technician_id)
	when, slot = _when(replacement_date, slot)
	technician_category = _pickup_category(sales_order_id, technician_category)

	fields = {
		"new_item": new.name,
		"old_item_status": old_item_status,
		"replacement_reason": reason,
		# What the app's job tile shows: the device out, and the one going in.
		"item_code": "{0} -> {1}".format(item.item_code, new.name),
	}
	if remark and remark.strip():
		fields["order_notes"] = remark.strip()
	visit = _create_office_pickup(order, target, technician_category, when, slot, [item],
								  visit_type=REPLACEMENT, fields=fields)

	# Reserved and pointed at the order, so the device list shows where it is
	# going. The fork's Reserved carries no order; nothing reads it there.
	new.status = "Reserved"
	new.custom_sales_order_id = order.name
	new.save(ignore_permissions=True)

	line = _("Replacement of {0} with {1} assigned to {2} on {3} by office ({4}). Old device will be {5}. Reason: {6}.").format(
		item.item_code, new.name, target.name1 or target.name, visit.name, frappe.session.user,
		old_item_status, reason)
	_comment(line, order.name, visit.name)
	return {"name": visit.name, "technician_name": target.name1 or target.name, "new_item": new.name}


def _replace_now(order, item, new, old_item_status, reason, replacement_date, remark):
	"""The swap with no visit: the row keeps Active with the new device, which
	is Rented Out; the old device takes `old_item_status`."""
	when = _replaced_at(replacement_date)
	old_item = item.item_code
	_replace(order.name, item.name, new, old_item_status, reason, when, delivered=True)

	line = _("Device replaced by office ({0}) without a technician visit: {1} -> {2}. Old device {3}. Reason: {4}.").format(
		frappe.session.user, old_item, new.name, old_item_status, reason)
	if remark and remark.strip():
		line += " " + remark.strip()
	frappe.get_doc("Sales Order", order.name).add_comment(
		"Comment", frappe.utils.escape_html(line), comment_email=frappe.session.user,
		comment_by=frappe.utils.get_fullname(frappe.session.user))
	return {"name": None, "replaced": True, "old_item": old_item, "new_item": new.name}


def _replaced_at(day):
	"""When an immediate swap happened: now for today (or no date), else the
	start of that past day. Never the future."""
	if not day or frappe.utils.getdate(day) == frappe.utils.getdate():
		return now_datetime()
	if frappe.utils.getdate(day) > frappe.utils.getdate():
		frappe.throw(_("The replacement date cannot be in the future."))
	return get_datetime(frappe.utils.getdate(day))


@frappe.whitelist()
def cancel_replacement(visit_id, note=None):
	"""Call off an open Replacement visit: the visit is Closed unpaid, the
	reserved device goes back to Available, the row keeps its device."""
	from nhk.api.visits import _assert_office_may_change

	visit = frappe.get_doc("Technician Visit Entry", visit_id)
	if visit.type != REPLACEMENT:
		frappe.throw(_("{0} is a {1} visit, not a replacement.").format(visit.name, visit.type))
	if visit.status != "Assigned":
		frappe.throw(_("{0} is already {1}.").format(visit.name, visit.status))
	_assert_office_may_change(visit)

	_release(visit.new_item, visit.sales_order_id)
	visit.status = "Closed"
	visit.charges = 0
	visit.save(ignore_permissions=True)

	line = _("Replacement {0} cancelled by office ({1}); {2} released.").format(
		visit.name, frappe.session.user, visit.new_item)
	if note and note.strip():
		line += " " + note.strip()
	_comment(line, visit.sales_order_id, visit.name)
	return {"name": visit.name, "status": visit.status}


def complete_scheduled(visit):
	"""Make the swap a Replacement visit carried. Called while the visit closes
	(`nhk.api.visits._advance_sales_order`); does not commit.

	Refused, and so the visit stays open, when the order moved on since the
	office scheduled it: the row is no longer Active with the old device, or
	the new device is no longer reserved for this order.
	"""
	row_name = replacement_row(visit)
	if not row_name:
		frappe.throw(_("{0} does not say which device to replace. Call the office.").format(visit.name))
	row = frappe.db.get_value("Sales Order Item", {"name": row_name, "parent": visit.sales_order_id},
							  ["name", "item_code", "child_status"], as_dict=True)
	old_item = visit.items[0].item_code
	if not row or row.child_status not in SCHEDULABLE_ROW_STATUSES or row.item_code != old_item:
		frappe.throw(_("{0} is no longer at the patient's home on {1} ({2}), so it cannot be replaced. Call the office.")
					 .format(old_item, visit.sales_order_id,
							 row.child_status if row else _("not on the order")))

	new = frappe.get_doc("Item", visit.new_item)
	if new.status != "Reserved" or new.custom_sales_order_id != visit.sales_order_id:
		frappe.throw(_("{0} is {1}, not reserved for {2}. Call the office.").format(
			new.name, new.status, visit.sales_order_id))
	out = device_out_elsewhere(new.name, visit.sales_order_id)
	if out:
		frappe.throw(_("{0} is still out on {1} with {2}. Call the office.").format(
			new.name, out.name, out.customer_name))

	_replace(visit.sales_order_id, row.name, new, visit.old_item_status or DEFAULT_OLD_ITEM_STATUS,
			 visit.replacement_reason, visit.completed_at or now_datetime(), delivered=True)

	_comment(_("Device replaced on {0}: {1} -> {2}. Old device {3}. Reason: {4}.").format(
		visit.name, old_item, new.name, visit.old_item_status or DEFAULT_OLD_ITEM_STATUS,
		visit.replacement_reason), visit.sales_order_id, visit.name)


def replacement_row(visit):
	"""The Sales Order Item row a Replacement visit swaps."""
	return visit.items[0].sales_order_item if visit.get("items") else None


def open_replacement_of(row_name):
	"""The open Replacement visit that carries `row_name`, if any."""
	name = frappe.db.sql(
		"""
		select v.name from `tabTechnician Visit Entry` v
		join `tabTechnician Visit Item` i on i.parent = v.name and i.parenttype = 'Technician Visit Entry'
		where v.type = %s and v.status = 'Assigned' and i.sales_order_item = %s
		order by v.creation desc limit 1
		""",
		(REPLACEMENT, row_name),
	)
	return frappe.get_doc("Technician Visit Entry", name[0][0]) if name else None


def scheduled_details(visit):
	"""What the job screen shows for a Replacement visit: the device to take
	and the one to bring back."""
	if visit.type != REPLACEMENT:
		return None
	old_item = visit.items[0].item_code if visit.get("items") else None
	return {
		"row": replacement_row(visit),
		"old_item": old_item,
		"old_item_name": frappe.db.get_value("Item", old_item, "item_name") if old_item else None,
		"new_item": visit.new_item,
		"new_item_name": frappe.db.get_value("Item", visit.new_item, "item_name") if visit.new_item else None,
		"old_item_status": visit.old_item_status,
		"reason": visit.replacement_reason,
	}


def _when(day, slot):
	"""The visit's scheduled time: the day at its slot's start, as a pickup's."""
	from nhk.api.pickup import DEFAULT_SLOT, SLOT_STARTS
	from nhk.api.visits import SLOTS

	slot = slot or DEFAULT_SLOT
	if slot not in SLOTS:
		frappe.throw(_("Slot must be one of {0}.").format(", ".join(SLOTS)))
	day = frappe.utils.getdate(day) if day else frappe.utils.getdate()
	if day < frappe.utils.getdate():
		frappe.throw(_("The replacement date cannot be in the past."))
	return get_datetime("%s %s" % (day, SLOT_STARTS[slot])), slot


def _rental(sales_order_id):
	if not sales_order_id or not frappe.db.exists("Sales Order", sales_order_id):
		frappe.throw(_("Sales Order {0} does not exist.").format(sales_order_id))
	order = frappe.get_doc("Sales Order", sales_order_id)
	if order.docstatus != 1 or order.order_type != "Rental":
		frappe.throw(_("Only a submitted rental's devices can be replaced. {0} is not one.").format(order.name))
	frappe.has_permission("Sales Order", "write", doc=order, throw=True)
	return order


def _schedulable_row(order, row):
	for item in order.items:
		if item.name == row:
			if item.child_status not in SCHEDULABLE_ROW_STATUSES:
				frappe.throw(_("{0} is {1}. A technician replacement is for a device at the patient's home (Active); use Item Replacement on the row instead.")
							 .format(item.item_code, item.child_status or _("not set")))
			return item
	frappe.throw(_("That device is not on {0}.").format(order.name))


def _check_choices(old_item_status, reason):
	if old_item_status not in OLD_ITEM_STATUSES:
		frappe.throw(_("Old device status must be one of {0}.").format(", ".join(OLD_ITEM_STATUSES)))
	if not reason or not frappe.db.exists("Item Replacement Reason", reason):
		frappe.throw(_("Choose a reason for the replacement."))


def _free_device(new_item, old_item, sales_order_id):
	if not new_item or not frappe.db.exists("Item", new_item):
		frappe.throw(_("Device {0} does not exist.").format(new_item or ""))
	if new_item == old_item:
		frappe.throw(_("{0} is the device being replaced. Choose another.").format(new_item))
	new = frappe.get_doc("Item", new_item)
	if new.status != "Available":
		frappe.throw(_("{0} is {1}, not Available. Choose another device.").format(new.name, new.status))
	out = device_out_elsewhere(new.name, sales_order_id)
	if out:
		frappe.throw(_("{0} is still out on {1} with {2} ({3}). Choose another device.").format(
			new.name, out.name, out.customer_name, out.child_status))
	return new


def _release(item_code, sales_order_id):
	"""Put a device reserved for a replacement back in stock."""
	if not item_code or not frappe.db.exists("Item", item_code):
		return
	item = frappe.get_doc("Item", item_code)
	if item.status != "Reserved" or item.custom_sales_order_id not in (sales_order_id, None, ""):
		return
	item.status = "Available"
	item.custom_sales_order_id = ""
	item.save(ignore_permissions=True)


def _comment(text, sales_order, visit):
	for doctype, name in (("Sales Order", sales_order), ("Technician Visit Entry", visit)):
		if name:
			frappe.get_doc(doctype, name).add_comment(
				"Comment", frappe.utils.escape_html(text), comment_email=frappe.session.user,
				comment_by=frappe.utils.get_fullname(frappe.session.user))
