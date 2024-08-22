import frappe

def execute(filters=None):
    # Define the columns you want to display
    columns = [
        {"label": "Name", "fieldname": "name", "fieldtype": "Link", "options": "Sales Order", "width": 120},
        {"label": "Order Type", "fieldname": "order_type", "fieldtype": "Data", "width": 80},
        {"label": "Customer", "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 120},
        {"label": "Customer Name", "fieldname": "customer_name", "fieldtype": "Data", "width": 150},
        {"label": "Mobile No.", "fieldname": "customer_mobile_no", "fieldtype": "Data", "width": 100},
        {"label": "Referrer", "fieldname": "custom_referrer", "fieldtype": "Link", "options": "Referrer", "width": 150},
        {"label": "Referrer Name", "fieldname": "custom_referrer_name", "fieldtype": "Data", "width": 150},
        {"label": "Referrer Hospital", "fieldname": "custom_referrer_hospital", "fieldtype": "Link", "options": "Hospital", "width": 150},

        {"label": "Referrer Commission Amount", "fieldname": "custom_referrer_commission_amount", "fieldtype": "Currency", "width": 100},
        {"label": "Referrer Commission Status", "fieldname": "custom_referrer_commission_status", "fieldtype": "Data", "width": 150},
        {"label": "Sales Person", "fieldname": "sales_person", "fieldtype": "Link", "options": "Sales Person", "width": 150},
        {"label": "Sales Commission Amount", "fieldname": "custom_sales_commission_amount", "fieldtype": "Currency", "width": 100},
        {"label": "Sales Commission Status", "fieldname": "custom_sales_commission_status", "fieldtype": "Select", "width": 80},
        {"label": "Order Date", "fieldname": "order_date", "fieldtype": "Date", "width": 100},
        {"label": "Start Date", "fieldname": "start_date", "fieldtype": "Date", "width": 100},
        {"label": "End Date", "fieldname": "end_date", "fieldtype": "Date", "width": 100},
        {"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 100},
        {"label": "Security Deposit", "fieldname": "security_deposit", "fieldtype": "Currency", "width": 100},
        {"label": "Order Amount", "fieldname": "rounded_total", "fieldtype": "Currency", "width": 100},
        {"label": "Grand Total", "fieldname": "total_rental_amount", "fieldtype": "Currency", "width": 100},
        {"label": "Paid Amount", "fieldname": "paid_amount", "fieldtype": "Currency", "width": 100},
        {"label": "UnPaid Amount", "fieldname": "unpaid_amount", "fieldtype": "Currency", "width": 100},
        {"label": "Security Deposit Status", "fieldname": "security_deposit_status", "fieldtype": "Select", "width": 100},
        {"label": "Payment Status", "fieldname": "payment_status", "fieldtype": "Select", "width": 100},
        {"label": "SO Type", "fieldname": "so_type", "fieldtype": "Data", "width": 50},
        {"label": "Docstatus", "fieldname": "docstatus", "fieldtype": "Int", "width": 50},
    ]


    # Extract filters
    order_types = filters.get("order_type", ["Rental"])  # Defaulting to "Rental" if not provided
    date_range = filters.get("order_date")
    customer = filters.get("customer")
    statuses = filters.get("status", [])
    referrer = filters.get("referrer")
    referrer_commission_status = filters.get("referrer_commission_status")
    sales_person = filters.get("sales_person")
    sales_commission_status = filters.get("sales_commission_status")
    referrer_hospital = filters.get("custom_referrer_hospital")

    # Initialize conditions with a default condition to exclude Cancelled orders and draft orders
    conditions = {
        "status": ("!=", "Cancelled"),
        "docstatus": 1  # Only include submitted documents
    }

    # Apply additional filters if they exist
    if order_types:
        conditions["order_type"] = ("in", order_types)
    if customer:
        conditions["customer"] = customer
    if date_range:
        if isinstance(date_range, list) and len(date_range) == 2:
            start_date, end_date = date_range
            if "Rental" in order_types:
                conditions["start_date"] = ("between", [start_date, end_date])
            else:
                conditions["transaction_date"] = ("between", [start_date, end_date])
    if statuses:
        conditions["status"] = ("in", statuses)

    if referrer:
        conditions["custom_referrer"] = referrer
    if referrer_commission_status:
        conditions["custom_referrer_commission_status"] = referrer_commission_status

    if sales_person:
        conditions["sales_person"] = sales_person
    if sales_commission_status:
        conditions["custom_sales_commission_status"] = sales_commission_status
    if referrer_hospital:
        conditions["custom_referrer_hospital"] = referrer_hospital

    # Fetch sales order records from the database based on the selected filters
    sales_orders = frappe.get_all("Sales Order", fields=["*"], filters=conditions)

    # Prepare the data to be displayed
    data = []
    for order in sales_orders:
        # Ensure numeric values before adding
        security_deposit = float(order.security_deposit) if order.security_deposit else 0.0
        rounded_total = float(order.rounded_total) if order.rounded_total else 0.0
        paid_security_deposit_amount = float(order.paid_security_deposite_amount) if order.paid_security_deposite_amount else 0.0
        received_amount = float(order.received_amount) if order.received_amount else 0.0
        outstanding_security_deposit_amount = float(order.outstanding_security_deposit_amount) if order.outstanding_security_deposit_amount else 0.0
        balance_amount = float(order.balance_amount) if order.balance_amount else 0.0
        
        so_type = "M" if order.is_renewed == 0 else "R"
        
        # Create the row with all necessary fields
        row = {
            "name": order.name,
            "customer": order.customer,
            "order_date": order.transaction_date,
            "start_date": order.start_date,
            "end_date": order.end_date,
            "order_type": order.order_type,
            "customer_name": order.customer_name,
            "custom_referrer": order.custom_referrer,
            "custom_referrer_name": order.custom_referrer_name,
            "custom_referrer_hospital": order.custom_referrer_hospital, 
            "custom_referrer_commission_amount": order.custom_referrer_commission_amount,
            "custom_referrer_commission_status": order.custom_referrer_commission_status,
            "sales_person": order.sales_person,
            "custom_sales_commission_amount": order.custom_sales_commission_amount,
            "custom_sales_commission_status": order.custom_sales_commission_status,
            "customer_mobile_no": order.customer_mobile_no,
            "status": order.status,
            "security_deposit": security_deposit,
            "rounded_total": rounded_total,
            "total_rental_amount": security_deposit + rounded_total,
            "security_deposit_status": order.security_deposit_status,
            "payment_status": order.payment_status,
            "paid_amount": received_amount if order.is_renewed else paid_security_deposit_amount + received_amount,
            "unpaid_amount": outstanding_security_deposit_amount + balance_amount,
            "so_type": so_type,
            "docstatus": order.docstatus,
        }
        data.append(row)


    html_card = """
    <script>
        document.addEventListener('click', function(event) {
            // Check if the clicked element is a cell
            var clickedCell = event.target.closest('.dt-cell__content');
            if (clickedCell) {
                // Remove highlight from previously highlighted cells
                var previouslyHighlightedCells = document.querySelectorAll('.highlighted-cell');
                previouslyHighlightedCells.forEach(function(cell) {
                    cell.classList.remove('highlighted-cell');
                    cell.style.backgroundColor = ''; // Remove background color
                    cell.style.border = ''; // Remove border
                    cell.style.fontWeight = '';
                });

                // Highlight the clicked row's cells
                var clickedRow = event.target.closest('.dt-row');
                var cellsInClickedRow = clickedRow.querySelectorAll('.dt-cell__content');
                cellsInClickedRow.forEach(function(cell) {
                    cell.classList.add('highlighted-cell');
                    cell.style.backgroundColor = '#d7eaf9'; // Light blue background color
                    cell.style.border = '2px solid #90c9e3'; // Border color
                    cell.style.fontWeight = 'bold';
                });
            }
        });
    </script>
    """

    return columns, data, html_card
