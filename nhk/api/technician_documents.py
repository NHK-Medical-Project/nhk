"""A technician's own documents, for the NHK Technician app (`nhk.api.technician_documents`).

Licence, RC, insurance, PUC and anything else a technician may be asked to
show at a roadside check. The phone keeps a copy so they open without signal;
the office reads them in the `documents` table on the technician's **NHK User**
(decided 2026-10-15, replacing the separate `Technician Document` doctype).

The rows are written as child rows directly, never by saving the NHK User:
saving a submitted NHK User resets the login's password and rebuilds its roles
(see `nhk.api.devices`). Each file is a private `File` attached to the NHK User.

Not gated on duty, unlike `nhk.api.staff`'s job reads: these are the
technician's own papers, not a patient's details, and they are needed most on
the way to and from work. No rules beyond the file check job attachments use
(decided 2026-10-14).
"""

import frappe
from frappe import _

from nhk.api.devices import nhk_user_of
from nhk.api.guards import current_technician
from nhk.api.staff import ATTACHMENT_IS_PRIVATE, _validated_attachment

PARENT = "NHK User"
DOCUMENT = "NHK User Document"
PARENTFIELD = "documents"


def _caller_nhk_user():
	"""The caller's NHK User. Only technicians use this API."""
	current_technician()
	nhk_user = nhk_user_of(frappe.session.user)
	if not nhk_user:
		frappe.throw(
			_("{0} has no NHK User record, so documents cannot be saved. Ask the office to create one.").format(
				frappe.session.user
			)
		)
	return nhk_user


def _row_filters(nhk_user):
	return {"parent": nhk_user, "parenttype": PARENT, "parentfield": PARENTFIELD}


def _owned(document_id, nhk_user):
	"""The caller's row, or the same not-found for "missing" and "not yours"."""
	if document_id and frappe.db.exists(DOCUMENT, {"name": document_id, **_row_filters(nhk_user)}):
		return document_id
	frappe.throw(_("Document {0} not found.").format(document_id), frappe.DoesNotExistError)


def _file_of(nhk_user, file_url):
	if not file_url:
		return None
	return frappe.db.get_value(
		"File",
		{"attached_to_doctype": PARENT, "attached_to_name": nhk_user, "file_url": file_url},
		["name", "file_name", "file_size"],
		as_dict=True,
	)


def _rows(nhk_user, names=None):
	filters = _row_filters(nhk_user)
	if names is not None:
		filters["name"] = ("in", names)
	docs = frappe.get_all(
		DOCUMENT,
		filters=filters,
		fields=["name", "document_type", "title", "vehicle_number", "file", "modified"],
		order_by="creation desc",
	)
	for d in docs:
		f = _file_of(nhk_user, d.file) or {}
		d.file_url = d.pop("file")
		d.file_name = f.get("file_name")
		d.file_size = f.get("file_size")
	return docs


def _add_document_row(nhk_user, document_type, title, vehicle_number, file_url):
	"""Append a document row to an NHK User without saving the NHK User."""
	last_idx = frappe.db.sql(
		"select coalesce(max(idx), 0) from `tabNHK User Document` where parent = %s and parentfield = %s",
		(nhk_user, PARENTFIELD),
	)[0][0]
	row = frappe.get_doc({
		"doctype": DOCUMENT,
		"parent": nhk_user,
		"parenttype": PARENT,
		"parentfield": PARENTFIELD,
		"idx": last_idx + 1,
		"document_type": document_type,
		"title": title,
		"vehicle_number": vehicle_number,
		"file": file_url,
	})
	# Rows of a submitted document carry its docstatus, as a normal save would give them.
	row.docstatus = frappe.db.get_value(PARENT, nhk_user, "docstatus")
	row.db_insert()
	return row.name


@frappe.whitelist()
def my_documents():
	"""The caller's documents, newest first."""
	return _rows(_caller_nhk_user())


@frappe.whitelist()
def upload_document(document_type=None, title=None, vehicle_number=None):
	"""Save one document the phone posted.

	Multipart, as `staff.attach_to_job`: the file is the `file` part and the
	rest are form fields, read from `frappe.form_dict` when not passed.
	"""
	nhk_user = _caller_nhk_user()
	form = frappe.form_dict
	document_type = document_type or form.get("document_type") or "Other"
	title = (title or form.get("title") or "").strip() or None
	vehicle_number = (vehicle_number or form.get("vehicle_number") or "").strip().upper() or None

	uploaded = (frappe.request.files or {}).get("file") if frappe.request else None
	if uploaded is None:
		frappe.throw(_("No file was received. Pick the file again."))
	filename = (uploaded.filename or "").strip()
	content = uploaded.stream.read()
	_validated_attachment(filename, content)

	file = frappe.get_doc({
		"doctype": "File",
		"attached_to_doctype": PARENT,
		"attached_to_name": nhk_user,
		"attached_to_field": PARENTFIELD,
		"file_name": filename,
		"is_private": ATTACHMENT_IS_PRIVATE,
		"content": content,
	}).insert(ignore_permissions=True)
	name = _add_document_row(nhk_user, document_type, title, vehicle_number, file.file_url)

	return _rows(nhk_user, [name])[0]


@frappe.whitelist()
def delete_document(document_id):
	"""Delete one of the caller's documents and its file."""
	nhk_user = _caller_nhk_user()
	name = _owned(document_id, nhk_user)
	file = _file_of(nhk_user, frappe.db.get_value(DOCUMENT, name, "file"))
	if file:
		frappe.delete_doc("File", file.name, ignore_permissions=True, delete_permanently=True)
	frappe.db.delete(DOCUMENT, {"name": name})
	return {"name": name, "removed": True}
