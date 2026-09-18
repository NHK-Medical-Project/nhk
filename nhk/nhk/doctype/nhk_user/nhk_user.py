# Copyright (c) 2024, vishnu and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import json

class NHKUser(Document):
    def on_submit(self):
        existing_core_user = frappe.get_all("User", filters={"email": self.email})
        role_profile_names = [role_profile.role_profile for role_profile in self.role]

        if not existing_core_user:
            # Create a new core user if it doesn't exist
            core_user = frappe.get_doc({
                "doctype": "User",
                "email": self.email,
                # "full_name": self.full_name,
                "first_name": self.first_name,
                "last_name": self.last_name,
                "middle_name": self.middle_name,
                "gender": self.gender,
                "enabled": self.enabled,
                "birth_date": self.date_of_birth,
                "send_welcome_email": self.send_welcome_email,
                "mobile_no": self.mobile_no,
                "new_password": self.password,
                "module_profile": "No Module",
            })

            # Add each role profile to the core user's role_profiles field
            for role_profile in role_profile_names:
                core_user.append("role_profiles", {
                    "role_profile": role_profile
                })
                
            core_user.insert()

            # Once user creation is successful, create Employee record
            create_employee_from_user(core_user)
            if "NHK Sales" in role_profile_names:
                create_sales_person(core_user)

        return

    def before_save(self):
        name_list=[self.first_name,self.middle_name,self.last_name]
        name_list = [value for value in name_list if value is not None]
        self.full_name=" ".join(name_list)

    def before_update_after_submit(self):
        # Extract role profile names from UserRoleProfile objects
        role_profile_names = [role_profile.role_profile for role_profile in self.role]
        frappe.logger().info(f"Role Profiles: {role_profile_names}")

        # Update core user information on NHK User update
        core_users = frappe.get_all("User", filters={"email": self.email}, fields=["name"])
        frappe.logger().info(f"Core Users: {core_users}")

        if core_users:
            core_user = frappe.get_doc("User", core_users[0].name)
            frappe.logger().info(f"Core User before update: {core_user.as_dict()}")

            core_user.update({
                "full_name": self.full_name,
                "first_name": self.first_name,
                "last_name": self.last_name,
                "middle_name": self.middle_name,
                "gender": self.gender,
                "enabled": self.enabled,
                "birth_date": self.date_of_birth,
                "send_welcome_email": self.send_welcome_email,
                "mobile_no": self.mobile_no
            })

            # Update password if not "NULL"
            frappe.logger().info(f"Password Update: {self.password}")
            if self.password != "NULL":
                core_user.new_password = self.password

            # Assign role profiles to the core user
            core_user.set("role_profiles", [])
            for role_profile_name in role_profile_names:
                core_user.append("role_profiles", {
                    "role_profile": role_profile_name
                })
            frappe.logger().info(f"Assigned Role Profiles: {core_user.role_profiles}")

            if "NHK Sales" in role_profile_names:
                frappe.logger().info(f"Creating Sales Person for: {core_user.name}")
                create_sales_person(core_user)
            else:
                employee_id = frappe.get_value("Employee", {"user_id": self.email}, "name")
                frappe.logger().info(f"Deleting Sales Person for Employee ID: {employee_id}")
                delete_sales_person(employee_id)

            core_user.save()
            frappe.logger().info(f"Core User saved: {core_user.name}")



    def on_trash(self):
        # Handle user deletion
        user = frappe.get_all("User", filters={"email": self.email})
        employee_id = frappe.get_value("Employee", {"user_id": self.email}, "name")

        if user:
            delete_sales_person(employee_id)
            # Also, delete the associated Employee record if it exists
            delete_employee_from_user(user[0].name)
            # pass  # Uncomment the next line if you want to delete the associated core user
            frappe.delete_doc("User", user[0].name)
            
           


def create_sales_person(user):
    # Get the Employee ID of the newly created employee
    employee_id = frappe.get_value("Employee", {"user_id": user.name}, "name")
    # Check if the user already has a Sales Person record
    existing_sales_person = frappe.get_all("Sales Person", filters={"employee": employee_id})
    if existing_sales_person:
        return  # Sales Person record already exists for the user
    
    # Create a new Sales Person record
    sales_person = frappe.get_doc({
        "doctype": "Sales Person",
        "sales_person_name": user.full_name,
        # "user_id": user.name,
        "employee": employee_id
        # Add other relevant fields
    })
    sales_person.insert()



def create_employee_from_user(user):
    employee = frappe.get_doc({
        "doctype": "Employee",
        "first_name": user.first_name,
        "middle_name": user.middle_name,    
        "last_name":user.last_name,
        "user_id": user.name,
        "create_user_permission":0,
        "expense_approver":"ashutosh.kumawat@nhkmedical.com",
        "create_user_permission":1
        # Add other relevant fields from user or other sources
    })
    employee.insert()


def delete_employee_from_user(user_id):
    # Find the Employee record associated with the given user_id
    employee = frappe.get_all("Employee", filters={"user_id": user_id})
    if employee:
        # Delete the Employee record
        frappe.delete_doc("Employee", employee[0].name)



def delete_sales_person(employee_id):
    # Assuming the sales person record is linked to the Employee record
    sales_person = frappe.get_all("Sales Person", filters={"employee": employee_id})
    if sales_person:
        frappe.delete_doc("Sales Person", sales_person[0].name)

@frappe.whitelist()
def user_to_nhkuser():
    # Sync core user data to NHK User
    core_users = frappe.get_all("User", fields=["name", "email", "full_name", "first_name", "last_name",
                                                "middle_name", "gender", "enabled", "birth_date", 
                                                "send_welcome_email", "mobile_no", "new_password"])

    for core_user in core_users:
        if core_user.first_name in ["Guest", "Administrator", "Account", "Pankaj"]:
            continue

        # Fetching role profiles for the current user
        role_profiles = frappe.get_all("User Role Profile", filters={"parent": core_user.name},
                                       fields=["role_profile"])
        role_profile_names = [role["role_profile"] for role in role_profiles]
        
        lsa_user = frappe.get_all("NHK User", filters={"email": core_user.email}, fields=["name"])
        
        if any(core_user.email == user_info['name'] for user_info in lsa_user):
            continue
        elif lsa_user:
            # Update existing NHK User
            existing_lsa_user = frappe.get_doc("NHK User", lsa_user[0].name)
            existing_lsa_user.update({
                "full_name": core_user.full_name,
                "first_name": core_user.first_name,
                "last_name": core_user.last_name,
                "middle_name": core_user.middle_name,
                "gender": core_user.gender,
                "enabled": core_user.enabled,
                "date_of_birth": core_user.birth_date,
                "send_welcome_email": core_user.send_welcome_email,
                "mobile_no": core_user.mobile_no,
                "role": [{"role_profile": role_profile} for role_profile in role_profile_names]
            })
            existing_lsa_user.save()
        else:
            # Create a new NHK User if it doesn't exist
            new_lsa_user = frappe.new_doc("NHK User")
            new_lsa_user.update({
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
                "role": [{"role_profile": role_profile} for role_profile in role_profile_names]
            })
            new_lsa_user.insert()
            new_lsa_user.submit()
    return {"status": "Users Synced"}


# @frappe.whitelist()
# def get_all_nhk_roles():
#     # Fetch all LSA roles
#     roles = frappe.get_all("Role", filters={"name": ("not in", frappe.permissions.AUTOMATIC_ROLES),
#                                              "disabled": 0, "nhk_roles": 1}, order_by="name")
#     roles = [role.get("name") for role in roles]
#     return {"roles": roles}

# @frappe.whitelist()
# def get_nhk_roles_and_core_user_roles(u_id):
#     try:
#         # Fetch LSA roles and roles assigned to the core user
#         nhk_roles = get_all_nhk_roles()["roles"]
#         core_user_roles = frappe.get_doc('User', u_id).get('roles')
#         return {'nhk_roles': nhk_roles, 'core_user_roles': core_user_roles}
#     except Exception as e:
#         frappe.log_error(frappe.get_traceback(), _('Failed to fetch roles'))
#         return None


# @frappe.whitelist()
# def update_core_user_roles(u_id, roles):
#     try:
#         # Update core user roles
#         roles = json.loads(roles)
#         core_user = frappe.get_doc('User', u_id)
#         core_user.roles = []
#         core_user.add_roles(*roles)
#         core_user.save()
#         return True
#     except Exception as e:
#         frappe.log_error(frappe.get_traceback(), _('Core User Roles Update Failed'))
#         return False
