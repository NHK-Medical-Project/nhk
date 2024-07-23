# Copyright (c) 2024, vishnu and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PaymentLinkLog(Document):
	pass







import frappe
import requests

@frappe.whitelist()
def cancel_link(p_id=None):
    if p_id:
        payment_link = frappe.get_doc('Payment Link Log', p_id)
        admin_settings = frappe.get_doc('Admin Settings')
        razorpay_base_url = admin_settings.razorpay_base_url
        razorpay_key_id = admin_settings.razorpay_api_key
        razorpay_key_secret = admin_settings.get_password('razorpay_secret')
        razorpay_api_url = razorpay_base_url + "payment_links/"+ payment_link.link_id +"/cancel"
        # razorpay_api_cancel = frappe.get_doc('Razorpay Api to cancel link')

        # razorpay_api_key = razorpay_api_cancel.razorpay_api_key
        # razorpay_api_secret = razorpay_api_cancel.razorpay_secret

        # Razorpay API endpoint for canceling a payment link
        # api_url = razorpay_api_cancel.razorpay_url
        # new_api_url = api_url.replace("link_id", payment_link.link_id)

        try:
            response = requests.post(razorpay_api_url, auth=(razorpay_key_id, razorpay_key_secret))
            response_dict = response.json()
            if response.status_code == 200:
                payment_link.enabled = 0
                payment_link.save()

                sales_order_doc = frappe.get_doc('Sales Order', payment_link.sales_order)
                sales_order_doc.custom_razorpay_payment_url = None
                sales_order_doc.save()
                return "Payment link canceled successfully"
            else:
                return f"Error canceling payment link. Status code: {response.status_code}, {response_dict['error']['description']}"
        except requests.exceptions.RequestException as e:
            return f"Error in Payment Link Log: {e}"




@frappe.whitelist()
def sync_payment(link_id, p_id):
    try:
        # Fetch Razorpay API credentials from the Admin Settings doctype
        admin_settings = frappe.get_doc('Admin Settings')
        razorpay_base_url = admin_settings.razorpay_base_url
        razorpay_key_id = admin_settings.razorpay_api_key
        razorpay_key_secret = admin_settings.get_password('razorpay_secret')
        razorpay_api_url = razorpay_base_url + "payment_links/" + link_id

        # Make a request to the Razorpay API to get the payment details
        response = requests.get(razorpay_api_url, auth=(razorpay_key_id, razorpay_key_secret))
        data = response.json()

        # Extract the relevant details from the response
        received_amount = data.get('amount_paid')
        payment_status = data.get('status')
        paid_amount = float(received_amount) / 100

        # Update the payment link document in Frappe
        if payment_status == 'paid':
            sales_order_id = frappe.db.get_value('Payment Link Log', p_id, 'sales_order')
            customer_id = frappe.db.get_value('Payment Link Log', p_id, 'customer_id')
            get_razorpay_payment_details(received_amount, sales_order_id, customer_id, link_id)
            frappe.db.set_value('Payment Link Log', p_id, 'payment_status', 'Paid')
            frappe.db.set_value('Payment Link Log', p_id, 'paid_amount', paid_amount)
        elif payment_status == 'cancelled':
            frappe.db.set_value('Payment Link Log', p_id, 'payment_status', 'Cancelled')
        elif payment_status == 'expired':
            frappe.db.set_value('Payment Link Log', p_id, 'payment_status', 'Expired')

        # Commit the transaction to ensure changes are saved
        frappe.db.commit()

        # Return the details to the client script
        return {"status": True, "msg": "Payment Link status synced successfully"}
    except Exception as e:
        return {"status": False, "msg": f"Error syncing payment details: {str(e)}"}

@frappe.whitelist(allow_guest=True)
def get_razorpay_payment_details(received_amount, sales_order_id, customer_id, link_id):
    try:
        admin_settings = frappe.get_doc('Admin Settings')
        razorpay_base_url = admin_settings.razorpay_base_url
        razorpay_key_id = admin_settings.razorpay_api_key
        razorpay_key_secret = admin_settings.razorpay_secret
        razorpay_api_url = razorpay_base_url + "payment_links/" + link_id

        razorpay_payment_link_id = link_id
        # razorpay_api = frappe.get_doc('Razorpay Api')
        # custom_razorpay_api_url = f'https://api.razorpay.com/v1/payment_links/{razorpay_payment_link_id}'

        response = requests.get(razorpay_api_url, auth=(razorpay_key_id, razorpay_key_secret))
        if response.status_code == 200:
            razorpay_response = response.json()
            payments = razorpay_response.get('payments')
            if payments:
                most_recent_payment = max(payments, key=lambda x: x['created_at'])
                payment_amount = most_recent_payment.get('amount')
                final_amount = int(float(payment_amount) / 100)
                sales_order = frappe.get_doc("Sales Order", sales_order_id)
                order_type = sales_order.order_type
                razorpay_link_so = sales_order.custom_razorpay_payment_url
                rounded_total = sales_order.rounded_total
                master_order_id = sales_order.master_order_id
                journal_entry = None  # Initialize journal_entry to None
				# print(order_type)
                if order_type == "Rental":
                    security_deposit = sales_order.security_deposit if sales_order.security_deposit else 0
                    if isinstance(security_deposit, str):
                        security_deposit = float(security_deposit) if '.' in security_deposit else int(security_deposit)

                    payment_entry = create_payment_entry(rounded_total, sales_order_id, customer_id, razorpay_payment_link_id, received_amount, master_order_id)

                    if security_deposit > 0:
                        # frappe.set_user("Administrator")
                        journal_entry = create_journal_entry_razorpay(security_deposit, sales_order_id, customer_id, razorpay_payment_link_id, master_order_id)
                        # frappe.set_user("Guest")

                    create_razorpay_payment_details(payment_entry, journal_entry, sales_order_id, order_type, customer_id, razorpay_payment_link_id, razorpay_link_so)

                    return True

                else:
                    frappe.msgprint("Order type is not Rental. Proceeding with standard payment entry.")
                    payment_entry = create_payment_entry(rounded_total, sales_order_id, customer_id, razorpay_payment_link_id, received_amount, master_order_id)
                    create_razorpay_payment_details(payment_entry, journal_entry, sales_order_id, order_type, customer_id, razorpay_payment_link_id, razorpay_link_so)
                    return True
            else:
                frappe.msgprint('Amount Paid not found in the response.')
                frappe.log_error('Amount Paid not found in the response.')
        else:
            frappe.msgprint(f'Request failed with status code: {response.status_code}')
            frappe.log_error(f'Request failed with status code: {response.status_code}; Response text: {response.text}')
    except Exception as e:
        frappe.msgprint(f'Error: {e}')
        frappe.log_error(f'Error: {e}')

def create_razorpay_payment_details(payment_entry_id, journal_entry_id, sales_order_id, order_type, customer, razorpay_payment_link_id, razorpay_link_so):
    try:
        if is_razorpay_payment_details(razorpay_payment_link_id):
            frappe.msgprint('Razorpay Payment Details already exists. Skipping creation.')
            return
        razorpay_payment_details = frappe.get_doc({
            "doctype": "Razorpay Payment Details",
            "payment_entry_id": payment_entry_id,
            "journal_entry_id": journal_entry_id,
            "sales_order_id": sales_order_id,
            "order_type": order_type,
            "date": frappe.utils.nowdate(),
            "customer_id": customer,
            "razorpay_link": razorpay_link_so,
            "reference_id": razorpay_payment_link_id
        })
        razorpay_payment_details.insert(ignore_permissions=True)
        frappe.db.commit()
        frappe.msgprint("Razorpay Payment Details created successfully.")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), _("Failed to create Razorpay Payment Details"))
        frappe.throw(_("Failed to create Razorpay Payment Details. Please try again later."))

def is_razorpay_payment_details(reference_id):
    is_razorpay_payment_details = frappe.get_value("Razorpay Payment Details", {
        "reference_id": reference_id
    })
    return bool(is_razorpay_payment_details)

def create_journal_entry_razorpay(security_deposit, sales_order_id, customer,razorpay_payment_link_id,master_order_id):
    try:
        # frappe.set_user("Administrator")
        if is_journal_entry_exists(sales_order_id):
            frappe.msgprint('Journal Entry already exists. Skipping creation.')
            return

        today = frappe.utils.nowdate()

        # Create a new Journal Entry document
        journal_entry = frappe.new_doc("Journal Entry")
        journal_entry.voucher_type = "Journal Entry"
        journal_entry.sales_order_id = sales_order_id
        journal_entry.posting_date = today
        journal_entry.journal_entry_type = "Security Deposit"
        journal_entry.security_deposite_type = "SD Amount Received From Client"
        journal_entry.master_order_id = master_order_id
        journal_entry.cheque_no = razorpay_payment_link_id
        journal_entry.cheque_date = today
        journal_entry.user_remark = f"Security Deposit Payment Against Sales Order {sales_order_id}. Remark: System Generated From RazorPay"
        # journal_entry.customer_id = customer
        journal_entry.mode_of__payment = 'Razorpay'
        journal_entry.transactional_effect = "Plus"
        journal_entry.custom_razorpay = 1

        # Add accounts for debit and credit
        journal_entry.append("accounts", {
            "account": 'Kotak Bank Current Account - INR',
            "debit_in_account_currency": security_deposit
        })
        journal_entry.append("accounts", {
            "account": "Debtors - INR",
            "party_type": "Customer",
            "party": customer,
            "credit_in_account_currency": security_deposit
        })

        # Save and submit the Journal Entry document
        journal_entry.insert(ignore_permissions=True)
        journal_entry.submit()
        frappe.db.commit()
        frappe.msgprint("Security Deposit Journal Entry created successfully.")
        return journal_entry.name
        # frappe.set_user("Guest")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), _("Failed to create Security Deposit Journal Entry"))
        frappe.throw(_("Failed to create Security Deposit Journal Entry. Please try again later."))


def create_payment_entry(rounded_total, sales_order_id, customer_id, razorpay_payment_link_id, received_amount, master_order_id):
    try:
        # frappe.msgprint("Payment Entry Function Called")
        # frappe.set_user("Administrator")
        
        if is_payment_entry_exists(razorpay_payment_link_id):
            frappe.msgprint('Payment Entry already exists. Skipping creation.')
            return
        
        payment_entry = frappe.get_doc({
            "doctype": "Payment Entry",
            "paid_from": "Debtors - INR",
            "paid_to": "Kotak Bank Current Account - INR",
            "received_amount": rounded_total,
            "base_received_amount": rounded_total,
            "paid_amount": int(rounded_total),
            "references": [{
                "reference_doctype": "Sales Order",
                "reference_name": sales_order_id,
                "allocated_amount": int(rounded_total)
            }],
            "sales_order_id": sales_order_id,
            "custom_system_generator_from_razorpay": 1,
            "reference_date": frappe.utils.today(),
            "account": "Accounts Receivable",
            "party_type": "Customer",
            "party": customer_id,
            "custom_from_razorpay": 1,
            "master_order_id":master_order_id,
            "mode_of_payment": "Razorpay",
            "reference_no": razorpay_payment_link_id
        }, ignore_permissions=True)
        
        payment_entry.insert(ignore_permissions=True)
        payment_entry.submit()
        frappe.db.commit()
        
        payment_link_log = frappe.get_all("Payment Link Log", filters={"link_id": razorpay_payment_link_id})
        if payment_link_log:
            payment_link_log_doc = frappe.get_doc("Payment Link Log", payment_link_log[0].name)
            payment_link_log_doc.payment_status = "Paid"
            payment_link_log_doc.save(ignore_permissions=True)
        
        # frappe.set_user("Guest")
        return payment_entry.name
    except frappe.exceptions.ValidationError as e:
        frappe.log_error(f"Error creating Payment Entry: {e}")
        frappe.msgprint(f'Error creating Payment Entry: {e}')
        return f"Error creating Payment Entry: {e}"

def is_payment_entry_exists(reference_no):
    payment_entry = frappe.get_value("Payment Entry", {"reference_no": reference_no})
    return bool(payment_entry)

def is_journal_entry_exists(reference_id):
    existing_journal_entry = frappe.get_value("Journal Entry", {
        "sales_order_id": reference_id,
        "security_deposite_type": "SD Amount Received From Client"
    })
    return bool(existing_journal_entry)




# @frappe.whitelist()
# def sync_all_payment_details():
#     payment_link_list = frappe.get_all('Payment Link Log', 
#                                        filters={
#                                                 'payment_status':("in",["Created", "Partially Paid"])
#                                                 },
#                                         fields=["link_id", "name"])
#     count = 0
#     for payment_link in payment_link_list:
#         resp = sync_payment(payment_link.link_id, payment_link.name)
#         if resp.get('status'):
#             count += 1
#     msg = "All Payment Link status synced successfully"
#     if count != len(payment_link_list):
#         msg = f"{count} out of {len(payment_link_list)} Payment Link status synced successfully"
#     return {"status": True, "msg": msg}









@frappe.whitelist()
def sync_all_payment_details():
    payment_link_list = frappe.get_all('Payment Link Log', 
                                       filters={
                                                'payment_status':("in",["Created", "Partially Paid"]),"enabled":1
                                                },
                                       fields=["link_id", "name"])
    for payment_link in payment_link_list:
        # Enqueue the sync_payment function to run in the background
        frappe.enqueue('nhk.nhk.doctype.payment_link_log.payment_link_log.sync_payment', link_id=payment_link.link_id, p_id=payment_link.name)

    return {"status": True, "msg": "Payment Link status sync initiated for all relevant records"}
