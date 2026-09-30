# Copyright (c) 2026, vishnu and contributors
# For license information, please see license.txt

"""One month of technician pay: what each technician earned, and whether it is final.

The figures are built and processed by `nhk.api.payouts`; this controller only
keeps them consistent and keeps a processed month from changing afterwards.
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class TechnicianPayoutMonth(Document):
	def validate(self):
		if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", self.month or ""):
			frappe.throw(_("Month must be written as YYYY-MM, for example 2026-08."))

		before = self.get_doc_before_save()
		if before and before.status == "Processed" and not self.flags.processing:
			frappe.throw(_("{0} has been processed and can no longer change.").format(self.name))

		seen = set()
		for row in self.rows:
			if row.technician_id in seen:
				frappe.throw(_("{0} appears twice in {1}.").format(row.technician_id, self.name))
			seen.add(row.technician_id)
			row.total = (
				flt(row.visit_charges) + flt(row.extra_payments)
				+ flt(row.sales_incentive) + flt(row.fixed_incentive)
			)

		self.total_visit_charges = sum(flt(r.visit_charges) for r in self.rows)
		self.total_extra_payments = sum(flt(r.extra_payments) for r in self.rows)
		self.total_sales_incentive = sum(flt(r.sales_incentive) for r in self.rows)
		self.total_fixed_incentive = sum(flt(r.fixed_incentive) for r in self.rows)
		self.grand_total = sum(flt(r.total) for r in self.rows)

	def on_trash(self):
		if self.status == "Processed":
			frappe.throw(_("{0} has been processed and cannot be deleted.").format(self.name))
