"""Give every Sales Person the token behind their public order form link.

Decided 2026-10-19: each sales person has their own link to the public order
form, `/order-form?token=<token>`; the token says whom a submission is from
(`nhk.api.order_form`). New Sales Persons get one on insert (hooks.py). Safe to
run again: the field is created once and only blank tokens are filled.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from nhk.api.order_form import TOKEN_FIELD, new_token


def execute():
	create_custom_fields(
		{
			"Sales Person": [
				{
					"fieldname": TOKEN_FIELD,
					"label": "Order Form Token",
					"fieldtype": "Data",
					"insert_after": "employee",
					"read_only": 1,
					"unique": 1,
					"no_copy": 1,
					"print_hide": 1,
					"description": "Identifies this sales person's public order form link. "
					"Use New Order Form Link to replace it if the link leaks.",
				}
			]
		},
		update=True,
	)
	for name in frappe.get_all(
		"Sales Person", filters={TOKEN_FIELD: ("in", ("", None))}, pluck="name"
	):
		frappe.db.set_value("Sales Person", name, TOKEN_FIELD, new_token(), update_modified=False)
