import frappe

def execute(filters=None):
    columns = [
        {"label": "Name", "fieldname": "name", "fieldtype": "Link", "options": "Serial No", "width": 150},
        {"label": "Duplicate Entry Found", "fieldname": "duplicate_entry_found", "fieldtype": "Data", "width": 150},
        {"label": "Item Code", "fieldname": "item_code",  "fieldtype": "Link", "options": "Item", "width": 150},
        {"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 100},
        {"label": "Purchase Document No", "fieldname": "purchase_document_no", "fieldtype": "Link", "options": "Purchase Receipt", "width": 150},
        {"label": "Purchase Order ID", "fieldname": "purchase_order_id",  "fieldtype": "Link", "options": "Purchase Order", "width": 150},
        {"label": "Purchase Invoice ID", "fieldname": "purchase_invoice_id",  "fieldtype": "Link", "options": "Purchase Invoice", "width": 150},
        {"label": "Delivery Note ID", "fieldname": "delivery_note_id",  "fieldtype": "Link", "options": "Delivery Note", "width": 150},
        {"label": "Sales Order ID", "fieldname": "sales_order_id","fieldtype": "Link", "options": "Sales Order", "width": 150},
        {"label": "Customer ID", "fieldname": "customer_id", "fieldtype": "Link", "options": "Customer", "width": 150},
        {"label": "Customer Name", "fieldname": "customer_name", "fieldtype": "Data", "width": 150}
    ]
    
    data = []
    
    # Prepare filters
    filters_conditions = {}
    if filters:
        if filters.get('status') is not None:
            filters_conditions['status'] = filters.get('status')
        if filters.get('serial_number'):
            filters_conditions['name'] = filters.get('serial_number')
        if filters.get('item_code'):
            filters_conditions['item_code'] = filters.get('item_code')
    
    # Query the Serial No doctype with applied filters
    serial_records = frappe.get_all('Serial No', fields=['name', 'item_code', 'status', 'purchase_document_no'], filters=filters_conditions)

    # Check for duplicates
    serial_numbers = [record['name'] for record in serial_records]
    duplicate_entries = [serial_number for serial_number in serial_numbers if serial_numbers.count(serial_number) > 1]

    for record in serial_records:
        row = {
            "name": record.name,
            "item_code": record.item_code,
            "status": record.status,
            "purchase_document_no": record.purchase_document_no,
            "purchase_order_id": None,
            "purchase_invoice_id": None,
            "delivery_note_id": None,
            "sales_order_id": None,
            "customer_id": None,
            "customer_name": None,
            "duplicate_entry_found": "Yes" if record.name in duplicate_entries else "No"
        }

        # Determine Purchase Order ID and Purchase Invoice ID based on Purchase Document No
        if record.purchase_document_no:
            # Fetch Purchase Invoice ID from Purchase Invoice Item child table
            purchase_invoice_items = frappe.get_all('Purchase Invoice Item', filters={'purchase_receipt': record.purchase_document_no}, fields=['parent', 'purchase_order'])
            if purchase_invoice_items:
                row['purchase_invoice_id'] = purchase_invoice_items[0].parent
                row['purchase_order_id'] = purchase_invoice_items[0].purchase_order

        # Check if the status is 'Delivered'
        if record.status == 'Delivered':
            # Fetch Sales Order ID from Sales Order Item child table
            sales_orders = frappe.get_all('Sales Order Item', filters={'serial_no': record.name}, fields=['parent'])
            if sales_orders:
                row['sales_order_id'] = sales_orders[0].parent
                
                # Fetch Delivery Note ID from Delivery Note doctype
                delivery_notes = frappe.get_all('Delivery Note', filters={'against_sales_order': row['sales_order_id']}, fields=['name'])
                if delivery_notes:
                    row['delivery_note_id'] = delivery_notes[0].name

                # Fetch Customer from Sales Order
                sales_order_doc = frappe.get_doc('Sales Order', row['sales_order_id'])
                if sales_order_doc.customer:
                    # Fetch Customer Name from Customer doctype
                    customer_doc = frappe.get_doc('Customer', sales_order_doc.customer)
                    row['customer_id'] = sales_order_doc.customer  # Customer ID
                    row['customer_name'] = customer_doc.customer_name  # Customer Name

        data.append(row)
    
    return columns, data
