# Copyright (c) 2024, vishnu and contributors
# For license information, please see license.txt

import frappe

def get_context(context):
    # Fetch blog entries from the database
    # blogs = frappe.get_all("Blog", filters={}, fields=["image", "date", "title", "description", "author"])
    blogs = frappe.get_all("Blog", filters={}, fields=["name","image", "date", "title", "description", "author"])
    # Pass the blog entries to the Jinja context
    context.index = blogs
