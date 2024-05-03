import frappe

def execute(filters=None):
    # Define the columns you want to display
    columns = [
        {"label": "Name", "fieldname": "name", "fieldtype": "Link", "options": "Sales Order"},
        {"label": "Order Type", "fieldname": "order_type", "fieldtype": "Data"},
        {"label": "Customer", "fieldname": "customer", "fieldtype": "Link", "options": "Customer"},
        {"label": "Order Date", "fieldname": "order_date", "fieldtype": "Date"},
        # Add more columns as needed
    ]

    # Extract filters
    order_type = filters.get("order_type")
    date_range = filters.get("order_date")

    print("Debug: Order Type:", order_type)
    print("Debug: Date Range:", date_range)

    # Fetch sales order records from the database based on the selected order type and date range
    conditions = {"order_type": order_type}
    if date_range:
        if isinstance(date_range, list) and len(date_range) == 2:
            start_date, end_date = date_range
            conditions["start_date"] = start_date
            conditions["end_date"] = end_date

    print("Debug: Conditions:", conditions)

    # Use Frappe's built-in method to get data
    sales_orders = frappe.db.sql("""SELECT name, customer, transaction_date, order_type
FROM `tabSales Order`
WHERE order_type = %(order_type)s
  AND transaction_date BETWEEN %(start_date)s AND %(end_date)s""", conditions, as_dict=True)

    print("Debug: Sales Orders:", sales_orders)

    # Prepare the data to be displayed
    data = []
    for order in sales_orders:
        row = {
            "name": order.name,
            "customer": order.customer,
            "order_date": order.transaction_date,
            "order_type": order.order_type,
            # Add more fields as needed
        }
        data.append(row)

    return columns, data
