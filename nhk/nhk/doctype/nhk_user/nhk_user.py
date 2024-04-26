# Copyright (c) 2024, vishnu and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import json

class NHKUser(Document):
    def on_submit(self):
        # Check if a core user with the same email exists
        existing_core_user = frappe.get_all("User", filters={"email": self.email})
        if not existing_core_user:
            # Create a new core user if it doesn't exist
            core_user = frappe.get_doc({
                "doctype": "User",
                "email": self.email,
                "full_name": self.full_name,
                "first_name": self.first_name,
                "last_name": self.last_name,
                "middle_name": self.middle_name,
                "gender": self.gender,
                "enabled": self.enabled,
                "birth_date": self.date_of_birth,
                "send_welcome_email": self.send_welcome_email,
                "mobile_no": self.mobile_no,
                "new_password": self.password,
                "module_profile":"No Module"
            })
            core_user.insert()
            return
        return

    def before_update_after_submit(self):
        # Update core user information on LSAUser update
        core_users = frappe.get_all("User", filters={"email": self.email}, fields=["name"])
        if core_users:
            core_user = frappe.get_doc("User", core_users[0].name)
            core_user.full_name = self.full_name
            core_user.first_name = self.first_name
            core_user.last_name = self.last_name
            core_user.middle_name = self.middle_name
            core_user.gender = self.gender
            core_user.enabled = self.enabled
            core_user.birth_date = self.date_of_birth
            core_user.send_welcome_email = self.send_welcome_email
            core_user.mobile_no = self.mobile_no
            if self.password != "NULL":
                core_user.new_password = self.password
            core_user.save()
            return
        return

    def on_trash(self):
        # Handle user deletion
        user = frappe.get_all("User", filters={"email": self.email})
        if user:
            # pass  # Uncomment the next line if you want to delete the associated core user
            frappe.delete_doc("User", user[0].name)


@frappe.whitelist()
def user_to_nhkuser():
    # Sync core user data to LSAUser
    core_users = frappe.get_all("User", fields=["name", "email", "full_name", "first_name", "last_name",
                                                "middle_name", "gender", "enabled", "birth_date", "send_welcome_email",
                                                "mobile_no", "new_password"])
    for core_user in core_users:
        lsa_user = frappe.get_all("NHK User", filters={"email": core_user.email})
        if core_user.first_name in ["Guest","Administrator","Account"]:
            continue
        elif lsa_user:
            # Update existing LSAUser
            existing_lsa_user = frappe.get_doc("NHK User", lsa_user[0].name)
            existing_lsa_user.full_name = core_user.full_name
            existing_lsa_user.first_name = core_user.first_name
            existing_lsa_user.last_name = core_user.last_name
            existing_lsa_user.middle_name = core_user.middle_name
            existing_lsa_user.gender = core_user.gender
            existing_lsa_user.enabled = core_user.enabled
            existing_lsa_user.date_of_birth = core_user.birth_date
            existing_lsa_user.send_welcome_email = core_user.send_welcome_email
            existing_lsa_user.mobile_no = core_user.mobile_no
            existing_lsa_user.save()
        else:
            # Create a new LSAUser if it doesn't exist
            new_lsa_user_fields = {
                "doctype": "NHK User",
                "email": core_user.email,
                "full_name": core_user.full_name,
                "first_name": core_user.first_name,
                "last_name": core_user.last_name,
                "middle_name": core_user.middle_name,
                "gender": core_user.gender,
                "enabled": core_user.enabled,
                "date_of_birth": core_user.birth_date,
                "send_welcome_email": core_user.send_welcome_email,
                "mobile_no": core_user.mobile_no,
                "password": "NULL",
                "lsa_ops_manager": 1,
            }
            new_lsa_user = frappe.get_doc(new_lsa_user_fields)
            new_lsa_user.insert()
            new_lsa_user.submit()
    return {"status": "Users Synced"}

@frappe.whitelist()
def get_all_nhk_roles():
    # Fetch all LSA roles
    roles = frappe.get_all("Role", filters={"name": ("not in", frappe.permissions.AUTOMATIC_ROLES),
                                             "disabled": 0, "nhk_roles": 1}, order_by="name")
    roles = [role.get("name") for role in roles]
    return {"roles": roles}

@frappe.whitelist()
def get_nhk_roles_and_core_user_roles(u_id):
    try:
        # Fetch LSA roles and roles assigned to the core user
        nhk_roles = get_all_nhk_roles()["roles"]
        core_user_roles = frappe.get_doc('User', u_id).get('roles')
        return {'nhk_roles': nhk_roles, 'core_user_roles': core_user_roles}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), _('Failed to fetch roles'))
        return None


@frappe.whitelist()
def update_core_user_roles(u_id, roles):
    try:
        # Update core user roles
        roles = json.loads(roles)
        core_user = frappe.get_doc('User', u_id)
        core_user.roles = []
        core_user.add_roles(*roles)
        core_user.save()
        return True
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), _('Core User Roles Update Failed'))
        return False
