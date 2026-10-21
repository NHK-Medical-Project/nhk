"""A technician's own documents (`nhk.api.technician_documents`).

Run:  cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_technician_documents.py
"""

import io
import sys

import frappe

sys.path.insert(0, __file__.rsplit("/", 1)[0])

PILOT_USER = "basawaraja.nhkmedical@gmail.com"
OTHER_USER = "suvam.nirmalhealthcare@gmail.com"

# A one-pixel PNG, as in test_staff_api.
_PNG = bytes.fromhex(
	"89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
	"0000000d49444154789c63f8cfc0f01f00050001ff89993d1d"
	"0000000049454e44ae426082"
)


class _MultipartPost:
	"""Binds `frappe.request` (and `form_dict`) to the phone's multipart POST."""

	def __init__(self, fields, filename, content):
		from werkzeug.test import EnvironBuilder
		from werkzeug.wrappers import Request

		self.fields = fields
		builder = EnvironBuilder(method="POST", data={**fields, "file": (io.BytesIO(content), filename)})
		self.request = Request(builder.get_environ())

	def __enter__(self):
		self._previous = getattr(frappe.local, "request", None)
		self._form = frappe.local.form_dict
		frappe.local.request = self.request
		frappe.local.form_dict = frappe._dict(self.fields)

	def __exit__(self, *exc):
		frappe.local.request = self._previous
		frappe.local.form_dict = self._form


def _upload(cleanup, user=PILOT_USER, filename="licence.png", content=_PNG, **fields):
	from nhk.api import technician_documents as api

	frappe.set_user(user)
	with _MultipartPost(fields, filename, content):
		res = api.upload_document()
	cleanup.add_row("NHK User Document", res["name"])
	file = frappe.db.get_value("File", {"attached_to_doctype": "NHK User", "file_url": res["file_url"]}, "name")
	if file:
		cleanup.add("File", file)
	return res


def test_upload_stores_a_private_file_and_lists_it(cleanup):
	from nhk.api import technician_documents as api

	res = _upload(cleanup, document_type="Insurance", title="Front", vehicle_number="ka 01 ab 1234")

	assert res["document_type"] == "Insurance"
	assert res["vehicle_number"] == "KA 01 AB 1234"
	assert res["file_url"].startswith("/private/files/"), res["file_url"]

	row = frappe.db.get_value("NHK User Document", res["name"], ["parent", "parentfield", "file"], as_dict=True)
	assert row.parent == PILOT_USER and row.parentfield == "documents", row
	assert row.file == res["file_url"], "the desk table's File column is empty"
	attached = frappe.db.get_value("File", {"file_url": res["file_url"]}, ["attached_to_doctype", "attached_to_name"], as_dict=True)
	assert (attached.attached_to_doctype, attached.attached_to_name) == ("NHK User", PILOT_USER), attached

	assert res["name"] in [d.name for d in api.my_documents()]


def test_works_off_duty(cleanup):
	"""The harness closes every check-in, so the pilot is off duty here."""
	from nhk.api import technician_documents as api

	res = _upload(cleanup, document_type="RC")
	assert res["name"] in [d.name for d in api.my_documents()]


def test_a_document_without_a_type_is_other(cleanup):
	assert _upload(cleanup)["document_type"] == "Other"


def test_another_technicians_documents_are_not_listed(cleanup):
	from nhk.api import technician_documents as api

	theirs = _upload(cleanup, user=OTHER_USER, document_type="PUC")
	frappe.set_user(PILOT_USER)
	assert theirs["name"] not in [d.name for d in api.my_documents()]


def test_another_technicians_document_cannot_be_deleted(cleanup):
	from nhk.api import technician_documents as api

	theirs = _upload(cleanup, user=OTHER_USER)
	frappe.set_user(PILOT_USER)
	try:
		api.delete_document(theirs["name"])
	except frappe.DoesNotExistError:
		assert frappe.db.exists("NHK User Document", theirs["name"])
		return
	raise AssertionError("deleted another technician's document")


def test_delete_removes_the_document_and_its_file(cleanup):
	from nhk.api import technician_documents as api

	res = _upload(cleanup)
	file = frappe.db.get_value("File", {"file_url": res["file_url"]}, "name")

	assert api.delete_document(res["name"])["removed"] is True
	assert not frappe.db.exists("NHK User Document", res["name"])
	assert not frappe.db.exists("File", file), "the file outlived its document"


def test_a_file_nobody_can_open_is_refused(cleanup):
	try:
		_upload(cleanup, filename="payload.apk", content=b"not a document")
	except frappe.ValidationError:
		return
	raise AssertionError("accepted an .apk")


def test_uploading_does_not_save_the_nhk_user(cleanup):
	"""Saving a submitted NHK User resets the login's password (`nhk.api.devices`)."""
	before = frappe.db.get_value("NHK User", PILOT_USER, "modified")
	_upload(cleanup)
	assert frappe.db.get_value("NHK User", PILOT_USER, "modified") == before


def test_someone_who_is_not_a_technician_is_refused(cleanup):
	from nhk.api import technician_documents as api
	from nhk.api.guards import NotATechnician

	frappe.set_user("Administrator")
	try:
		api.my_documents()
	except NotATechnician:
		return
	raise AssertionError("Administrator was given a technician's documents")


if __name__ == "__main__":
	import harness
	raise SystemExit(harness.run(sys.modules[__name__]))
