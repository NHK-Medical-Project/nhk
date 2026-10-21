# Copyright (c) 2026, vishnu and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class NHKUserDocument(Document):
	"""A paper a technician may have to show at a roadside check: licence, RC,
	insurance, PUC and the like, as a photo or PDF. One row of the `documents`
	table on their NHK User.

	Deliberately rule-free (decided 2026-10-14): no required documents, no
	expiry. Written by `nhk.api.technician_documents`, never by saving the form.
	"""
