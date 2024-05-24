import frappe

def execute(filters=None):
    # Define the columns you want to display
    columns = [
        {"label": "Name", "fieldname": "name", "fieldtype": "Link", "options": "Sales Order", "width": 120},
        {"label": "Order Type", "fieldname": "order_type", "fieldtype": "Data", "width": 80},
        {"label": "Customer", "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 120},
        {"label": "Customer Name", "fieldname": "customer_name", "fieldtype": "Data", "width": 150},
        {"label": "Order Date", "fieldname": "order_date", "fieldtype": "Date", "width": 100},
        {"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 100},
        {"label": "Grand Total", "fieldname": "total_rental_amount", "fieldtype": "Currency", "width": 100},
        {"label": "Paid Amount", "fieldname": "paid_amount", "fieldtype": "Currency", "width": 100},
        {"label": "UnPaid Amount", "fieldname": "unpaid_amount", "fieldtype": "Currency", "width": 100},
        {"label": "Security Deposit Status", "fieldname": "security_deposit_status", "fieldtype": "Select", "width": 100},
        {"label": "Payment Status", "fieldname": "payment_status", "fieldtype": "Select", "width": 100},
        {"label": "SO Type", "fieldname": "so_type", "fieldtype": "Data", "width": 50},
        # Add more columns as needed
    ]

    # Extract filters
    order_types = filters.get("order_type", ["Rental"])  # Defaulting to "Rental" if not provided
    date_range = filters.get("order_date")
    customer = filters.get("customer")
    statuses = filters.get("status", [])

    # print("Debug: Order Types:", order_types)
    # print("Debug: Date Range:", date_range)
    # print("Debug: Customer:", customer)
    # print("Debug: Statuses:", statuses)

    # Initialize conditions
    conditions = {}

    # Apply filters if they exist
    if order_types:
        conditions["order_type"] = ("in", order_types)
    if customer:
        conditions["customer"] = customer
    if date_range:
        if isinstance(date_range, list) and len(date_range) == 2:
            start_date, end_date = date_range
            conditions["transaction_date"] = ("between", [start_date, end_date])
    if statuses:
        conditions["status"] = ("in", statuses)

    print("Debug: Conditions:", conditions)

    # Fetch sales order records from the database based on the selected filters
    sales_orders = frappe.get_all("Sales Order", fields=["name", "customer", "transaction_date", "order_type", "customer_name", "status","security_deposit_status","payment_status","total_rental_amount","outstanding_security_deposit_amount","paid_security_deposite_amount","received_amount","balance_amount","is_renewed"], filters=conditions)

    print("Debug: Sales Orders:", sales_orders)

    # Prepare the data to be displayed
    data = []
    for order in sales_orders:
        so_type = "M" if order.is_renewed == 0 else "R"
        row = {
            "name": order.name,
            "customer": order.customer,
            "order_date": order.transaction_date,
            "order_type": order.order_type,
            "customer_name": order.customer_name,
            "status": order.status,
            "total_rental_amount": order.total_rental_amount,
            "security_deposit_status": order.security_deposit_status,
            "payment_status": order.payment_status,
            "paid_amount": order.paid_security_deposite_amount + order.received_amount,
            "unpaid_amount": order.outstanding_security_deposit_amount + order.balance_amount,
            "so_type": so_type,
            # Add more fields as needed
        }
        data.append(row)
        
    html_card = f"""
 
 
    <script>
        document.addEventListener('click', function(event) {{
            // Check if the clicked element is a cell
            var clickedCell = event.target.closest('.dt-cell__content');
            if (clickedCell) {{
                // Remove highlight from previously highlighted cells
                var previouslyHighlightedCells = document.querySelectorAll('.highlighted-cell');
                previouslyHighlightedCells.forEach(function(cell) {{
                    cell.classList.remove('highlighted-cell');
                    cell.style.backgroundColor = ''; // Remove background color
                    cell.style.border = ''; // Remove border
                    cell.style.fontWeight = '';
                }});
                
                // Highlight the clicked row's cells
                var clickedRow = event.target.closest('.dt-row');
                var cellsInClickedRow = clickedRow.querySelectorAll('.dt-cell__content');
                cellsInClickedRow.forEach(function(cell) {{
                    cell.classList.add('highlighted-cell');
                    cell.style.backgroundColor = '#d7eaf9'; // Light blue background color
                    cell.style.border = '2px solid #90c9e3'; // Border color
                    cell.style.fontWeight = 'bold';
                }});
            }}
        }});
 
 
 
    
    </script>
    """

    return columns, data, html_card
