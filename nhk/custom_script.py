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
        doc.technician_update_datetime = frappe.utils.now()
    elif doc.status == "Assigned" and new_status == "Picked up":
        # Allow changing from Assigned to Delivered

        doc.technician_update_datetime = frappe.utils.now()
    elif doc.status == "Assigned" and new_status == "Service Done":
        # Allow changing from Assigned to Delivered

        doc.technician_update_datetime = frappe.utils.now()
    elif doc.status == "Delivered" and new_status == "Amount Settled":
        # Allow changing from Delivered to Amount Settled
        # Add additional checks for kilometers and charges if necessary
        if not doc.kilometers or not doc.charges:
            frappe.throw(_("Please fill in kilometers and charges before settling the amount."))
        # create_payment_entry_for_settlement(doc,doc.technician_id,doc.technician_user_id, doc.charges,mode_of_payment,account,reference_no,reference_date)

        # update_technician_amount(doc.technician_id, doc.charges)   
        # doc.payment_status = 'Cleared'
    elif doc.status == "Picked up" and new_status == "Incentive Finalize":
        # Allow changing from Picked up to Amount Settled
        if not doc.kilometers or not doc.charges or not doc.incentive_amount_to_be_processed:
            frappe.throw(_("Please fill in kilometers and charges before settling the amount."))
    elif doc.status == "Delivered" and new_status == "Incentive Finalize":
        # Allow changing from Picked up to Amount Settled
        if not doc.kilometers or not doc.charges or not doc.incentive_amount_to_be_processed:
            frappe.throw(_("Please fill in kilometers and charges before settling the amount."))
        # create_payment_entry_for_settlement(doc,doc.technician_id,doc.technician_user_id, doc.charges,mode_of_payment,account,reference_no,reference_date)

        # update_technician_amount(doc.technician_id, doc.charges)   
        # doc.payment_status = 'Cleared'
    elif doc.status == "Service Done" and new_status == "Incentive Finalize":
        # Allow changing from Picked up to Amount Settled
        if not doc.kilometers or not doc.charges or not doc.incentive_amount_to_be_processed:
            frappe.throw(_("Please fill in kilometers and charges before settling the amount."))
    elif doc.status == "Picked up" and new_status == "Amount Settled":
        # Allow changing from Picked up to Amount Settled
        if not doc.kilometers or not doc.charges:
            frappe.throw(_("Please fill in kilometers and charges before settling the amount."))
        # create_payment_entry_for_settlement(doc,doc.technician_id,doc.technician_user_id, doc.charges,mode_of_payment,account,reference_no,reference_date)

        # update_technician_amount(doc.technician_id, doc.charges)   
        # doc.payment_status = 'Cleared'
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




def update_technician_amount(technician_id, amount):
    """Update the technician's total amount in Technician Details."""
    try:
        technician_doc = frappe.get_doc("Technician Details", technician_id)
        
        # Add the amount to the technician's balance (or another field)
        technician_doc.total_amount_settled += amount
        
        # Save the technician document
        technician_doc.save()
        frappe.db.commit()
    except Exception as e:
        frappe.throw(_("Failed to update technician amount: {0}").format(str(e)))
def create_payment_entry_for_settlement(doc, technician_id, technician_user_id, charges,mode_of_payment,account,reference_no,reference_date):
    """Create a payment entry for amount settlement."""

    # Fetch the employee details based on the technician's user ID
    employee = frappe.get_all("Employee", filters={"user_id": technician_user_id}, fields=["name", "employee"])

    if not employee:
        frappe.throw(_("No Employee found for Technician User ID: {0}").format(technician_user_id))
    
    employee_id = employee[0].employee  # Get the employee ID

    # Fetch the company from the Technician Visit Entry document

    # Create a new Payment Entry document
    payment_entry = frappe.new_doc("Payment Entry")
    payment_entry.payment_type = "Pay"
    payment_entry.posting_date = frappe.utils.nowdate()
    payment_entry.party_type = "Employee"
    payment_entry.party = employee_id  # Set to the employee ID
    payment_entry.custom_from_technician_protal = 1  # Custom field for technician portal
    payment_entry.custom_technician_id = technician_id  # Custom field for technician name
    payment_entry.mode_of_payment = mode_of_payment  # Custom field for technician name

    # Account paid from (typically an expense account or cash account)
    payment_entry.paid_from = account  # Replace with the correct expense account
    payment_entry.paid_amount = charges
    payment_entry.received_amount = charges
    payment_entry.paid_to = "Creditors - INR"  # Replace with the correct cash or bank account
    payment_entry.reference_no = reference_no
    payment_entry.reference_date = reference_date
    # Set the exchange rate and account currency fields
    payment_entry.source_exchange_rate = 1.0  
    payment_entry.paid_from_account_currency = "INR"  
    payment_entry.paid_to_account_currency = "INR"    

    # Set the company for the payment entry
    # payment_entry.company = company

    # # Append the reference to the Payment Entry
    # reference_entry = payment_entry.append("references")
    # reference_entry.reference_doctype = doc.doctype
    # reference_entry.reference_name = doc.name
    # reference_entry.allocated_amount = charges
    # reference_entry.total_amount = charges
    # reference_entry.outstanding_amount = charges

    # Debug: Print the payment entry details before inserting
    # print("Payment Entry Details: ", payment_entry.as_dict())  # Use as_dict() to print the full object state

    # Save the payment entry
    try:
        payment_entry.insert(ignore_permissions=True)  # Use ignore_permissions if necessary
        payment_entry.submit()
        frappe.msgprint(_("Payment Entry created for Amount Settlement."))
    except Exception as e:
        error_message = _("Error creating Payment Entry: {0}. Payment Entry Details: {1}").format(str(e), str(payment_entry))
        frappe.throw(error_message)



@frappe.whitelist()
def update_shares(doctype, docname, technician_user_id):
    # Remove existing shares
    shares = frappe.get_all('DocShare', filters={'share_doctype': doctype, 'share_name': docname}, fields=['name', 'user'])
    for share in shares:
        frappe.share.remove(doctype, docname, share.user)
    
    # Add new share for technician_user_id
    frappe.share.add(doctype, docname, technician_user_id, read=1, write=1)

    return True




import frappe

@frappe.whitelist()
def get_uncleared_technician_records(technician_id, start_date=None, end_date=None):
    # Validate technician_id
    if not technician_id:
        frappe.throw("Technician ID is required.")
    
    # Prepare filters
    filters = {
        'technician_id': technician_id,
        'status': 'Incentive Finalize'
    }

    # If both start_date and end_date are provided, add them to the filters
    if start_date and end_date:
        filters.update({
            'technician_update_datetime': ['between', [start_date, end_date]]  # Filter by datetime range
        })

    # Fetch technician visit entries based on filters
    entries = frappe.get_all(
        'Technician Visit Entry',
        filters=filters,
        fields=['name']  # Replace with actual fields needed
    )

    # print('Fetched Entriesssssssssssssssssssssssssssssssss:', entries)  # Debugging log
    return entries

@frappe.whitelist()
def create_payment_entry(technician_visit_payment_id, total_amount, technician_id, technician_user_id, mode_of_payment, payment_account, reference_no=None, reference_date=None):
    # Ensure valid input and convert total_amount to a float
    try:
        total_amount = float(total_amount)
        if total_amount <= 0:
            return {"success": False, "message": "Total amount must be greater than zero."}
    except ValueError:
        return {"success": False, "message": "Invalid total amount. Please ensure it is a valid number."}

    if not technician_id:
        return {"success": False, "message": "Technician ID is required."}

    # Fetch the employee details based on the technician's user ID
    employee = frappe.get_all("Employee", filters={"user_id": technician_user_id}, fields=["name", "employee"])
    if not employee:
        frappe.throw(_("No Employee found for Technician User ID: {0}").format(technician_user_id))
    
    employee_id = employee[0].employee  # Get the employee ID

    # Create a new Payment Entry document
    payment_entry = frappe.new_doc("Payment Entry")
    payment_entry.payment_type = "Pay"
    payment_entry.posting_date = frappe.utils.nowdate()
    payment_entry.party_type = "Employee"
    payment_entry.party = employee_id  # Set to the employee ID
    payment_entry.custom_from_technician_protal = 1  # Custom field for technician portal
    payment_entry.custom_technician_id = technician_id  # Custom field for technician name
    payment_entry.mode_of_payment = mode_of_payment  # Set mode of payment
    payment_entry.custom_technician_visit_payment_id = technician_visit_payment_id
    payment_entry.paid_from = payment_account  # Set payment account
    payment_entry.paid_amount = total_amount
    payment_entry.received_amount = total_amount
    payment_entry.paid_to = "Creditors - INR"
    payment_entry.reference_no = reference_no
    payment_entry.reference_date = reference_date

    # Save the payment entry
    try:
        payment_entry.insert(ignore_permissions=True)  # Insert the payment entry
        payment_entry.submit()

        # Fetch all technician_visit_ids from the payments child table in Technician Visit Payment
        technician_visit_payment_doc = frappe.get_doc("Technician Visit Payment", technician_visit_payment_id)
        if technician_visit_payment_doc.payments:
            for payment in technician_visit_payment_doc.payments:
                visit_id = payment.technician_visit_id
                # Update status and payment_status in Technician Visit entries
                update_technician_visit_entry(visit_id, "Amount Settled", "Cleared")

        # After successfully updating the technician visit entries, update payment_done in Technician Visit Payment
        technician_visit_payment_doc.payment_done = 1
        technician_visit_payment_doc.payment_entry_id = payment_entry.name
        technician_visit_payment_doc.save()

        technician_details = frappe.get_doc('Technician Details',technician_id)
        technician_details.total_amount_settled += total_amount
        technician_details.save()
        frappe.db.commit()

        frappe.msgprint(_("Payment Entry created, Technician Visit updated, and Payment marked as done successfully."))
        return {"success": True, "message": "Payment Entry, Technician Visit, and Payment status updated successfully."}

    except Exception as e:
        frappe.db.rollback()
        error_message = _("Error creating Payment Entry: {0}.").format(str(e))
        frappe.throw(error_message)


@frappe.whitelist()
def update_technician_visit_entry(visit_id, status, payment_status):
    # Ensure valid input
    if not visit_id:
        return {"success": False, "message": "Technician visit ID is required."}

    try:
        # Fetch the Technician Visit entry and update fields
        technician_visit = frappe.get_doc("Technician Visit Entry", visit_id)
        technician_visit.status = status
        technician_visit.payment_status = payment_status
        technician_visit.save()

        frappe.db.commit()
        return {"success": True, "message": "Technician visit entry updated successfully."}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Update Technician Visit Error")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def delete_technician_visit_payment(docname):
    # Ensure valid input
    if not docname:
        return {"success": False, "message": "Technician Visit Payment ID is required."}

    try:
        # Fetch the Technician Visit Payment document
        technician_visit_payment = frappe.get_doc("Technician Visit Payment", docname)
        technician_id = technician_visit_payment.technician_id
        total_amount = technician_visit_payment.total_amount
        # 1. Get all the related Technician Visit entries and reset their statuses
        if technician_visit_payment.payments:
            for payment in technician_visit_payment.payments:
                visit_id = payment.technician_visit_id
                if visit_id:
                    technician_visit = frappe.get_doc("Technician Visit Entry", visit_id)
                    # Reset status and payment status
                    technician_visit.status = "Incentive Finalize"  # Revert to the previous status
                    technician_visit.payment_status = "Pending"  # Reset payment status
                    technician_visit.save()
                    frappe.msgprint(_("Technician Visit {0} status has been reset.").format(visit_id))

        # 2. After resetting Technician Visit statuses, cancel and delete the related Payment Entry
        if technician_visit_payment.payment_entry_id:  # Check if the Payment Entry ID exists
            payment_entry = frappe.get_doc("Payment Entry", technician_visit_payment.payment_entry_id)
            if payment_entry.docstatus == 1:  # Ensure the Payment Entry is submitted
                payment_entry.cancel()  # Cancel the payment entry
            payment_entry.delete()  # Delete the payment entry after cancelling
            frappe.msgprint(_("Payment Entry {0} has been deleted.").format(payment_entry.name))
        technician_visit_payment.payment_entry_id = ''
        technician_visit_payment.payment_done = 0
        technician_visit_payment.save()
        # Commit the changes
        technician_details = frappe.get_doc('Technician Details',technician_id)
        technician_details.total_amount_settled -= total_amount
        technician_details.save()
        frappe.db.commit()
        return {"success": True, "message": "Undo successful. All related records have been updated."}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Undo Technician Visit Payment Error")
        return {"success": False, "message": str(e)}
