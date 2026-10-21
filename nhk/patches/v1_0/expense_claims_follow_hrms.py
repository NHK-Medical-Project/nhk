"""Technician expense claims follow the plain HRMS flow (ADR 0008, 2026-10-19).

- Drops the custom fields the app's own Mark Paid / Reject used: the decision is
  HRMS's Approval Status, submit and payment now.
- NHK Admin, the office, may set Approval Status on the desk: HRMS keeps it at
  permlevel 1, which NHK Admin did not hold. Nothing else changes.
"""

import frappe
from frappe.permissions import add_permission, update_permission_property

CLAIM = "Expense Claim"
DROPPED = ("custom_rejection_reason", "custom_payment_reference", "custom_decided_on", "custom_decided_by")


def execute():
	for fieldname in DROPPED:
		name = f"{CLAIM}-{fieldname}"
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, ignore_permissions=True)

	if frappe.db.exists("Role", "NHK Admin"):
		add_permission(CLAIM, "NHK Admin", permlevel=1)
		update_permission_property(CLAIM, "NHK Admin", 1, "write", 1)
	frappe.clear_cache(doctype=CLAIM)
