from frappe import _
import frappe
import urllib.parse


@frappe.whitelist(allow_guest=True)
def contact_form_data(form_data):
    try:
        parsed_data = urllib.parse.parse_qs(form_data)

        name = parsed_data.get("name", [None])[0]
        email = parsed_data.get("email", [None])[0]
        phone = parsed_data.get("phone", [None])[0]
        message = parsed_data.get("message", [None])[0]
        city = parsed_data.get("city", [None])[0]
        pincode = parsed_data.get("pincode", [None])[0]

        # Mapping logic to determine form type
        if pincode:
            form_type = "Timing Popup"
        elif city:
            form_type = "Get In Touch"
        elif message:
            form_type = "Contact Form"
        else:
            form_type = "Unknown"  # You can handle this case as per your requirement

        # Create and insert the document
        custom_data_doc = frappe.new_doc("Contact Form")
        custom_data_doc.name1 = name
        custom_data_doc.phone = phone
        custom_data_doc.email = email
        custom_data_doc.message = message
        custom_data_doc.city = city
        custom_data_doc.pincode = pincode
        custom_data_doc.form_type = form_type

        custom_data_doc.insert()

        # Return a success response
        return {"status": "success", "message": "Data inserted successfully."}

    except Exception as e:
        # Log the error and return an error response
        frappe.log_error(str(e))
        return {"status": "error", "message": "Error inserting data: " + str(e)}


@frappe.whitelist(allow_guest=True)
def blog_data(form_data):

    try:
        
        name = frappe.form_dict.get("name")
        comment_text = frappe.form_dict.get("comment_text")
      
        parsed_data = urllib.parse.parse_qs(form_data)
       
        name = parsed_data.get("name", [None])[0]
        comment_text = parsed_data.get("comment_text", [None])[0]
        


    

        # Replace "YourCustomDoctype" with the actual name of your Doctype
        blog = frappe.new_doc("Blog Comment")
        blog.blog_id = name
        blog.comment = comment_text
        
        # frappe.msgprint("Form data ==> "+blog)

        # Save the document to persist the changes
        blog.insert()

        return ("Data inserted successfully.")
    except Exception as e:
        frappe.log_error(str(e))
        return "Error inserting data: " + str(e)
    








from frappe.utils import flt
import frappe

def update_technician_charge(doc):
    if not doc.technician_category or not doc.kilometers:
        return

    settings = frappe.get_single("Admin Settings")

    for row in settings.technician_charges_table:
        if (
            row.category == doc.technician_category
            and flt(row.from_distance) <= flt(doc.kilometers) <= flt(row.to_distance)
        ):

            # Type = Pickup
            if doc.type == "Pickup":
                doc.charges = row.pickup

            # Type = Delivery
            elif doc.type == "Delivery":
                doc.charges = row.delivery

            # Any other type defaults to Delivery charge
            else:
                doc.charges = row.delivery

            break