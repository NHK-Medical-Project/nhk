import frappe
from frappe import _

no_cache = 1
no_sitemap = 1

# The deck describes the system's weak points in detail (core modifications, plaintext
# credentials, the gap list), so it is staff-only. Website customers get a Frappe User
# too, which is why "any logged-in user" is not good enough. Widen this list if the
# office needs it.
ALLOWED_ROLES = ("System Manager", "NHK Admin")


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.throw(_("Please sign in to view the system documentation."), frappe.PermissionError)

	if not set(ALLOWED_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("You are not permitted to view the system documentation."), frappe.PermissionError)

	context.no_cache = 1
	return context
