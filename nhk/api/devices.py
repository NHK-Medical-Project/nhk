"""Which phone belongs to which user, for push notifications.

`fcm_360ithub` sends to one token it is handed and keeps no record of whose
token is whose. This is that record: the `devices` table on each user's
**NHK User** (decided 2026-09-29), one row per install of the technician app,
registered by the app itself after login and whenever Firebase rotates the
token.

**The NHK User is never saved to change its devices.** NHK User is submitted,
and saving it after submit runs `NHKUser.before_update_after_submit`, which
sets the login's password back to the plain-text `password` stored on the
record, rebuilds its role profiles, creates or deletes its Sales Person, and
logs the password. Registering a phone must not do any of that, so the rows are
written as child rows directly (`_add_device_row`, `frappe.db.set_value`,
`frappe.db.delete`). That also works on a cancelled NHK User.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

PLATFORMS = ("Android", "iOS", "Web")

#: The `NHK User Device.token` column width. Firebase tokens run to about 160
#: characters; anything longer is not a token.
MAX_TOKEN_LENGTH = 255

DEVICE = "NHK User Device"


def _caller():
	if frappe.session.user in (None, "Guest"):
		frappe.throw(_("Log in to register this device for notifications."), frappe.PermissionError)
	return frappe.session.user


def nhk_user_of(user):
	"""The NHK User record for a login: named by the email, which is the login id."""
	if not user:
		return None
	return frappe.db.get_value("NHK User", user, "name") or frappe.db.get_value(
		"NHK User", {"email": user}, "name"
	)


def _rows_with_token(token):
	return frappe.get_all(
		DEVICE,
		filters={"token": token, "parenttype": "NHK User", "parentfield": "devices"},
		fields=["name", "parent"],
	)


def _add_device_row(nhk_user, token, platform=None, device_name=None, last_seen=None):
	"""Append a device row to an NHK User without saving the NHK User."""
	parent_docstatus = frappe.db.get_value("NHK User", nhk_user, "docstatus")
	last_idx = frappe.db.sql(
		"select coalesce(max(idx), 0) from `tabNHK User Device` where parent = %s and parentfield = 'devices'",
		nhk_user,
	)[0][0]
	row = frappe.get_doc({
		"doctype": DEVICE,
		"parent": nhk_user,
		"parenttype": "NHK User",
		"parentfield": "devices",
		"idx": last_idx + 1,
		"token": token,
		"platform": platform,
		"device_name": device_name,
		"enabled": 1,
		"last_seen": last_seen or now_datetime(),
	})
	# Rows of a submitted document carry its docstatus, as a normal save would give them.
	row.docstatus = parent_docstatus
	row.db_insert()
	return row.name


@frappe.whitelist()
def register_device(token, platform=None, device_name=None):
	"""Register the caller's phone. Idempotent; call it on every login and token refresh.

	A token already registered to someone else moves to the caller: the phone
	was handed over or logged in as another user, and the previous user must stop
	getting its notifications.
	"""
	user = _caller()
	token = (token or "").strip()
	if not token or len(token) > MAX_TOKEN_LENGTH:
		frappe.throw(_("That is not a notification token."))
	if platform and platform not in PLATFORMS:
		frappe.throw(_("Platform must be one of {0}.").format(", ".join(PLATFORMS)))

	nhk_user = nhk_user_of(user)
	if not nhk_user:
		frappe.throw(_("{0} has no NHK User record, so this phone cannot get notifications. Ask the office to create one.").format(user))

	mine = None
	for row in _rows_with_token(token):
		if row.parent == nhk_user and not mine:
			mine = row.name
		else:
			frappe.db.delete(DEVICE, {"name": row.name})

	if mine:
		update = {"enabled": 1, "last_seen": now_datetime()}
		if platform:
			update["platform"] = platform
		if device_name:
			update["device_name"] = device_name
		frappe.db.set_value(DEVICE, mine, update, update_modified=False)
	else:
		mine = _add_device_row(nhk_user, token, platform, device_name)

	return {"name": mine, "user": user, "enabled": 1}


@frappe.whitelist()
def unregister_device(token):
	"""Stop notifications to this phone, on logout. Only the caller's own token."""
	user = _caller()
	rows = _rows_with_token((token or "").strip())
	if not rows:
		return {"removed": False}
	if any(r.parent != nhk_user_of(user) for r in rows):
		frappe.throw(_("That device is not registered to you."), frappe.PermissionError)
	for r in rows:
		frappe.db.delete(DEVICE, {"name": r.name})
	return {"removed": True}


def tokens_for(user):
	"""Every enabled token registered to `user`, most recently seen first."""
	nhk_user = nhk_user_of(user)
	if not nhk_user:
		return []
	return frappe.get_all(
		DEVICE,
		filters={"parent": nhk_user, "parenttype": "NHK User", "parentfield": "devices", "enabled": 1},
		pluck="token",
		order_by="last_seen desc",
	)
