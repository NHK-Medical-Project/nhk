import frappe


@frappe.whitelist()
def fetch_asset_id(item_code):
    asset_id = frappe.db.get_value('Asset', {'item_code': item_code}, 'name')
    return asset_id


# Import frappe
import frappe

# Your custom Python method
# Import frappe
import frappe

# Your custom Python method
@frappe.whitelist()
def append_service_history(docname,attachment, vendor_link, date, amount):
    try:
        # Get the Item document
        item_doc = frappe.get_doc('Item', docname)
        
        # Append values to the child table
        service_history = item_doc.append('service_history', {})
        service_history.vendor = vendor_link
        service_history.date = date
        service_history.amount = amount
        service_history.attachment = attachment
        
        # Update status to "Service"
        item_doc.status = "Under Service"
        
        # Save the changes
        item_doc.save()
        
        # Return success message
        return {'status': 'success', 'message': 'Service history added successfully.'}
    except Exception as e:
        # Return error message
        return {'status': 'error', 'message': str(e)}
