"""Submitted to Office frees only the devices that are this order's to free.

Both buttons in the ERPNext fork set a device to Available whenever it reads
Rented Out, without asking which order it is Rented Out on:

- the order's **Submitted To Office** (`make_submitted_to_office`) is sent every
  device code on the order, rows already returned included. On 2026-10-21
  SAL-ORD-2026-11251 freed 2000205 that way: its row had come back on 09-28 and
  the device had gone out the same day on SAL-ORD-2026-11428.
- the row's Submitted to Office (`update_status_to_submitted_to_office`) does the
  same for one device, and when it fails it returns False, so the button shows
  nothing. On 2026-09-29 SAL-ORD-2026-10627 freed .0133493, which a corrected
  mix-up had already moved back to Krishnamma on SAL-ORD-2026-10592.

These wrappers replace both through `override_whitelisted_methods`, so the desk
reaches them under the names it already calls (`.scratch/submitted-to-office-blocked/`).
"""

import ast
import json

import frappe
from frappe import _

from nhk.api.order_steps import DeviceOnAnotherOrder, _refuse

BACK = "Submitted to Office"


def _codes(item_code):
	"""The fork takes a Python-literal list; the desk sends a JSON one."""
	if isinstance(item_code, (list, tuple)):
		return list(item_code)
	try:
		return list(json.loads(item_code))
	except ValueError:
		return list(ast.literal_eval(item_code))


def _rental(order):
	"""Every submitted order in `order`'s rental: itself, what it renewed, its renewals."""
	master = frappe.db.get_value("Sales Order", order, "master_order_id") or order
	return set(frappe.get_all(
		"Sales Order",
		filters={"master_order_id": master, "docstatus": 1},
		pluck="name",
	)) | {order}


def why_not_this_orders(item_code, order, customer):
	"""Why `order` may not free `item_code`, or None if it may.

	The device must be Rented Out, and on this order's rental: its
	`custom_sales_order_id` names an order in the rental, or is empty with the
	device Rented Out to this customer (older records).
	"""
	device = frappe.db.get_value(
		"Item", item_code, ("status", "customer_n", "customer_name", "custom_sales_order_id"), as_dict=True)
	if not device:
		return _("{0} does not exist.").format(item_code)

	linked = [o.strip() for o in (device.custom_sales_order_id or "").split(",") if o.strip()]
	rental = _rental(order)
	if linked and not rental.intersection(linked):
		elsewhere = linked[0]
		return _("{0} is on {1} ({2}, {3}) now, not on {4}. Close the row without freeing the device, or correct the device first.").format(
			item_code, elsewhere, device.customer_name or device.customer_n or _("no customer"), device.status, order)
	if device.status != "Rented Out":
		return _("{0} reads {1}, not Rented Out. Correct the device before submitting it to the office.").format(
			item_code, device.status)
	if not linked and device.customer_n and device.customer_n != customer:
		return _("{0} is Rented Out to {1}, not to this order's customer.").format(
			item_code, device.customer_name or device.customer_n)
	return None


def _check(item_code, order, customer):
	reason = why_not_this_orders(item_code, order, customer)
	if reason:
		_refuse(reason, _("{0} is not this order's to free").format(item_code), DeviceOnAnotherOrder)


@frappe.whitelist()
def submit_order_to_office(docname, item_code, submitted_date, send_email=None, customer_email=None):
	"""The order's Submitted To Office. A row already back is closed and its
	device left alone; every other device must be this order's."""
	from erpnext.selling.doctype.sales_order.sales_order import make_submitted_to_office

	frappe.has_permission("Sales Order", "write", docname, throw=True)
	doc = frappe.get_doc("Sales Order", docname)
	back = {row.item_code for row in doc.items if row.child_status == BACK}
	still_out = [code for code in _codes(item_code) if code not in back]
	for code in still_out:
		_check(code, doc.name, doc.customer)

	return make_submitted_to_office(docname, repr(still_out), submitted_date, send_email, customer_email)


@frappe.whitelist()
def submit_row_to_office(item_code, submission_datetime, docname, child_name):
	"""The row's Submitted to Office, which says why when it refuses."""
	from erpnext.selling.doctype.sales_order.sales_order import update_status_to_submitted_to_office

	frappe.has_permission("Sales Order", "write", docname, throw=True)
	row = frappe.db.get_value(
		"Sales Order Item", {"name": child_name, "parent": docname}, ("item_code", "child_status"), as_dict=True)
	if not row or row.item_code != item_code:
		frappe.throw(_("{0} is not a row of {1}. Reload the order.").format(item_code, docname))
	if row.child_status == BACK:
		frappe.throw(_("{0} is already Submitted to Office on {1}.").format(item_code, docname))
	_check(item_code, docname, frappe.db.get_value("Sales Order", docname, "customer"))

	if not update_status_to_submitted_to_office(item_code, submission_datetime, docname, child_name):
		# The fork catches its own errors and returns False, keeping whatever it
		# had saved before the failure.
		frappe.db.rollback()
		frappe.throw(_("{0} could not be Submitted to Office. See the Error Log for Sales Order.").format(item_code))
	return True
