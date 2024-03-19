import frappe
from datetime import datetime
 
def get_context(context):
    # Fetch blog entries from the database
    blogs = frappe.get_all("Blog", filters={}, fields=["name","image", "date", "title", "description", "author"])
 
    # Preprocess dates
    for blog in blogs:
        date_str = blog['date'].isoformat()  # Convert datetime.date to string
        blog['formatted_date'] = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d-%m-%Y")
 
    # Pass the blog entries to the Jinja context for both banner and popular topics
    context.blog_details = blogs
    context.blogs = blogs