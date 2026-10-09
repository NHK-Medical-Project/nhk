# import frappe

# def execute(filters=None):
#     columns = [
#         {"label": "Name", "fieldname": "name", "fieldtype": "Link", "options": "Serial No", "width": 150},
#         {"label": "Duplicate Entry Found", "fieldname": "duplicate_entry_found", "fieldtype": "Data", "width": 40},
#         {"label": "Item Code", "fieldname": "item_code",  "fieldtype": "Link", "options": "Item", "width": 150},
#         {"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 100},
#         {"label": "Purchase Document No", "fieldname": "purchase_document_no", "fieldtype": "Link", "options": "Purchase Receipt", "width": 150},
#         {"label": "Purchase Order ID", "fieldname": "purchase_order_id",  "fieldtype": "Link", "options": "Purchase Order", "width": 150},
#         {"label": "Purchase Invoice ID", "fieldname": "purchase_invoice_id",  "fieldtype": "Link", "options": "Purchase Invoice", "width": 150},
#         {"label": "Purchase Invoice Date", "fieldname": "purchase_invoice_date", "fieldtype": "Date", "width": 120},
#         {"label": "Taxable Value", "fieldname": "taxable_value", "fieldtype": "Currency", "width": 120},
#         {"label": "Tax Amount", "fieldname": "tax_amount", "fieldtype": "Currency", "width": 120},
#         {"label": "Total Amount", "fieldname": "total_amount", "fieldtype": "Currency", "width": 120},
#         {"label": "Delivery Note ID", "fieldname": "delivery_note_id",  "fieldtype": "Link", "options": "Delivery Note", "width": 150},
#         {"label": "Sales Order ID", "fieldname": "sales_order_id","fieldtype": "Link", "options": "Sales Order", "width": 150},
#         {"label": "Customer ID", "fieldname": "customer_id", "fieldtype": "Link", "options": "Customer", "width": 150},
#         {"label": "Customer Name", "fieldname": "customer_name", "fieldtype": "Data", "width": 150}
#     ]
    
#     data = []
    
#     # Prepare filters
#     filters_conditions = {}
#     if filters:
#         if filters.get('status') is not None:
#             filters_conditions['status'] = filters.get('status')
#         if filters.get('serial_number'):
#             filters_conditions['name'] = filters.get('serial_number')
#         if filters.get('item_code'):
#             filters_conditions['item_code'] = filters.get('item_code')
    
#     # Query the Serial No doctype with applied filters
#     serial_records = frappe.get_all(
#         'Serial No',
#         fields=['name', 'item_code', 'status', 'purchase_document_no'],
#         filters=filters_conditions
#     )

#     # Check for duplicates
#     serial_numbers = [record['name'] for record in serial_records]
#     duplicate_entries = [serial_number for serial_number in serial_numbers if serial_numbers.count(serial_number) > 1]

#     for record in serial_records:
#         row = {
#             "name": record.name,
#             "item_code": record.item_code,
#             "status": record.status,
#             "purchase_document_no": record.purchase_document_no,
#             "purchase_order_id": None,
#             "purchase_invoice_id": None,
#             "purchase_invoice_date": None,
#             "taxable_value": None,
#             "tax_amount": None,
#             "total_amount": None,
#             "delivery_note_id": None,
#             "sales_order_id": None,
#             "customer_id": None,
#             "customer_name": None,
#             "duplicate_entry_found": "Yes" if record.name in duplicate_entries else "No"
#         }

#         # Determine Purchase Order ID and Purchase Invoice ID based on Purchase Document No
#         if record.purchase_document_no:
#             # Fetch Purchase Invoice ID from Purchase Invoice Item child table
#             purchase_invoice_items = frappe.get_all(
#                 'Purchase Invoice Item',
#                 filters={'purchase_receipt': record.purchase_document_no, 'item_code': record.item_code},
#                 fields=['parent', 'purchase_order']
#             )
#             if purchase_invoice_items:
#                 row['purchase_invoice_id'] = purchase_invoice_items[0].parent
#                 row['purchase_order_id'] = purchase_invoice_items[0].purchase_order

#                 # Fetch Purchase Invoice details
#                 invoice = frappe.get_value(
#                     "Purchase Invoice",
#                     purchase_invoice_items[0].parent,
#                     ["posting_date", "base_net_total", "total_taxes_and_charges", "grand_total"],
#                     as_dict=True
#                 )
#                 if invoice:
#                     row['purchase_invoice_date'] = invoice.posting_date
#                     row['taxable_value'] = invoice.base_net_total
#                     row['tax_amount'] = invoice.total_taxes_and_charges
#                     row['total_amount'] = invoice.grand_total

#         # Check if the status is 'Delivered'
#         if record.status == 'Delivered':
#             # Fetch Sales Order ID from Sales Order Item child table
#             sales_orders = frappe.get_all('Sales Order Item', filters={'serial_no': record.name}, fields=['parent'])
#             if sales_orders:
#                 row['sales_order_id'] = sales_orders[0].parent
                
#                 # Fetch Delivery Note ID from Delivery Note doctype
#                 delivery_notes = frappe.get_all('Delivery Note', filters={'against_sales_order': row['sales_order_id']}, fields=['name'])
#                 if delivery_notes:
#                     row['delivery_note_id'] = delivery_notes[0].name

#                 # Fetch Customer from Sales Order
#                 sales_order_doc = frappe.get_doc('Sales Order', row['sales_order_id'])
#                 if sales_order_doc.customer:
#                     # Fetch Customer Name from Customer doctype
#                     customer_doc = frappe.get_doc('Customer', sales_order_doc.customer)
#                     row['customer_id'] = sales_order_doc.customer  # Customer ID
#                     row['customer_name'] = customer_doc.customer_name  # Customer Name

#         data.append(row)
    
#     return columns, data
import frappe

def execute(filters=None):
    filters = frappe._dict(filters or {})

    columns = [
        {"label": "Serial Number", "fieldname": "name", "fieldtype": "Link", "options": "Serial No", "width": 150},
        {"label": "Duplicate Entry Found", "fieldname": "duplicate_entry_found", "fieldtype": "Data", "width": 40},
        {"label": "Item Code", "fieldname": "item_code",  "fieldtype": "Link", "options": "Item", "width": 150},
        {"label": "Item Disabled", "fieldname": "item_disabled", "fieldtype": "Check", "width": 80},
        {"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 100},
        {"label": "Purchase Document No", "fieldname": "purchase_document_no", "fieldtype": "Link", "options": "Purchase Receipt", "width": 150},
        {"label": "Purchase Order ID", "fieldname": "purchase_order_id",  "fieldtype": "Link", "options": "Purchase Order", "width": 150},
        {"label": "Purchase Order Date", "fieldname": "purchase_order_date", "fieldtype": "Date", "width": 120},
        {"label": "Purchase Invoice ID", "fieldname": "purchase_invoice_id", "fieldtype": "Link", "options": "Purchase Invoice", "width": 150},
        {"label": "Purchase Invoice Date", "fieldname": "purchase_invoice_date", "fieldtype": "Date", "width": 120},
        {"label": "Taxable Value (1 qty)", "fieldname": "taxable_value", "fieldtype": "Currency", "width": 120},
        {"label": "Tax Amount (1 qty)", "fieldname": "tax_amount", "fieldtype": "Currency", "width": 120},
        {"label": "Total Amount (1 qty)", "fieldname": "total_amount", "fieldtype": "Currency", "width": 120},
        {"label": "Delivery Note ID", "fieldname": "delivery_note_id",  "fieldtype": "Link", "options": "Delivery Note", "width": 150},
        {"label": "Sales Order ID", "fieldname": "sales_order_id","fieldtype": "Link", "options": "Sales Order", "width": 150},
        {"label": "Customer ID", "fieldname": "customer_id", "fieldtype": "Link", "options": "Customer", "width": 150},
        {"label": "Customer Name", "fieldname": "customer_name", "fieldtype": "Data", "width": 150}
    ]

    # SQL for Serial No + Purchase Invoice Item + Item + Purchase Order
    status_filter = f" AND sn.status = '{filters.status}'" if filters.get("status") else ""
    serial_filter = f" AND sn.name = '{filters.serial_number}'" if filters.get("serial_number") else ""
    item_filter = f" AND sn.item_code = '{filters.item_code}'" if filters.get("item_code") else ""

    item_disabled_filter = ""
    if filters.get("item_disabled") in ("0", "1"):
        item_disabled_filter = f" AND i.disabled = {filters.get('item_disabled')}"

    data = frappe.db.sql(f"""
        SELECT
            sn.name,
            sn.item_code,
            i.disabled AS item_disabled,
            sn.status,
            sn.purchase_document_no,
            pii.purchase_order AS purchase_order_id,
            po.transaction_date AS purchase_order_date,
            pii.parent AS purchase_invoice_id,
            pii.qty,
            pii.base_net_amount,
            pii.igst_amount,
            pii.cgst_amount,
            pii.sgst_amount,
            pi.posting_date AS purchase_invoice_date,
            soi.parent AS sales_order_id,
            so.customer AS customer_id,
            c.customer_name,
            CASE WHEN dup.cnt > 1 THEN 'Yes' ELSE 'No' END AS duplicate_entry_found
        FROM `tabSerial No` sn
        LEFT JOIN `tabPurchase Invoice Item` pii
            ON pii.purchase_receipt = sn.purchase_document_no
            AND pii.item_code = sn.item_code
        LEFT JOIN `tabPurchase Invoice` pi
            ON pi.name = pii.parent
        LEFT JOIN `tabPurchase Order` po
            ON po.name = pii.purchase_order
        LEFT JOIN `tabItem` i
            ON i.name = sn.item_code
        LEFT JOIN `tabSales Order Item` soi
            ON soi.serial_no LIKE CONCAT('%%', sn.name, '%%')
        LEFT JOIN `tabSales Order` so
            ON so.name = soi.parent
        LEFT JOIN `tabCustomer` c
            ON c.name = so.customer
        LEFT JOIN (
            SELECT name, COUNT(*) as cnt
            FROM `tabSerial No`
            GROUP BY name
        ) dup
            ON dup.name = sn.name
        WHERE 1=1
        {status_filter}
        {serial_filter}
        {item_filter}
        {item_disabled_filter}
    """, as_dict=True)


    # Calculate single unit amounts
    for row in data:
        if row.get("qty") and row.get("base_net_amount") is not None:
            row['taxable_value'] = row['base_net_amount'] / row['qty']
            total_tax = (row.get("igst_amount") or 0) + (row.get("cgst_amount") or 0) + (row.get("sgst_amount") or 0)
            row['tax_amount'] = total_tax / row['qty']
            row['total_amount'] = row['taxable_value'] + row['tax_amount']

    # Fetch latest Delivery Note for each Sales Order
    for row in data:
        if row.get("sales_order_id"):
            delivery_notes = frappe.get_all(
                'Delivery Note',
                filters={'against_sales_order': row['sales_order_id']},
                fields=['name'],
                order_by='posting_date desc'
            )
            if delivery_notes:
                row['delivery_note_id'] = delivery_notes[0].name

    return columns, data
