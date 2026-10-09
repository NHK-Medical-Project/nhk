frappe.query_reports["Consumable Inventory Items"] = {
	"filters": [
		{
			"fieldname": "item_code",
			"label": __("Item Code"),
			"fieldtype": "Link",
			"options": "Item",
			"width": 150,
			"default": null,
			"reqd": 0,
			"get_query": function() {
				return {
					"filters": {
						"item_group": "Sales",
						"is_stock_item": 1,
						"has_serial_no":0,
						"has_batch_no":0
					}
				};
			}
		}
	]
};
