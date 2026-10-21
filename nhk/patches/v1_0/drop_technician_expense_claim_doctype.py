"""Technician expense claims are HRMS Expense Claims now (`nhk.api.expense_claims`,
decided 2026-10-16). Drop the short-lived `Technician Expense Claim` doctype.

It only ever existed on development sites. Its rows are not carried over: if a
site still has any, the doctype is left in place and the patch says so, so a
claim is never deleted silently.
"""

import frappe

OLD = "Technician Expense Claim"


def execute():
	if not frappe.db.exists("DocType", OLD):
		return
	if frappe.db.table_exists(OLD) and frappe.db.count(OLD):
		print(f"{OLD}: {frappe.db.count(OLD)} claim(s) left; re-file them as Expense Claims, delete them, "
			  "then run `bench execute nhk.patches.v1_0.drop_technician_expense_claim_doctype.execute`.")
		return
	for name in frappe.get_all("File", filters={"attached_to_doctype": OLD}, pluck="name"):
		frappe.delete_doc("File", name, ignore_permissions=True, delete_permanently=True)
	frappe.delete_doc("DocType", OLD, ignore_missing=True, force=True)
