frappe.query_reports["Sales order Report"] = {
    "filters": [
        {
            "fieldname": "order_type",
            "label": __("Order Type"),
            "fieldtype": "MultiSelect",
            "options": ["", "Sales", "Rental", "Service"],
            "default": ["Rental"],
            "reqd": 1
        },
        {
            "fieldname": "order_date",
            "label": __("Date Range"),
            "fieldtype": "DateRange",
            "reqd": 0
        },
        {
            "fieldname": "customer",
            "label": __("Customer"),
            "fieldtype": "Link",
            "options": "Customer",
            "reqd": 0
        },
        {
            "fieldname": "status",
            "label": __("Status"),
            "fieldtype": "MultiSelect",
            "options": ["", "Pending", "Approved", "Rental Device Assigned", "Ready for Delivery", "DISPATCHED", "Active", "Ready for Pickup", "Picked Up", "Submitted to Office", "RENEWED"],
            "reqd": 0  // Optional field
        }
    ],
    "onload": function(report) {
        // Ensure that the order_date filter is passed as a string
        report.get_filter("order_date").$input.on("change", function() {
            const date_range = report.get_filter_value("order_date");
            if (date_range) {
                const formatted_date_range = date_range.map(date => frappe.datetime.str_to_obj(date).toISOString());
                frappe.query_report.filters.find(f => f.fieldname === "order_date").value = formatted_date_range.join(" to ");
            }
        });
    }
};
