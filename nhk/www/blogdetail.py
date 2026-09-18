import frappe
from datetime import datetime

def get_context(context):
    # Assuming you have a parameter 'title' in your URL
    blog_title = frappe.form_dict.get("id")
 
    # Fetch blog detail from the database or wherever it's stored
    blog_detail = frappe.get_doc("Blog", {"name": blog_title})  # Adjust the query based on your data structure
 
    # Pass the blog detail to the Jinja context
    context.blog_detail = blog_detail
 
    # Fetch blog entries from the database
    blogs = frappe.get_all("Blog", filters={}, fields=["name","image", "date", "title", "content", "description", "author"])
 
    # Preprocess dates for blog detail and blog list
    for blog in blogs:
        blog['formatted_date'] = blog['date'].strftime("%d-%m-%Y")
    context.blogsdetail = blogs