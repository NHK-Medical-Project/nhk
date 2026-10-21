"""Move uploads from the short-lived `Technician Document` doctype onto NHK User.

Decided 2026-10-15: a technician's documents live in the `documents` table on
their NHK User (`nhk.api.technician_documents`). Technician Document existed for
a day, on nhk.local only. Rows move across with their files re-attached to the
NHK User, then the doctype and its table go.

The rows are inserted as child rows directly. Saving an NHK User after submit
resets the login's password and rebuilds its roles -- see `nhk.api.devices`.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "Technician Document"):
		return

	left = 0
	if frappe.db.table_exists("Technician Document"):
		from nhk.api.devices import nhk_user_of
		from nhk.api.technician_documents import PARENT, PARENTFIELD, _add_document_row

		for row in frappe.db.sql(
			"""select d.name, d.document_type, d.title, d.vehicle_number, d.file, t.user_mail_id
			from `tabTechnician Document` d
			left join `tabTechnician Details` t on t.name = d.technician
			order by d.creation""",
			as_dict=True,
		):
			nhk_user = nhk_user_of(row.user_mail_id)
			if not nhk_user:
				frappe.log_error(
					title="Technician Document not moved",
					message="%s (%s) has no NHK User record; it stays on the old record, which is kept until it is moved."
					% (row.name, row.user_mail_id),
				)
				left += 1
				continue
			_add_document_row(nhk_user, row.document_type, row.title, row.vehicle_number, row.file)
			frappe.db.set_value(
				"File",
				{"attached_to_doctype": "Technician Document", "attached_to_name": row.name},
				{"attached_to_doctype": PARENT, "attached_to_name": nhk_user, "attached_to_field": PARENTFIELD},
				update_modified=False,
			)
			frappe.db.delete("Technician Document", {"name": row.name})

	if left:
		# Deleting the doctype drops its table, and these rows with it.
		return
	frappe.delete_doc("DocType", "Technician Document", force=True, ignore_permissions=True)
