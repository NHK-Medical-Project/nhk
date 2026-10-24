"""The undo buttons on a rental's device table, refused when the device has moved on.

The "sales order html table" Client Script gives every device row a step back:
Back To Pickup (Submitted to Office), Back To Ready For PickUp (Picked Up) and
Back To Active (Ready for Pickup). Over the year to 2026-10 they were pressed
about 400 times and the office needs them to correct a wrong click, so they stay
as they are. What they may not do is pull a row back onto a device that is now
out on another order: on 2026-10-08 Back To Pickup did that to SAL-ORD-2026-11693,
whose device was by then with the next patient (`.scratch/order-status-guards/`).

The fork's methods are whitelisted with no permission check at all; these
wrappers replace them through `override_whitelisted_methods`, so the desk reaches
them under the names its Client Script already calls.
"""

import frappe
from frappe import _

from nhk.api.order_steps import DeviceOnAnotherOrder, _refuse, device_out_elsewhere


def refuse_if_out_elsewhere(item_code, sales_order):
	"""Refuse an undo on `sales_order` while its device is out on another order."""
	out = device_out_elsewhere(item_code, sales_order)
	if out:
		_refuse(
			_("{0} is already out on {1} with {2} ({3}). Close that order first.").format(
				item_code, out.name, out.customer_name, out.child_status),
			_("Device is out on {0}").format(out.name),
			DeviceOnAnotherOrder,
		)


def _guarded(item_code, sales_order):
	frappe.has_permission("Sales Order", "write", sales_order, throw=True)
	refuse_if_out_elsewhere(item_code, sales_order)


@frappe.whitelist()
def back_to_pickup(item_code, docname, child_name):
	"""Back To Pickup: a Submitted to Office row back to Picked Up, its device
	back on the order as Rented Out (`update_status_to_pickup` in the fork)."""
	from erpnext.selling.doctype.sales_order.sales_order import update_status_to_pickup

	_guarded(item_code, docname)
	if not update_status_to_pickup(item_code, docname, child_name):
		# The fork catches its own errors and returns False, keeping whatever it
		# had saved before the failure.
		frappe.db.rollback()
		return False
	return True


@frappe.whitelist()
def back_to_ready_for_pickup(item_code, docname, child_name):
	"""Back To Ready For PickUp: a Picked Up row back to Ready for Pickup
	(`update_status_back_to_ready_for_pickup` in the fork)."""
	from erpnext.selling.doctype.sales_order.sales_order import update_status_back_to_ready_for_pickup

	_guarded(item_code, docname)
	return update_status_back_to_ready_for_pickup(item_code, docname, child_name)


@frappe.whitelist()
def back_to_active(item_code, docname, child_name):
	"""The fork's Back To Active (`update_status_to_active`), which a desk on the
	Client Script from before 2026-10-21 still calls. It moved the row and left
	its pickup visit open for the technician to close later (SAL-ORD-2026-10665);
	`release_item_pickup` is what the button calls now, and this sends the old
	call there too."""
	from nhk.api.pickup import release_item_pickup

	return release_item_pickup(docname, child_name)
