"""A rental order's delivery steps, refused when the order has already moved on.

`make_ready_for_delivery` and `make_dispatch` in the ERPNext fork overwrite the
order's status with no look at what it is now. The form only offers each button
from the status before it, but a form, or the technician prompt it opens, can sit
on screen while someone else moves the order along. On 2026-10-03 that put
SAL-ORD-2026-11683 back from Active to Ready for Delivery ten minutes after the
cylinder was delivered, made a second delivery visit for it, and left the order
DISPATCHED with the device at the patient.

The check runs on the save rather than in the form, so it compares against the
status in the database at that moment, whatever screen the request came from.
"""

import frappe
from frappe import _

#: Each step, and the only status it may be taken from. Over the year to
#: 2026-10 every other source in the Version log was a mistake: Active (8),
#: DISPATCHED (2) and Submitted to Office (7) to Ready for Delivery, and Active
#: to DISPATCHED (1). Submitted to Office is closed: a returned device goes out
#: again on a new order, not this one.
STEP_FROM = {
	"Ready for Delivery": "Approved",
	"DISPATCHED": "Ready for Delivery",
}

#: Pickup steps, and the statuses they may *not* be taken from. A pickup can
#: start from several places (per-item pickups, "Back To Pickup"), so these
#: name the mistakes instead. A RENEWED order has handed its devices to the
#: renewal: SAL-ORD-2026-10665 was renewed on 2026-10-09 and its device
#: returned on the renewal on 10-17, then a pickup visit left open on the old
#: order was closed on 10-18 and moved it to Picked Up, where Submitted to
#: Office could never finish it. Submitted to Office goes back one step, to
#: Picked Up, and no further.
STEP_NOT_FROM = {
	"Ready for Pickup": ("RENEWED", "Submitted to Office", "Cancelled"),
	"Picked Up": ("RENEWED", "Cancelled"),
}


class OrderMovedOn(frappe.ValidationError):
	"""The order is no longer in the status this step is taken from."""


def refuse_out_of_order_step(doc, method=None):
	"""`before_update_after_submit` on Sales Order."""
	before = doc.get_doc_before_save()
	if not before or before.status == doc.status:
		return

	required = STEP_FROM.get(doc.status)
	if required and before.status != required:
		_refuse(
			_("{0} is already {1}. It can be marked {2} only while it is {3}. Reload the order.").format(
				doc.name, before.status, doc.status, required),
			_("{0} is already {1}").format(doc.name, before.status),
			OrderMovedOn,
		)

	if before.status in STEP_NOT_FROM.get(doc.status, ()):
		renewal = before.status == "RENEWED" and frappe.db.get_value(
			"Sales Order", {"previous_order_id": doc.name, "docstatus": 1}, "name")
		_refuse(
			_("{0} is already {1}, so it cannot be marked {2}.").format(doc.name, before.status, doc.status)
			+ (" " + _("Do the pickup on its renewal, {0}.").format(renewal) if renewal else ""),
			_("{0} is already {1}").format(doc.name, before.status),
			OrderMovedOn,
		)


def _refuse(message, short, exc):
	"""Show `message` and raise `exc` with `short`.

	`make_dispatch`, `make_pickedup` and `update_status_to_pickup` in the fork
	catch the exception and log its text as an Error Log *title*, which is 140
	characters; a longer text fails the logging instead. The full reason goes
	to the screen.
	"""
	frappe.msgprint(message, title=_("Not allowed"), indicator="red")
	raise exc(short)


# ---------------------------------------------------------------------------
# a device belongs to one open order at a time
# ---------------------------------------------------------------------------

#: `Sales Order Item.child_status` while the device is out with the patient, or
#: on its way to or back from them. Until the row leaves these, the device is
#: that order's.
DEVICE_OUT = ("Ready for Delivery", "DISPATCHED", "Active", "Ready for Pickup", "Picked Up")


class DeviceOnAnotherOrder(frappe.ValidationError):
	"""The device is still out on a different rental."""


def device_out_elsewhere(item_code, sales_order):
	"""The other submitted order that has `item_code` out, if any.

	An order in the same rental (`master_order_id`: the order it renewed, or its
	renewal) is not "elsewhere".
	"""
	master = frappe.db.get_value("Sales Order", sales_order, "master_order_id") or sales_order
	out = frappe.db.sql(
		"""
		select so.name, so.customer_name, soi.child_status
		from `tabSales Order Item` soi join `tabSales Order` so on so.name = soi.parent
		where soi.item_code = %s and so.docstatus = 1 and so.name != %s
		  and coalesce(so.master_order_id, so.name) != %s and soi.child_status in %s
		order by so.creation desc limit 1
		""",
		(item_code, sales_order, master, DEVICE_OUT),
		as_dict=True,
	)
	return out[0] if out else None


def refuse_taking_a_device_from_an_open_order(doc, method=None):
	"""`validate` on Item: `custom_sales_order_id` may not move off an order that
	still has the device out.

	"Back To Pickup" (`update_status_to_pickup` in the fork) writes the device
	back onto its order, Rented Out, without asking where it is now. On
	2026-10-08 it took 1200R23209543 off SAL-ORD-2026-11767, where it was
	with Sanjay kumar gomasta, and put it on SAL-ORD-2026-11693, returned three
	days earlier. Each order's later Submitted to Office then found the device
	in the wrong state.

	A renewal moves the device from the old order to the new one, and cancelling
	the renewal moves it back; both orders share a `master_order_id`, so that
	move is allowed.
	"""
	before = doc.get_doc_before_save()
	old, new = (before.get("custom_sales_order_id") if before else None), doc.get("custom_sales_order_id")
	# `nhk.custom_script.update_custom_sales_order_ids` writes comma-joined lists.
	if not old or not new or old == new or "," in old or "," in new:
		return

	out = frappe.db.sql(
		"""
		select so.customer_name, so.master_order_id, soi.child_status
		from `tabSales Order Item` soi join `tabSales Order` so on so.name = soi.parent
		where so.name = %s and so.docstatus = 1 and soi.item_code = %s and soi.child_status in %s
		limit 1
		""",
		(old, doc.name, DEVICE_OUT),
		as_dict=True,
	)
	if not out:
		return

	master = frappe.db.get_value("Sales Order", new, "master_order_id")
	if master and master == out[0].master_order_id:
		return

	_refuse(
		_("{0} is still with {1} on {2} ({3}). Close that order before putting the device on {4}.").format(
			doc.name, out[0].customer_name, old, out[0].child_status, new),
		_("Device is out on {0}").format(old),
		DeviceOnAnotherOrder,
	)
