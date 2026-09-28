"""Endpoints for the technician staff app.

Every function here resolves the caller to a `Technician Details` record, proves
the document belongs to them, and only then delegates to the existing desk
functions. The desk keeps calling `nhk.custom_script` and the ERPNext fork
directly; nothing in this module widens what those already allow.

Two rules that the desk does not enforce and this module does:

* **The caller never sets the payout.** `change_status` accepts a `charges`
  argument and writes it straight through; no function here exposes it, so the
  slab calculation in `TechnicianVisitEntry.validate` stays the only source.
* **Distance is a required whole number.** It defaulted silently to 1.0, which is
  why 41% of visits are priced at the bottom slab. Whole numbers also keep the
  payout slabs gapless -- their boundaries are integers, so `7.3` can fall
  between two rows and leave the charge untouched.

Two gates run ahead of every read and every write:

* **Duty.** Off duty there is nothing to read. `my_jobs` and `job` refuse rather
  than returning a filtered view, so a phone that is not on shift is not holding
  patient names, addresses, phone numbers and outstanding balances on screen.
* **Acceptance.** The office assigns a job; the technician answers it. Until
  `accept_job` lands, `check_in` and `complete_job` refuse. A rejection is
  recorded with its reason and leaves the visit assigned -- reassignment is the
  office's call, not the app's.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, flt, get_datetime, now_datetime, today

from nhk.api.guards import (
	RESPONSE_ACCEPTED,
	RESPONSE_PENDING,
	RESPONSE_REJECTED,
	assert_accepted,
	assert_on_duty,
	assert_open,
	current_technician,
	open_duty,
	owned_visit,
	response_of,
)
from nhk.api import visits

#: Jobs older than this drop out of the day list into the backlog. The open queue
#: is full of jobs nobody intends to do -- 366 of 437 are over a month old -- and
#: showing them all makes the list useless on day one.
DAY_LIST_WINDOW_DAYS = 7

#: How long a technician may reverse their own check-in. Long enough for a
#: mis-tap, short enough that an arrival time stays meaningful.
UNDO_WINDOW_MINUTES = 15

#: Re-exported: `my_stats` and `job` read it, and callers have imported it
#: from here since before the completion routine moved to `visits`.
COMPLETION_STATUS = visits.COMPLETION_STATUS


# ---------------------------------------------------------------------------
# reading the day
# ---------------------------------------------------------------------------


@frappe.whitelist()
def my_jobs(include_backlog=False):
	"""Open jobs for the calling technician.

	Returns the day list by default: everything assigned and scheduled (or, with
	no schedule, created) within the last `DAY_LIST_WINDOW_DAYS`. Pass
	`include_backlog` for the older ones.

	Refuses off duty -- see the module docstring.
	"""
	technician = current_technician()
	assert_on_duty(technician)
	cutoff = add_to_date(today(), days=-DAY_LIST_WINDOW_DAYS, as_string=False)

	jobs = frappe.get_all(
		"Technician Visit Entry",
		filters={
			"technician_id": technician,
			"technician_user_id": frappe.session.user,
			"status": "Assigned",
		},
		fields=[
			"name", "type", "status", "sales_order_id",
			"patient_id", "patient_name", "area",
			"scheduled_datetime", "slot", "creation",
			"started_at", "order_notes",
			"technician_response", "technician_response_at", "rejection_reason",
		],
		order_by="scheduled_datetime asc, creation asc",
		limit_page_length=0,
	)

	def is_current(job):
		when = job.get("scheduled_datetime") or job.get("creation")
		return get_datetime(when) >= get_datetime(cutoff)

	if not cint(include_backlog):
		jobs = [j for j in jobs if is_current(j)]

	# A rejected job stays assigned so the office can reassign it, but it is no
	# longer this technician's to do. Filtered here rather than in the query
	# because rows created before the field existed carry NULL, not "Pending".
	jobs = [j for j in jobs if response_of(j) != RESPONSE_REJECTED]

	for job in jobs:
		job["is_backlog"] = not is_current(job)
		job["patient_mobile"] = frappe.db.get_value("Customer", job.get("patient_id"), "mobile_no")

	return jobs


#: Everything `TechnicianVisit` in the app reads off a list row.
VISIT_LIST_FIELDS = [
	"name", "type", "status", "sales_order_id", "item_code",
	"patient_id", "patient_name", "area",
	"technician_id", "technician_name", "technician_mobile_no", "technician_user_id",
	"technician_category", "kilometers", "charges", "payment_status",
	"scheduled_datetime", "slot", "started_at", "completed_at",
	"created_datetime", "technician_update_datetime", "creation",
	"notes", "order_notes",
	"technician_response", "technician_response_at", "rejection_reason",
]


@frappe.whitelist()
def my_visits(limit=100):
	"""Every visit that is the caller's, newest first -- the app's list screen.

	`my_jobs` answers "what is on today". This answers "what is mine at all",
	finished ones included, because the app counts and filters them. Both refuse
	off duty, which is the point of routing the list through here rather than
	through `frappe.client.get_list`: the doctype's own row permissions let a
	technician read their visits whatever the time of day, and the phone should
	not.
	"""
	technician = current_technician()
	assert_on_duty(technician)

	visits = frappe.get_all(
		"Technician Visit Entry",
		filters={"technician_id": technician, "technician_user_id": frappe.session.user},
		fields=VISIT_LIST_FIELDS,
		order_by="created_datetime desc, creation desc",
		limit_page_length=cint(limit) or 100,
	)

	# Rejected jobs belong to the office now -- same rule as `my_jobs`.
	return [v for v in visits if response_of(v) != RESPONSE_REJECTED]


@frappe.whitelist()
def job(visit_id):
	"""One job, with the order detail the technician needs on the doorstep.

	Refuses off duty -- see the module docstring.
	"""
	technician = current_technician()
	assert_on_duty(technician)

	visit = owned_visit(visit_id, technician=technician)

	from nhk.custom_script import get_sales_order_details

	detail = get_sales_order_details(visit.sales_order_id) if visit.sales_order_id else {}

	# The desk call returns the full ledger. A technician needs to know what is
	# outstanding, not every journal and payment entry behind it.
	for key in ("payment_entries", "journal_entries", "all_payment_entries"):
		detail.pop(key, None)

	checkin = _open_visit_checkin(visit.technician_id, visit.name)

	return {
		"visit": {
			"name": visit.name,
			"type": visit.type,
			"status": visit.status,
			"sales_order_id": visit.sales_order_id,
			"patient_id": visit.patient_id,
			"patient_name": visit.patient_name,
			"patient_mobile": frappe.db.get_value("Customer", visit.patient_id, "mobile_no"),
			"area": visit.area,
			"scheduled_datetime": visit.scheduled_datetime,
			"slot": visit.slot,
			"started_at": visit.started_at,
			"completed_at": visit.completed_at,
			"technician_update_datetime": visit.technician_update_datetime,
			"created_datetime": visit.created_datetime,
			"kilometers": visit.kilometers,
			"charges": visit.charges,
			"extra_payment": visit.extra_payment,
			"extra_payment_reason": visit.extra_payment_reason,
			"extra_payment_note": visit.extra_payment_note,
			"notes": visit.notes,
			"order_notes": visit.order_notes,
			"technician_response": response_of(visit),
			"technician_response_at": visit.technician_response_at,
			"rejection_reason": visit.rejection_reason,
		},
		"order": detail,
		# The app must not carry a second copy of the transition table: a type it
		# cannot close is one this map has no entry for, whatever the desk does.
		"completion_status": COMPLETION_STATUS.get(visit.type),
		"checked_in": bool(checkin),
		# The id and the time, not just the flag: without them the app cannot
		# offer the undo, and it would have to guess at the window.
		"checkin": checkin,
		"undo_window_minutes": UNDO_WINDOW_MINUTES,
		# In the same round trip as the rest: the attachment list is one more
		# thing the doorstep screen renders, and a second call would show it
		# arriving late on a slow connection.
		"attachments": _attachments_of(visit.name),
		"on_duty": True,
	}


@frappe.whitelist()
def my_stats(from_date=None, to_date=None):
	"""Completed job count. Deliberately no money: distances are not yet honest
	enough for a rupee figure to survive an argument."""
	technician = current_technician()
	filters = {
		"technician_id": technician,
		"status": ("in", list(COMPLETION_STATUS.values())),
	}
	if from_date:
		filters["technician_update_datetime"] = (">=", from_date)
	if to_date:
		filters["technician_update_datetime"] = ("<=", to_date)

	return {"completed": frappe.db.count("Technician Visit Entry", filters)}


# ---------------------------------------------------------------------------
# check-in
# ---------------------------------------------------------------------------


#: Duty lookup lives in `guards` because `assert_on_duty` needs it and this
#: module imports from there, not the other way round.
_open_duty = open_duty


def _open_visit_checkin(technician, visit_id=None):
	filters = {
		"technician_id": technician,
		"kind": "Visit",
		"closed_at": ("is", "not set"),
	}
	if visit_id:
		filters["visit_entry"] = visit_id
	return frappe.db.get_value(
		"Technician Check In", filters, ["name", "visit_entry", "checked_in_at"], as_dict=True
	)


def _record_checkin(technician, kind, visit_entry=None, latitude=None, longitude=None,
					accuracy=None, is_mocked=0):
	doc = frappe.get_doc({
		"doctype": "Technician Check In",
		"technician_id": technician,
		"technician_user_id": frappe.session.user,
		"kind": kind,
		"visit_entry": visit_entry,
		"checked_in_at": now_datetime(),
		# Location is recorded, never enforced. Only a fraction of patient
		# addresses carry coordinates, so there is nothing to check against --
		# but the trail is impossible to backfill later.
		"latitude": flt(latitude) if latitude not in (None, "") else None,
		"longitude": flt(longitude) if longitude not in (None, "") else None,
		"accuracy": flt(accuracy) if accuracy not in (None, "") else None,
		"is_mocked": cint(is_mocked),
	}).insert()
	return doc


def _close_checkin(name, reason, latitude=None, longitude=None, accuracy=None, is_mocked=0):
	"""Close a check-in, recording where the technician was if the phone said.

	Going off duty is a reported event the same way going on duty is, so it
	carries the same coordinates. A check-in closed by the system -- superseded
	by the next arrival, or rolled into a completion -- has no location of its
	own and leaves the columns empty.
	"""
	update = {"closed_at": now_datetime(), "close_reason": reason}

	# Float columns are NOT NULL in Frappe, so "no fix" has to mean "leave the
	# column alone" rather than writing a null -- or a zero, which reads as a
	# real position off the coast of Africa.
	for field, value in (
		("closed_latitude", latitude),
		("closed_longitude", longitude),
		("closed_accuracy", accuracy),
	):
		if value not in (None, ""):
			update[field] = flt(value)

	if update.get("closed_latitude") is not None:
		update["closed_is_mocked"] = cint(is_mocked)

	frappe.db.set_value("Technician Check In", name, update)


@frappe.whitelist()
def duty_status():
	technician = current_technician()
	duty = _open_duty(technician)
	visit = _open_visit_checkin(technician)
	return {
		"on_duty": bool(duty),
		"since": duty.checked_in_at if duty else None,
		"open_visit": visit.visit_entry if visit else None,
	}


@frappe.whitelist()
def start_duty(latitude=None, longitude=None, accuracy=None, is_mocked=0):
	"""Begin the working day. Idempotent -- a second call returns the same record.

	Paired with `end_duty`: the app toggles duty, and both edges record where the
	technician was.
	"""
	technician = current_technician()

	existing = _open_duty(technician)
	if existing:
		return {"name": existing.name, "kind": "Duty", "checked_in_at": existing.checked_in_at,
				"already_on_duty": True}

	doc = _record_checkin(technician, "Duty", latitude=latitude, longitude=longitude,
						  accuracy=accuracy, is_mocked=is_mocked)
	return {"name": doc.name, "kind": doc.kind, "checked_in_at": doc.checked_in_at,
			"already_on_duty": False}


@frappe.whitelist()
def end_duty(latitude=None, longitude=None, accuracy=None, is_mocked=0):
	"""End the working day. Idempotent -- a second call reports the same thing.

	Any visit the technician is still standing in is closed with them: an open
	arrival outlives the shift otherwise, and "where is this technician right
	now" would keep answering with a job they left hours ago. The arrival itself
	stays on the visit; only the check-in closes.
	"""
	technician = current_technician()

	duty = _open_duty(technician)
	if not duty:
		return {"on_duty": False, "already_off_duty": True, "closed_visit": None}

	open_visit = _open_visit_checkin(technician)
	if open_visit and open_visit.name:
		_close_checkin(open_visit.name, "Day ended")

	_close_checkin(
		duty.name, "Day ended", latitude=latitude, longitude=longitude,
		accuracy=accuracy, is_mocked=is_mocked,
	)

	return {
		"on_duty": False,
		"already_off_duty": False,
		"closed_visit": open_visit.visit_entry if open_visit else None,
	}


# ---------------------------------------------------------------------------
# accepting the job
# ---------------------------------------------------------------------------


@frappe.whitelist()
def accept_job(visit_id):
	"""Take a job on. Idempotent -- accepting twice is not an error.

	Acceptance is what the office watches to know a job is actually moving, so
	it is a distinct step from arriving: a technician can accept the day's work
	from the depot and drive to the first address afterwards.
	"""
	technician = current_technician()
	assert_on_duty(technician)

	visit = owned_visit(visit_id, technician=technician)
	assert_open(visit)

	response = response_of(visit)
	if response == RESPONSE_REJECTED:
		frappe.throw(_("You rejected this job. The office has to reassign it before you can take it."))
	if response == RESPONSE_ACCEPTED:
		return {"name": visit.name, "technician_response": RESPONSE_ACCEPTED,
				"technician_response_at": visit.technician_response_at, "already_accepted": True}

	responded_at = now_datetime()
	frappe.db.set_value("Technician Visit Entry", visit.name, {
		"technician_response": RESPONSE_ACCEPTED,
		"technician_response_at": responded_at,
		"rejection_reason": None,
	})

	return {"name": visit.name, "technician_response": RESPONSE_ACCEPTED,
			"technician_response_at": responded_at, "already_accepted": False}


@frappe.whitelist()
def reject_job(visit_id, reason):
	"""Hand a job back, with a reason the office can act on.

	The visit stays `Assigned` and stays on this technician: reassignment is an
	office decision, and clearing the technician here would strip the shares the
	desk hands out and lose who was asked in the first place. It simply drops
	out of `my_jobs`.

	A job already under way cannot be handed back -- arriving is a commitment,
	and the stock state behind a half-done delivery is not the app's to unwind.
	"""
	technician = current_technician()
	assert_on_duty(technician)

	visit = owned_visit(visit_id, technician=technician)
	assert_open(visit)

	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Say why you are rejecting this job so the office can reassign it."))

	if _open_visit_checkin(technician, visit.name):
		frappe.throw(_("You have already arrived at this job. Call the office instead."))

	responded_at = now_datetime()
	frappe.db.set_value("Technician Visit Entry", visit.name, {
		"technician_response": RESPONSE_REJECTED,
		"technician_response_at": responded_at,
		"rejection_reason": reason,
	})

	return {"name": visit.name, "technician_response": RESPONSE_REJECTED,
			"technician_response_at": responded_at, "rejection_reason": reason}


@frappe.whitelist()
def check_in(visit_id, latitude=None, longitude=None, accuracy=None, is_mocked=0):
	"""Record arrival at one job."""
	technician = current_technician()

	if not _open_duty(technician):
		frappe.throw(_("Start your day before checking in to a job."))

	visit = owned_visit(visit_id, technician=technician)
	assert_open(visit)
	assert_accepted(visit)

	# One open visit check-in at a time, so "where is this technician right now"
	# has a single answer. Auto-closing is recorded distinctly from a completion
	# so that arrival times stay interpretable.
	open_elsewhere = _open_visit_checkin(technician)
	if open_elsewhere and open_elsewhere.name:
		_close_checkin(open_elsewhere.name, "Auto closed")

	doc = _record_checkin(technician, "Visit", visit_entry=visit.name, latitude=latitude,
						  longitude=longitude, accuracy=accuracy, is_mocked=is_mocked)

	arrival = {"started_at": doc.checked_in_at}
	# Float columns are NOT NULL -- see `_close_checkin`. A phone with no fix
	# arrives without coordinates, and writing its nulls here threw an
	# IntegrityError that stopped the technician checking in at all.
	if doc.latitude is not None and doc.longitude is not None:
		arrival.update(start_latitude=doc.latitude, start_longitude=doc.longitude)
	frappe.db.set_value("Technician Visit Entry", visit.name, arrival)

	return {"name": doc.name, "kind": doc.kind, "visit_entry": visit.name,
			"checked_in_at": doc.checked_in_at}


@frappe.whitelist()
def undo_check_in(checkin_id):
	"""Reverse a visit check-in within `UNDO_WINDOW_MINUTES`.

	Only check-ins. Reversing a completion would mean unwinding stock state --
	`make_delivered` flips items to Rented Out -- which belongs with an admin.
	"""
	technician = current_technician()

	doc = frappe.get_doc("Technician Check In", checkin_id)
	if doc.technician_id != technician:
		frappe.throw(_("Check-in {0} not found.").format(checkin_id), frappe.DoesNotExistError)
	if doc.kind != "Visit":
		frappe.throw(_("Only a job check-in can be undone."))
	if doc.closed_at:
		frappe.throw(_("That check-in is already closed."))

	deadline = add_to_date(get_datetime(doc.checked_in_at), minutes=UNDO_WINDOW_MINUTES, as_string=False)
	if now_datetime() > get_datetime(deadline):
		frappe.throw(
			_("A check-in can only be undone within {0} minutes. Ask the office to correct it.")
			.format(UNDO_WINDOW_MINUTES)
		)

	_close_checkin(doc.name, "Reversed by technician")
	# Float columns are NOT NULL in Frappe, so the coordinates zero out rather
	# than clear; `started_at` going empty is what marks the arrival undone.
	frappe.db.set_value("Technician Visit Entry", doc.visit_entry, {
		"started_at": None, "start_latitude": 0, "start_longitude": 0
	})
	return {"name": doc.name, "undone": True}


# ---------------------------------------------------------------------------
# completion
# ---------------------------------------------------------------------------


@frappe.whitelist()
def complete_job(visit_id, kilometers, notes=None, latitude=None, longitude=None,
				 payment_pending_reason=None, extra_payment=None, extra_payment_reason=None,
				 extra_payment_note=None):
	"""Finish a job: the visit and its Sales Order, together or not at all.

	Note the absent `charges` argument -- see the module docstring.

	The closing itself is `nhk.api.visits.complete_visit`, shared with the
	desk. What is the app's own is the gates in front of it: duty, ownership,
	acceptance, and a check-in -- the office closes visits nobody arrived at,
	the app does not.

	`extra_payment` is what the technician is owed beyond the visit's charge --
	out of station, waiting -- with a reason, and a note for "Other". It is paid
	with the month's payout (`nhk.api.payouts`); the office can correct it
	until then.
	"""
	technician = current_technician()
	assert_on_duty(technician)
	visit = owned_visit(visit_id, technician=technician)

	if visit.status != "Assigned":
		# The desk completes 97% of visits today and both paths stay live during
		# the pilot, so this is a routine race, not a corruption.
		frappe.throw(
			_("The office already marked this job {0}. Nothing more to do here.")
			.format(visit.status)
		)

	assert_accepted(visit)

	if not _open_visit_checkin(technician, visit.name):
		frappe.throw(_("Check in at the job before completing it."))

	if not COMPLETION_STATUS.get(visit.type):
		frappe.throw(_("The app cannot complete a {0} visit.").format(visit.type))

	completed_at = visits.complete_visit(
		visit, kilometers, notes=notes, latitude=latitude, longitude=longitude,
		extra={"amount": extra_payment, "reason": extra_payment_reason, "note": extra_payment_note},
	)

	return {"name": visit.name, "status": visit.status, "kilometers": visit.kilometers,
			"charges": visit.charges, "completed_at": completed_at,
			"extra_payment": visit.extra_payment, "extra_payment_reason": visit.extra_payment_reason}


# ---------------------------------------------------------------------------
# attachments
# ---------------------------------------------------------------------------

#: What the technician may attach from the doorstep. Photos are what this is
#: actually for -- a delivered device, a meter reading, a signed handover slip --
#: but the office also asks for the odd PDF, so documents are allowed too.
#: Anything executable or unopenable at the desk is refused here rather than
#: leaving the office with a file nobody can read.
ATTACHMENT_EXTENSIONS = (
	".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif",
	".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt", ".csv",
)

#: Phone cameras write 3-8 MB a frame, so this is roughly two untouched photos.
#: Large enough that a technician never has to think about it, small enough that
#: a bad upload on 3G fails in seconds rather than minutes.
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

#: Attachments are private files. A delivery photo has a patient's doorway in it
#: and `/files/` is served to anyone with the URL.
ATTACHMENT_IS_PRIVATE = 1


def _attachments_of(visit_name):
	"""Files hanging off one visit, oldest first.

	`ignore_permissions`: the `NHK Technician` role has read-on-own-record and
	nothing else, so the File rows are invisible to the technician who just
	uploaded them. Ownership was already proved by `owned_visit` before this is
	reached.
	"""
	return frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Technician Visit Entry",
			"attached_to_name": visit_name,
		},
		fields=["name", "file_name", "file_url", "file_size", "is_private", "owner", "creation"],
		order_by="creation asc",
		ignore_permissions=True,
	)


@frappe.whitelist()
def job_attachments(visit_id):
	"""Everything attached to one job. Same gates as reading the job itself."""
	technician = current_technician()
	assert_on_duty(technician)
	visit = owned_visit(visit_id, technician=technician)

	return _attachments_of(visit.name)


@frappe.whitelist()
def attach_to_job(visit_id=None):
	"""Attach one file the phone posted to a job.

	Multipart, not JSON: the file arrives as the `file` part and `visit_id` as an
	ordinary form field, so `frappe.form_dict` is the fallback for callers that
	cannot set a query string on a multipart POST.

	Deliberately not `frappe.handler.upload_file`: that one checks *write*
	permission on the target document, and the `NHK Technician` role has read
	only. Ownership here is the same test every other write in this module makes
	-- the visit is the caller's, they accepted it, and it is still open -- and
	the File is then saved with permissions ignored.
	"""
	visit_id = visit_id or frappe.form_dict.get("visit_id")
	if not visit_id:
		frappe.throw(_("No job was named for this attachment."))

	technician = current_technician()
	assert_on_duty(technician)
	visit = owned_visit(visit_id, technician=technician)
	# An attachment is field work like any other: the office owns the job once it
	# is closed, and a photo arriving after that has no one watching for it.
	assert_open(visit)
	assert_accepted(visit)

	uploaded = (frappe.request.files or {}).get("file") if frappe.request else None
	if uploaded is None:
		frappe.throw(_("No file was received. Pick the file again."))

	filename = (uploaded.filename or "").strip()
	content = uploaded.stream.read()

	_validated_attachment(filename, content)

	doc = frappe.get_doc({
		"doctype": "File",
		"attached_to_doctype": "Technician Visit Entry",
		"attached_to_name": visit.name,
		"folder": "Home/Attachments",
		"file_name": filename,
		"is_private": ATTACHMENT_IS_PRIVATE,
		"content": content,
	}).insert(ignore_permissions=True)

	return {
		"name": doc.name,
		"file_name": doc.file_name,
		"file_url": doc.file_url,
		"file_size": doc.file_size,
		"is_private": doc.is_private,
		"owner": doc.owner,
		"creation": doc.creation,
		"visit_id": visit.name,
	}


@frappe.whitelist()
def remove_job_attachment(visit_id, file_id):
	"""Drop an attachment the caller uploaded to their own open job.

	Only their own: a file the office put on the visit is not the technician's
	to delete, and a closed job is nobody's to change from the app. This exists
	so a mis-picked photo costs a tap rather than a phone call.
	"""
	technician = current_technician()
	assert_on_duty(technician)
	visit = owned_visit(visit_id, technician=technician)
	assert_open(visit)

	attachment = frappe.db.get_value(
		"File", file_id,
		["name", "owner", "attached_to_doctype", "attached_to_name"],
		as_dict=True,
	)
	# Same message for "not there" and "not yours" -- see `owned_visit`.
	missing = (
		not attachment
		or attachment.attached_to_doctype != "Technician Visit Entry"
		or attachment.attached_to_name != visit.name
	)
	if missing:
		frappe.throw(_("Attachment {0} not found.").format(file_id), frappe.DoesNotExistError)

	if attachment.owner != frappe.session.user:
		frappe.throw(_("That file was not uploaded from this app. Ask the office to remove it."))

	frappe.delete_doc("File", attachment.name, ignore_permissions=True, delete_permanently=True)
	return {"name": file_id, "removed": True}


def _validated_attachment(filename, content):
	"""Reject what the office cannot open, and what the phone should not send."""
	if not filename:
		frappe.throw(_("That file has no name. Pick it again."))

	if not content:
		frappe.throw(_("That file is empty."))

	if len(content) > MAX_ATTACHMENT_BYTES:
		frappe.throw(
			_("{0} is too large. Attachments are limited to {1} MB.")
			.format(filename, MAX_ATTACHMENT_BYTES // (1024 * 1024))
		)

	if not filename.lower().endswith(ATTACHMENT_EXTENSIONS):
		frappe.throw(
			_("{0} cannot be attached. Allowed: {1}.")
			.format(filename, ", ".join(e.lstrip(".") for e in ATTACHMENT_EXTENSIONS))
		)
