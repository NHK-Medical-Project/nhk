"""Store every answer of the public order form on the Sales Order it creates.

Decided 2026-10-19: one public form replaces the two Google Forms (patient
registration, sleep study registration); each submission is a draft Sales
Order (`nhk.api.order_form`). This adds the *Order Form* tab of `custom_of_*`
fields, `custom_from_order_form`, and the placeholder Item every requested
product is booked against until the office picks the real one. Safe to run
again: fields are created or updated, the Item only once.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from nhk.api import order_form as of


def _select(*options):
	return "\n" + "\n".join(options)


def _fields():
	f = []

	def add(fieldname, label, fieldtype="Data", **kw):
		f.append({"fieldname": fieldname, "label": label, "fieldtype": fieldtype,
				  "insert_after": f[-1]["fieldname"] if f else "party_account_currency",
				  "no_copy": 1, "print_hide": 1, "translatable": 0, **kw})

	add("custom_order_form_tab", "Order Form", "Tab Break")
	add("custom_from_order_form", "From Order Form", "Check", read_only=1,
		description="Raised by a sales person through the public order form.")
	add("custom_of_kind", "Type", "Select", options=_select(*of.KINDS), in_standard_filter=1)
	add("custom_of_doctor", "Dr Name & Hospital (as typed)",
		description="Link the Referrer above from this before submitting.")
	add("custom_of_products", "Requested", "Small Text")
	add("custom_of_col_1", None, "Column Break")
	add("custom_of_titration_days", "Titration Days", "Select", options=_select(*of.TITRATION_DAYS))
	add("custom_of_test", "Diagnostic Test", "Select", options=_select(*of.TESTS))
	add("custom_of_delivery_time", "Delivery Time")
	add("custom_of_delivery_remarks", "Delivery Remarks", "Small Text")

	add("custom_of_patient_section", "Patient", "Section Break")
	add("custom_of_patient_name", "Name")
	add("custom_of_age", "Age")
	add("custom_of_gender", "Gender")
	add("custom_of_height", "Height")
	add("custom_of_weight", "Weight")
	add("custom_of_diagnosis", "Diagnosis / Problems", "Small Text")
	add("custom_of_col_2", None, "Column Break")
	add("custom_of_mobile", "Mobile Number")
	add("custom_of_whatsapp", "WhatsApp Number")
	add("custom_of_alternate_mobile", "Alternative Mobile Number")
	add("custom_of_email", "Email", options="Email")

	add("custom_of_address_section", "Address", "Section Break")
	add("custom_of_delivery_address", "Delivery Address", "Small Text")
	add("custom_of_gps_location", "Delivery GPS Location", "Small Text")
	add("custom_of_col_3", None, "Column Break")
	add("custom_of_permanent_address", "Permanent Address", "Small Text")

	add("custom_of_sleep_section", "Sleep Study", "Section Break",
		depends_on="eval:doc.custom_of_test=='Sleep Study Test'")
	add("custom_of_profession", "Profession")
	add("custom_of_languages", "Preferred Language")
	add("custom_of_sleep_time", "Sleep Time", "Time")
	add("custom_of_wake_time", "Wake Up Time", "Time")
	add("custom_of_col_4", None, "Column Break")
	add("custom_of_study_date", "Sleep Study Scheduled For", "Date")
	add("custom_of_symptoms", "Applicable Conditions", "Small Text")
	return f


def execute():
	create_custom_fields({"Sales Order": _fields()}, update=True)

	if not frappe.db.exists("Item", of.PLACEHOLDER_ITEM):
		frappe.get_doc({
			"doctype": "Item",
			"item_code": of.PLACEHOLDER_ITEM,
			"item_name": "Order form request (replace with the actual item)",
			"item_group": "Services",
			"stock_uom": "Nos",
			"is_stock_item": 0,
			"is_sales_item": 1,
			"is_purchase_item": 0,
			"include_item_in_manufacturing": 0,
			# Taxed as NHK's other service Items (Visit, Report, Sleep study) are:
			# india_compliance requires the HSN/SAC code, the fork's Item the
			# mandatory `tax_rate`.
			"gst_hsn_code": "999316",
			"tax_rate": "Non-GST - INR",
			"taxes": [{"item_tax_template": "Non-GST - INR"}],
			"description": "Placeholder for a product asked for on the public order form. "
			"Sales Orders with this item cannot be submitted.",
		}).insert(ignore_permissions=True)
