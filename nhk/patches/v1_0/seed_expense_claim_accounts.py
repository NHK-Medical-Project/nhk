"""Seed default expense accounts for Expense Claim Types under company NHK MEDICAL.

HRMS refuses to save an Expense Claim if the Expense Claim Type has no default
account configured for the company. Without these accounts, `nhk.api.expense_claims`
cannot offer any expense types to technicians.
"""

import frappe

MAPPING = {
	"Travel": "Travel Expenses - INR",
	"Calls": "Telephone Expenses - INR",
	"Food": "Miscellaneous Expenses - INR",
	"Medical": "Miscellaneous Expenses - INR",
	"Others": "Miscellaneous Expenses - INR",
}


def execute():
	company = frappe.defaults.get_global_default("company") or "NHK MEDICAL"
	if not frappe.db.exists("Company", company):
		return

	for type_name, default_account in MAPPING.items():
		if not frappe.db.exists("Expense Claim Type", type_name):
			continue
		if not frappe.db.exists("Account", default_account):
			continue

		doc = frappe.get_doc("Expense Claim Type", type_name)
		if not any(row.company == company for row in doc.accounts):
			doc.append("accounts", {"company": company, "default_account": default_account})
			doc.save(ignore_permissions=True)
