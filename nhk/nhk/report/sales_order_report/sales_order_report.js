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
        },
        {
            "fieldname": "referrer",
            "label": "Referrer",
            "fieldtype": "Link",
            "options": "Referrer",
            "reqd": 0,
        },
        {
            "fieldname": "custom_referrer_hospital",
            "label": "Referrer Hospital",
            "fieldtype": "Link",
            "options": "Hospital",
            "reqd": 0,
        },
        {
            "fieldname": "referrer_commission_status",
            "label": "Referrer Commission Status",
            "fieldtype": "Select",
            "options": "\nPending\nCleared",
            "default": "Pending",
            "reqd": 0,
        },
        {
            "fieldname": "sales_person",
            "label": __("Sales Person"),
            "fieldtype": "Link",
            "options": "Sales Person"
        },
        {
            "fieldname": "sales_commission_status",
            "label": __("Sales Commission Status"),
            "fieldtype": "Select",
            "options": "\nPending\nCleared"
        }
    ],
    "onload": function(report) {
        // Ensure that the order_date filter is passed as a string
        report.get_filter("order_date").$input.on("change", function() {
            const date_range = report.get_filter_value("order_date");
            const order_types = report.get_filter_value("order_type");

            if (date_range) {
                const formatted_date_range = date_range.map(date => frappe.datetime.str_to_obj(date).toISOString().split('T')[0]);

                // Determine which date field to use based on order type
                if (order_types.includes("Rental")) {
                    frappe.query_report.filters.find(f => f.fieldname === "order_date").value = formatted_date_range.join(" to ");
                } else {
                    // For Sales and Service
                    frappe.query_report.filters.find(f => f.fieldname === "order_date").value = formatted_date_range.join(" to ");
                }
            }
        });
    }
};




// frappe.query_reports["Sales order Report"] = {
//     "filters": [
//         {
//             "fieldname": "order_type",
//             "label": __("Order Type"),
//             "fieldtype": "MultiSelect",
//             "options": ["", "Sales", "Rental", "Service"],
//             "default": ["Rental"],
//             "reqd": 1
//         },
//         {
//             "fieldname": "order_date",
//             "label": __("Date Range"),
//             "fieldtype": "DateRange",
//             "reqd": 0
//         },
//         {
//             "fieldname": "customer",
//             "label": __("Customer"),
//             "fieldtype": "Link",
//             "options": "Customer",
//             "reqd": 0
//         },
//         {
//             "fieldname": "status",
//             "label": __("Status"),
//             "fieldtype": "MultiSelect",
//             "options": ["", "Pending", "Approved", "Rental Device Assigned", "Ready for Delivery", "DISPATCHED", "Active", "Ready for Pickup", "Picked Up", "Submitted to Office", "RENEWED"],
//             "reqd": 0  // Optional field
//         }
//     ],
//     "onload": function(report) {
//         // Ensure that the order_date filter is passed as a string
//         report.get_filter("order_date").$input.on("change", function() {
//             const date_range = report.get_filter_value("order_date");
//             if (date_range) {
//                 const formatted_date_range = date_range.map(date => frappe.datetime.str_to_obj(date).toISOString());
//                 frappe.query_report.filters.find(f => f.fieldname === "order_date").value = formatted_date_range.join(" to ");
//             }
//         });
//     }
// };
