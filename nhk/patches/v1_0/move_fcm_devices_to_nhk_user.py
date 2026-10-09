"""Move phones from the short-lived `FCM Device` doctype onto NHK User.

Decided 2026-09-29: a user's phones live in the `devices` table on their NHK
User (`nhk.api.devices`). FCM Device existed for a day, on nhk.local only, with
one real row. Rows move across, then the doctype and its table go.

The rows are inserted as child rows directly. Saving an NHK User after submit
runs `before_update_after_submit`, which resets the login's password to the
record's stored one and rebuilds its roles -- see `nhk.api.devices`.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "FCM Device"):
		return

	if frappe.db.table_exists("FCM Device"):
		from nhk.api.devices import _add_device_row

		for row in frappe.db.sql(
			"select user, token, platform, device_name, enabled, last_seen from `tabFCM Device`",
			as_dict=True,
		):
			if frappe.db.exists("NHK User", row.user):
				_add_device_row(row.user, row.token, row.platform, row.device_name, row.last_seen)
			else:
				frappe.log_error(
					title="FCM Device not moved",
					message="%s has no NHK User record; its phone must register again." % row.user,
				)

	frappe.delete_doc("DocType", "FCM Device", force=True, ignore_permissions=True)
