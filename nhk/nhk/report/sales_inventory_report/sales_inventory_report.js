frappe.query_reports["Sales Inventory Report"] = {
    filters: [
        {
            fieldname: "status",
            label: __("Status"),
            fieldtype: "Select",
            options: [
                { "label": "All", "value": "" }, // Option to select all records
                { "label": "Delivered", "value": "Delivered" },
                { "label": "Active", "value": "active" },
                { "label": "Inactive", "value": "inactive" },
                // Add other statuses as needed
            ],
            default: "",
            reqd: 0
        },
        {
            fieldname: "serial_number",
            label: __("Serial Number"),
            fieldtype: "Link",
            options: "Serial No",
            placeholder: __("Serial Number")
        },
		{
            "fieldname": "item_code",
            "label": __("Item Code"),
            "fieldtype": "Link",
            "options": "Item",
            "get_query": function() {
                return {
                    filters: {
                        "is_stock_item": 1
                    }
                };
            }
        }
    ]
};
