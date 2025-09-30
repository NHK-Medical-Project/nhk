import frappe

def execute(filters=None):
    # Define the columns for the report
    columns = [
        {
            "label": "Item Code",
            "fieldname": "item_code",
            "fieldtype": "Link",
            "options": "Item",
            "width": 150
        },
        {
            "label": "Item Name",
            "fieldname": "item_name",
            "fieldtype": "Data",
            "width": 200
        },
        {
            "label": "In Qty",
            "fieldname": "in_qty",
            "fieldtype": "Float",
            "width": 100
        },
        {
            "label": "Balance Stock",
            "fieldname": "total_qty",
            "fieldtype": "Float",
            "width": 100
        },
        {
            "label": "Out Qty (Sold Stock)",
            "fieldname": "out_qty",
            "fieldtype": "Float",
            "width": 100
        },
        {
            "label": "Warehouse",
            "fieldname": "warehouse",
            "fieldtype": "Link",
            "options": "Warehouse",
            "width": 150
        }
    ]
    
    # Define the filter condition for item_code if it is provided
    conditions = ""
    if filters and filters.get("item_code"):
        conditions += " AND item.item_code = %(item_code)s"

    # Query to fetch total stock, in qty, sold stock (Out Qty), and balance stock
    data = frappe.db.sql(f"""
        SELECT 
            item.item_code, 
            item.item_name, 
            bin.actual_qty as total_qty,
            
            -- Calculate total 'In Qty' from Stock Ledger Entry (total received quantity)
            IFNULL((SELECT SUM(sle.actual_qty) FROM `tabStock Ledger Entry` sle
                    WHERE sle.item_code = item.item_code
                    AND sle.actual_qty > 0
                    AND sle.warehouse = bin.warehouse), 0) as in_qty,
                    
            -- Calculate total 'Out Qty' (Sold Stock) from Stock Ledger Entry (total outgoing quantity)
            IFNULL((SELECT ABS(SUM(sle.actual_qty)) FROM `tabStock Ledger Entry` sle
                    WHERE sle.item_code = item.item_code
                    AND sle.actual_qty < 0
                    AND sle.warehouse = bin.warehouse), 0) as out_qty,
            
            -- Total stock (actual stock in bin is already balance stock)
            bin.warehouse
        FROM 
            `tabItem` as item
        INNER JOIN 
            `tabBin` as bin ON item.item_code = bin.item_code
        WHERE 
            item.is_stock_item = 1
            AND item.has_serial_no != 1
            AND item.has_batch_no != 1
            AND bin.actual_qty > 0
            {conditions} -- Apply item_code filter if provided
    """, filters, as_dict=True)

    return columns, data
