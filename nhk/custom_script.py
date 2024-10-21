import frappe


@frappe.whitelist()
def fetch_asset_id(item_code):
    asset_id = frappe.db.get_value('Asset', {'item_code': item_code}, 'name')
    return asset_id



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



# import frappe,json
# import requests,re

# @frappe.whitelist()
# def cancel_link(p_id=None):
#     if p_id:
#         payment_link = frappe.get_doc('Payment Link Log',p_id)
#         razorpay_api_cancel = frappe.get_doc('Razorpay Api to cancel link')

#         razorpay_api_key = razorpay_api_cancel.razorpay_api_key
#         razorpay_api_secret = razorpay_api_cancel.razorpay_secret
#         razorpay_api_key = razorpay_api_cancel.razorpay_api_key
#         razorpay_api_secret = razorpay_api_cancel.razorpay_secret

#         # Razorpay API endpoint for canceling a payment link
#         api_url = razorpay_api_cancel.razorpay_url
#         new_api_url = api_url.replace("link_id", payment_link.link_id)

#         # # Set up headers with your API key and secret
#         # headers = {
#         #     'Content-Type': 'application/json',
#         #     'Authorization': f'Basic {razorpay_api_key}:{razorpay_api_secret}'
#         # }
#         try:
#             # Make a POST request to cancel the payment link
#             # # response = requests.post(new_api_url, headers=headers)
#             response = requests.post(new_api_url, 
#                                         auth=(razorpay_api_key, razorpay_api_secret))

#             # Check if the request was successful (HTTP status code 200)
#             # client = razorpay.Client(auth=(razorpay_api_key, razorpay_api_secret))
#             # print(client)
#             # response=client.payment_link.cancel(id)

#             # print(self.link_id)
#             # response=client.payment.fetch(self.link_id)
#             response_dict = response.json() 
#             if response.status_code == 200:
#                 payment_link.enabled=0
#                 payment_link.save()
                
#                 sales_order_doc = frappe.get_doc('Sales Order',payment_link.sales_order)
#                 sales_order_doc.custom_razorpay_payment_url=None
#                 sales_order_doc.save()
#                 return "Payment link canceled successfully:"
#             else:
#                 return f"Error canceling payment link. Status code: {response.status_code},{response_dict['error']['description']}"

#         except requests.exceptions.RequestException as e:
#             return "Error in Payment Link Log"









# import frappe

# @frappe.whitelist()
# def update_custom_sales_order_ids():
#     try:
#         # Query to fetch item_code and related sales orders
#         sql_query = """
#             SELECT so_item.item_code, GROUP_CONCAT(so.name) AS sales_order_ids
#             FROM `tabSales Order Item` so_item
#             INNER JOIN `tabSales Order` so ON so.name = so_item.parent
#             WHERE so.docstatus = 1
#             AND so.status = 'Active'
#             AND so_item.item_code IN (
#                 SELECT name
#                 FROM `tabItem`
#                 WHERE device_type = 'Rental'
#             )
#             GROUP BY so_item.item_code
#         """
#         data = frappe.db.sql(sql_query, as_dict=True)

#         # Update Item doctype with Sales Order IDs
#         for item in data:
#             item_doc = frappe.get_doc('Item', item.item_code)
#             item_doc.custom_sales_order_id = item.sales_order_ids
#             item_doc.save()

#         return "Sales Order IDs updated successfully"
#     except Exception as e:
#         frappe.log_error(f"Error in updating Sales Order IDs: {str(e)}")
#         frappe.throw("Error updating Sales Order IDs. Please check logs for details.")



# @frappe.whitelist()
# def check_items_with_multiple_sales_orders():
#     try:
#         # Query to fetch item_code and related sales orders
#         sql_query = """
#             SELECT so_item.item_code, GROUP_CONCAT(so.name) AS sales_order_ids
#             FROM `tabSales Order Item` so_item
#             INNER JOIN `tabSales Order` so ON so.name = so_item.parent
#             WHERE so.docstatus = 1
#             AND so.status = 'Active'
#             AND so_item.item_code IN (
#                 SELECT name
#                 FROM `tabItem`
#                 WHERE device_type = 'Rental'
#             )
#             GROUP BY so_item.item_code
#         """
#         data = frappe.db.sql(sql_query, as_dict=True)

#         # List to store items with multiple sales orders
#         multiple_orders = []

#         # Check for items with multiple sales orders
#         for item in data:
#             # Check if the item has multiple sales orders
#             if ',' in item.sales_order_ids:
#                 multiple_orders.append(f"Item Code: {item.item_code}, Sales Orders: {item.sales_order_ids}")

#         return {
#             "success": True,
#             "multiple_orders": multiple_orders
#         }
#     except Exception as e:
#         frappe.log_error(f"Error in checking Sales Order IDs: {str(e)}")
#         frappe.throw("Error checking Sales Order IDs. Please check logs for details.")



@frappe.whitelist()
def update_custom_sales_order_ids():
    try:
        # Query to fetch item_code and related sales orders
        sql_query = """
            SELECT so_item.item_code, GROUP_CONCAT(so.name) AS sales_order_ids
            FROM `tabSales Order Item` so_item
            INNER JOIN `tabSales Order` so ON so.name = so_item.parent
            WHERE so.docstatus = 1
            AND so.status IN ('Active', 'Partially Closed')
            AND so_item.item_code IN (
                SELECT name
                FROM `tabItem`
                WHERE device_type = 'Rental'
            )
            GROUP BY so_item.item_code
        """
        data = frappe.db.sql(sql_query, as_dict=True)

        for item in data:
            item_doc = frappe.get_doc('Item', item.item_code)
            item_doc.custom_sales_order_id = item.sales_order_ids

            # Retrieve customer from the first Sales Order associated with the item
            first_sales_order = item.sales_order_ids.split(',')[0].strip()  # Get the first sales order
            sales_order_doc = frappe.get_doc('Sales Order', first_sales_order)
            item_doc.customer_n = sales_order_doc.customer

            item_doc.save()

        return {"message": "Sales Order IDs and Customer updated successfully"}
    except Exception as e:
        frappe.log_error(f"Error in updating Sales Order IDs and Customer: {str(e)}")
        return {"message": "Error updating Sales Order IDs and Customer. Please check logs for details."}


@frappe.whitelist()
def check_items_with_multiple_sales_orders():
    try:
        # Query to fetch item_code and related sales orders
        sql_query = """
            SELECT so_item.item_code, GROUP_CONCAT(so.name) AS sales_order_ids
            FROM `tabSales Order Item` so_item
            INNER JOIN `tabSales Order` so ON so.name = so_item.parent
            WHERE so.docstatus = 1
            AND so.status = 'Active'
            AND so_item.item_code IN (
                SELECT name
                FROM `tabItem`
                WHERE device_type = 'Rental'
            )
            GROUP BY so_item.item_code
        """
        data = frappe.db.sql(sql_query, as_dict=True)

        # List to store items with multiple sales orders
        multiple_orders = []

        # Check for items with multiple sales orders
        for item in data:
            if ',' in item.sales_order_ids:
                multiple_orders.append(f"Item Code: {item.item_code}, Sales Orders: {item.sales_order_ids}")

        return {
            "success": True,
            "multiple_orders": multiple_orders
        }
    except Exception as e:
        frappe.log_error(f"Error in checking Sales Order IDs: {str(e)}")
        return {
            "success": False,
            "message": "Error checking Sales Order IDs. Please check logs for details."
        }




@frappe.whitelist()
def get_serial_numbers(item_code):
    serial_numbers = frappe.get_all("Serial No", filters={"item_code": item_code}, fields=["name", "status","purchase_document_no"])
    return serial_numbers



@frappe.whitelist()
def get_sales_orders(item_code):
    sales_orders = frappe.db.sql("""
        SELECT 
            soi.parent, soi.qty, soi.rate, soi.amount, soi.child_status, so.status AS parent_status
        FROM 
            `tabSales Order Item` soi
        JOIN 
            `tabSales Order` so ON soi.parent = so.name
        WHERE 
            soi.item_code = %s
    """, (item_code), as_dict=True)
    return sales_orders

@frappe.whitelist()
def get_delivery_notes(item_code):
    delivery_notes = frappe.get_all("Delivery Note Item", filters={"item_code": item_code}, fields=["parent", "qty", "rate", "amount"])
    return delivery_notes







# Assuming 'status' is a linked field to 'Sales Order'
@frappe.whitelist()
def check_rented_out_items():
    rented_items = []

    # Query Sales Order Items for items with status 'Active'
    sales_order_items = frappe.db.sql("""
        SELECT
            so_item.item_code,
            so.status as item_status
        FROM
            `tabSales Order Item` so_item
        LEFT JOIN `tabSales Order` so ON so_item.parent = so.name
        WHERE
            so_item.docstatus = 1  # Considering only submitted Sales Orders
            AND so.status != 'Active'  # Adjust this condition based on how status is stored
    """, as_dict=True)

    if sales_order_items:
        for item in sales_order_items:
            rented_items.append(f"{item.item_code} - {item.item_status}")

        return {
            'success': True,
            'rented_items': rented_items
        }
    else:
        return {
            'success': False,
            'message': 'No rented out items with status \'Active\' found.'
        }


@frappe.whitelist()
def get_sales_order_info(customer):
    # SQL query to get the total due amount for active sales orders
    due_amount_query = """
        SELECT SUM(so.balance_amount) AS total_due
        FROM `tabSales Order` so
        WHERE so.customer = %s AND so.status IN ('Active', 'Approved' , 'Rental Device Assigned', 'Ready for Delivery', 'DISPATCHED','DELIVERED','Ready for Pickup','Picked Up', 'Partially Closed' , 'Order' ) AND so.docstatus = 1
    """
    due_amount = frappe.db.sql(due_amount_query, (customer,), as_dict=True)[0].total_due or 0
    
    # SQL query to get the refundable security deposit
    refundable_sd_query = """
        SELECT SUM(refundable_security_deposit) AS total_refundable_sd
        FROM `tabSales Order`
        WHERE customer = %s AND status IN ('Active', 'Approved' , 'Rental Device Assigned', 'Ready for Delivery', 'DISPATCHED','DELIVERED','Ready for Pickup','Picked Up', 'Partially Closed' , 'Order' ) AND docstatus = 1
    """
    refundable_sd = frappe.db.sql(refundable_sd_query, (customer,), as_dict=True)[0].total_refundable_sd or 0
    
    # SQL query to get active sales orders details with start_date, end_date, and payment_status
    sales_orders_query = """
        SELECT so.name AS sales_order, so.transaction_date, so.grand_total, so.start_date, so.end_date, so.payment_status, so.order_type, so.status
        FROM `tabSales Order` so
        WHERE so.customer = %s AND so.status IN ('Active', 'Approved' , 'Rental Device Assigned', 'Ready for Delivery', 'DISPATCHED','DELIVERED','Ready for Pickup','Picked Up', 'Partially Closed' , 'Order' ) AND so.docstatus = 1
    """
    sales_orders = frappe.db.sql(sales_orders_query, (customer,), as_dict=True)
    
    return {
        'total_due_amount': due_amount,
        'refundable_sd': refundable_sd,
        'sales_orders': sales_orders
    }



import frappe

# @frappe.whitelist()
# def get_sales_order_details(sales_order_id):
#     """
#     Fetch details of the specified sales order.
    
#     :param sales_order_id: The name or ID of the sales order to fetch.
#     :return: A dictionary containing the sales order details.
#     """
#     sales_order = frappe.get_doc('Sales Order', sales_order_id)

#     # Prepare the response dictionary with required fields
#     response = {
#         "sales_order_id": sales_order.name,
#         "customer": sales_order.customer,
#         "customer_mobile_no": sales_order.customer_mobile_no,
#         "customer_email_id": sales_order.customer_email_id,
#         "permanent_address": sales_order.permanent_address,
#         "balance_amount": sales_order.balance_amount,
#         "outstanding_security_deposit_amount": sales_order.outstanding_security_deposit_amount,
#         "payment_status": sales_order.payment_status,
#         "status": sales_order.status,
#         "master_order_id":sales_order.master_order_id,
#         "security_deposit_status":sales_order.security_deposit_status,
#         "items": []
#     }

#     # Fetch the items from the sales order
#     for item in sales_order.items:
#         response["items"].append({
#             "item_code": item.item_code,
#             "item_name": item.item_name
#         })

#     return response



import frappe

@frappe.whitelist()
def get_sales_order_details(sales_order_id):
    # Fetch Sales Order details
    sales_order = frappe.get_doc("Sales Order", sales_order_id)

    # Fetch items from the Sales Order
    items = [{"item_code": item.item_code, "item_name": item.item_name, "name":item.name,"child_status":item.child_status} for item in sales_order.items]
    # Helper function to map docstatus to status text
    def get_status_text(docstatus):
        if docstatus == 0:
            return "Draft"
        elif docstatus == 1:
            return "Submitted"
        elif docstatus == 2:
            return "Cancelled"
        return "Unknown"
    # Fetch Payment Entries related to this Sales Order
    payment_entries = frappe.db.sql("""
        SELECT 
            name, posting_date, paid_amount AS amount,docstatus
        FROM 
            `tabPayment Entry`
        WHERE 
            sales_order_id = %s AND docstatus IN (0, 1)
    """, (sales_order_id,), as_dict=True)


    for payment in payment_entries:
        payment["status"] = get_status_text(payment.get("docstatus"))

    # Fetch Journal Entries related to this Sales Order
    journal_entries = frappe.db.sql("""
        SELECT 
            name, posting_date, total_debit AS amount, docstatus
        FROM 
            `tabJournal Entry`
        WHERE 
            sales_order_id = %s AND docstatus IN (0, 1) AND security_deposite_type = 'SD Amount Received From Client'
    """, (sales_order_id,), as_dict=True)

    for journal in journal_entries:
        journal["status"] = get_status_text(journal.get("docstatus"))

     # Calculate total paid amount from Payment Entries (including draft and submitted)
    total_paid_rental = sum(payment["amount"] for payment in payment_entries if payment.get("docstatus") in [0, 1])

    # Calculate total security deposit paid (including draft and submitted)
    total_paid_security_deposit = sum(journal["amount"] for journal in journal_entries if journal.get("docstatus") in [0, 1])
    # Calculate unpaid amounts
    unpaid_rental_amount = max(sales_order.rounded_total - total_paid_rental, 0)
    unpaid_security_deposit_amount = max(float(sales_order.security_deposit) - total_paid_security_deposit, 0)

    # Calculate Rental Payment Status
    if total_paid_rental >= sales_order.rounded_total:
        rental_payment_status = "Fully Paid"
    elif total_paid_rental > 0:
        rental_payment_status = "Partially Paid"
    else:
        rental_payment_status = "Unpaid"

    # Calculate Security Deposit Payment Status
    if total_paid_security_deposit >= float(sales_order.security_deposit):
        security_deposit_payment_status = "Fully Paid"
    elif total_paid_security_deposit > 0:
        security_deposit_payment_status = "Partially Paid"
    else:
        security_deposit_payment_status = "Unpaid"
    # Prepare response data
    response = {
         "sales_order_id": sales_order.name,
        "customer": sales_order.customer,
        "customer_mobile_no": sales_order.customer_mobile_no,
        "customer_email_id": sales_order.customer_email_id,
        "permanent_address": sales_order.permanent_address,
        "balance_amount": sales_order.balance_amount,
        "outstanding_security_deposit_amount": sales_order.outstanding_security_deposit_amount,
        "payment_status": sales_order.payment_status,
        "status": sales_order.status,
        "master_order_id":sales_order.master_order_id,
        "security_deposit_status":sales_order.security_deposit_status,
        "items": items,
        "payment_entries": payment_entries,
        "journal_entries": journal_entries,
        "rental_payment_status": rental_payment_status,
        "security_deposit_payment_status": security_deposit_payment_status,
        "paid_rental_amount": total_paid_rental,
        "unpaid_rental_amount": unpaid_rental_amount,
        "unpaid_security_deposit_amount":unpaid_security_deposit_amount,
        "paid_security_deposit_amount":total_paid_security_deposit
        
    }

    return response


import frappe
from frappe import _

@frappe.whitelist()
def submit_entry(entry_name, doctype):
    """Submit a Payment Entry or Journal Entry."""
    # Validate the doctype
    if doctype not in ["Payment Entry", "Journal Entry"]:
        frappe.throw(_("Invalid doctype"))

    # Get the document by name
    doc = frappe.get_doc(doctype, entry_name)

    # Check if the document is in draft status
    if doc.docstatus != 0:
        frappe.throw(_("Only draft entries can be submitted"))

    try:
        # Submit the document
        doc.submit()
        return {
            "status": "success",
            "message": _("Entry submitted successfully!")
        }
    except Exception as e:
        frappe.throw(_("Error submitting entry: {0}").format(str(e)))


import frappe
from frappe import _

@frappe.whitelist()
def change_status(docname, new_status):
    """Change the status of a document to the new status provided."""
    
    # Replace 'Technician Portal' with the actual DocType name you are working with
    doc = frappe.get_doc("Technician Visit Entry", docname)

    # Check the current status and validate the transition
    if doc.status == "Assigned" and new_status == "Delivered":
        # Allow changing from Assigned to Delivered
        pass
    elif doc.status == "Assigned" and new_status == "Picked up":
        # Allow changing from Assigned to Delivered
        pass
    elif doc.status == "Delivered" and new_status == "Amount Settled":
        # Allow changing from Delivered to Amount Settled
        # Add additional checks for kilometers and charges if necessary
        if not doc.kilometers or not doc.charges:
            frappe.throw(_("Please fill in kilometers and charges before settling the amount."))
    elif doc.status == "Picked up" and new_status == "Amount Settled":
        # Allow changing from Picked up to Amount Settled
        if not doc.kilometers or not doc.charges:
            frappe.throw(_("Please fill in kilometers and charges before settling the amount."))
        doc.payment_status = 'Cleared'
    elif doc.status == "Amount Settled" and new_status == "Closed":
        # Allow changing from Picked up to Amount Settled
        if not doc.kilometers or not doc.charges:
            frappe.throw(_("Please fill in kilometers and charges before settling the amount."))
    else:
        frappe.throw(_("Invalid status change from '{0}' to '{1}'.".format(doc.status, new_status)))

    # Change the status
    doc.status = new_status

    # Save the document
    try:
        doc.save()
        frappe.db.commit()  # Commit the changes to the database
    except Exception as e:
        frappe.throw(_("Error while changing status: {0}").format(str(e)))

    # Return success message
    return _("Status changed to '{0}' successfully!".format(new_status))
