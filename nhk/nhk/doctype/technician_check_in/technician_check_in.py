import frappe
from frappe.model.document import Document


class TechnicianCheckIn(Document):
	"""A technician's check-in, either for the day (Duty) or at one job (Visit).

	Written only through `nhk.api.staff`; every field is read-only in the form so
	that a check-in cannot be back-dated or relocated after the fact.
	"""

	def validate(self):
		if self.kind == "Visit" and not self.visit_entry:
			frappe.throw(frappe._("A Visit check-in must name a visit entry."))
		if self.kind == "Duty" and self.visit_entry:
			frappe.throw(frappe._("A Duty check-in cannot name a visit entry."))
		if self.closed_at and not self.close_reason:
			frappe.throw(frappe._("A closed check-in must say why it closed."))
