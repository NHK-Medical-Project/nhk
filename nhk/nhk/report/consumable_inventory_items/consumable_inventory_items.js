frappe.query_reports["Consumable Inventory Items"] = {
	"filters": [
		{
			"fieldname": "item_code",
			"label": __("Item Code"),
			"fieldtype": "Link",
			"options": "Item",
			"width": 150,
			"default": null,
			"reqd": 0
		}
	]
};
