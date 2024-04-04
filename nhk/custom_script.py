import frappe


@frappe.whitelist()
def fetch_asset_id(item_code):
    asset_id = frappe.db.get_value('Asset', {'item_code': item_code}, 'name')
    return asset_id