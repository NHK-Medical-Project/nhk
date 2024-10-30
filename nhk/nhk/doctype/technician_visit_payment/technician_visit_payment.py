# Copyright (c) 2024, vishnu and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class TechnicianVisitPayment(Document):
	def on_trash(doc):
		# Ensure valid input
		# Ensure valid input
		if doc.payment_done == 1:
			frappe.throw(("You cannot delete this document because the payment has been completed. Please cancel the payment first."))