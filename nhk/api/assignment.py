"""Moving a Technician Visit Entry from one technician to another.

The office assigns a job by creating a visit (`create_technician_portal_entry` in
the ERPNext fork). It reassigns one by changing `technician_id` on that visit --
from the desk form, or through `reassign_visit` here. Neither route used to carry
anything else with it, so a reassigned visit kept the previous technician's
DocShare, their answer and their rejection reason, and the new technician could
not see it at all.

Three facts shape everything below.

* **A technician's access is the DocShare, nothing else.** `NHK Technician` holds
  `read`/`write` with `if_owner: 1`, and the visit is inserted by the office, so
  the technician is never `owner`. Move the share or the job is invisible.
* **A rejection is not in the change log.** `accept_job` and `reject_job` write
  through `frappe.db.set_value`, which creates no Version row. Resetting the
  answer would destroy the only record of it, so the handover is written to the
  document's timeline as a comment first.
* **`technician_category` describes the work, not the worker.** It is an office
  choice made per assignment and `Technician Details` has no such field, so a
  reassignment leaves it alone: the job is the same job. Repricing when it *is*
  changed by hand belongs to `update_technician_charge`, not here.

`sync_assignment` runs on every save, so a plain form edit behaves exactly like a
call to `reassign_visit`. The guard runs in `validate`, where a refusal can still
stop the write.
"""

import frappe
from frappe import _

from nhk.api.guards import RESPONSE_PENDING, response_of

#: Statuses a visit may be moved out of. Past `Assigned` the payout run owns it.
REASSIGNABLE_STATUSES = ("Assigned",)

#: Sales Order fields that name the technician, by the visit `type` that set them.
#: `make_ready_for_delivery`, `make_ready_for_pickup` and `assign_technician` in
#: the ERPNext fork write exactly these, and nothing kept them current afterwards.
SALES_ORDER_FIELDS = {
	"Pickup": ("custom_technician_id_pickup", "technician_id_after_delivered"),
	"Delivery": ("custom_technician_id_before_delivered", "technician_id_before_deliverd"),
	"Service": ("custom_technician_id_before_delivered", "technician_id_before_deliverd"),
	"Technician Assignment For Sales": (
		"custom_technician_id_before_delivered", "technician_id_before_deliverd"),
	"Technician Assignment For Service": (
		"custom_technician_id_before_delivered", "technician_id_before_deliverd"),
}


class VisitInProgress(frappe.ValidationError):
	"""The technician holding this visit has already arrived at it."""


def _moved(doc):
	"""The visit's previous technician, if this save moves it. Otherwise None.

	Returns the `doc_before_save` rather than a bool so callers have the previous
	`technician_user_id` to take the share off.
	"""
	before = doc.get_doc_before_save()

	if not before:
		# An insert. The assignment path shares the visit itself; there is no
		# previous technician to take anything from.
		return None

	if before.technician_id == doc.technician_id:
		return None

	return before


def guard_reassignment(doc, method=None):
	"""Refuse a reassignment that would strand work already under way.

	`reject_job` refuses once a technician has arrived -- "Call the office
	instead" -- and this is the office side of the same rule. A check-in does not
	change `status`, so without this the form would let a visit be moved out from
	under someone standing at the patient's door, leaving their `started_at`,
	their coordinates and their open check-in on a job that is no longer theirs.

	`reassign_visit(force=True)` sets the flag that skips it, and clears that
	state deliberately.
	"""
	before = _moved(doc)
	if not before:
		return

	if doc.status not in REASSIGNABLE_STATUSES:
		frappe.throw(
			_("Visit {0} is {1} and can no longer be reassigned.").format(doc.name, doc.status)
		)

	if doc.flags.get("force_reassign"):
		return

	from nhk.api.staff import _open_visit_checkin

	arrived = _open_visit_checkin(before.technician_id, doc.name)
	if arrived:
		frappe.throw(
			_("{0} has already arrived at visit {1}. Close their check-in before reassigning it.")
			.format(before.technician_name or before.technician_id, doc.name),
			VisitInProgress,
		)


def sync_assignment(doc, method=None):
	"""Carry the share, the answer and the Sales Order across a reassignment."""
	before = _moved(doc)
	if not before:
		return

	_record_handover(doc, before)
	_move_share(doc.name, before.technician_user_id, doc.technician_user_id)
	_reset_response(doc)
	_sync_sales_order(doc)


def _record_handover(doc, before):
	"""Write what the previous technician said into the timeline, before it goes.

	The change log does not hold it: `reject_job` writes with `db.set_value` and
	leaves no Version row. This comment is the only copy that survives the reset.
	"""
	answer = response_of(before.as_dict())
	line = _("Reassigned from {0} to {1}.").format(
		before.technician_name or before.technician_id,
		doc.technician_name or doc.technician_id,
	)

	if answer != RESPONSE_PENDING:
		line += " " + _("Their answer was {0}").format(answer)
		if before.technician_response_at:
			line += " " + _("at {0}").format(before.technician_response_at)
		if before.rejection_reason:
			line += ". " + _("Reason given: {0}").format(before.rejection_reason)
		line += "."

	doc.add_comment("Comment", line)


def _move_share(visit_name, previous_user, new_user):
	"""Downgrade the previous technician to read, and give the new one write.

	The previous technician keeps read access deliberately: they may still have
	the patient on the phone, and they should be able to see what they were
	asked to do. What they lose is the ability to change it.
	"""
	if previous_user and previous_user != new_user:
		if frappe.db.exists(
			"DocShare",
			{"share_doctype": "Technician Visit Entry", "share_name": visit_name,
			 "user": previous_user},
		):
			frappe.share.add_docshare(
				"Technician Visit Entry", visit_name, previous_user,
				read=1, write=0, flags={"ignore_share_permission": True},
			)

	if new_user:
		frappe.share.add_docshare(
			"Technician Visit Entry", visit_name, new_user,
			read=1, write=1, flags={"ignore_share_permission": True},
		)


def _reset_response(doc):
	"""Hand the new technician an unanswered job.

	Without this the row keeps the previous technician's `Rejected`, which
	`my_jobs` and `my_visits` filter out and `accept_job` refuses -- so the
	reassignment the office was told to make would change nothing.
	"""
	frappe.db.set_value("Technician Visit Entry", doc.name, {
		"technician_response": RESPONSE_PENDING,
		"technician_response_at": None,
		"rejection_reason": None,
	}, update_modified=False)

	# Keep the in-memory document honest for whatever reads it after this save.
	doc.technician_response = RESPONSE_PENDING
	doc.technician_response_at = None
	doc.rejection_reason = None


def _sync_sales_order(doc):
	"""Point the Sales Order at the technician who is actually doing the work.

	The order and its items carry their own technician fields, written once at
	assignment and never updated. The payout queries and the technician reports
	read those, so a stale one misattributes the work as well as the money.
	"""
	fields = SALES_ORDER_FIELDS.get(doc.type)
	if not fields or not doc.sales_order_id:
		return

	order_field, item_field = fields

	if frappe.db.exists("Sales Order", doc.sales_order_id):
		frappe.db.set_value("Sales Order", doc.sales_order_id, order_field,
							doc.technician_id, update_modified=False)

	for item in frappe.get_all("Sales Order Item",
							   filters={"parent": doc.sales_order_id}, pluck="name"):
		frappe.db.set_value("Sales Order Item", item, item_field,
							doc.technician_id, update_modified=False)


@frappe.whitelist()
def reassign_visit(visit_id, technician_id, force=0):
	"""Move one visit to another technician, in one transaction.

	The office-facing entry point. Everything it does, `sync_assignment` also does
	for a plain form edit; this exists so there is one call to make from the desk
	and from the Sales Order, and so `force` has somewhere to live.

	`force` skips the arrival guard, closes the previous technician's check-in and
	clears the arrival stamp. It is the deliberate version of what the form used
	to do silently.

	Gated on `share` permission, not `write`. A technician holds write on their own
	visit through the DocShare, so a write gate would let them hand their work to
	someone else -- and reassignment is the office's call, which is the rule
	`reject_job` is built on. `share` is held by `NHK Admin` and `System Manager`
	and withheld from `NHK Technician` in `nhk/fixtures/custom_docperm.json`, so it
	is the permission that already means "the office".
	"""
	frappe.has_permission("Technician Visit Entry", "share", doc=visit_id, throw=True)

	visit = frappe.get_doc("Technician Visit Entry", visit_id)

	if visit.technician_id == technician_id:
		return {"name": visit.name, "technician_id": technician_id, "moved": False}

	if visit.status not in REASSIGNABLE_STATUSES:
		frappe.throw(
			_("Visit {0} is {1} and can no longer be reassigned.").format(visit.name, visit.status)
		)

	previous = visit.technician_id

	if frappe.utils.cint(force):
		visit.flags.force_reassign = True
		_clear_arrival(visit, previous)

	visit.technician_id = technician_id
	visit.save()

	return {"name": visit.name, "technician_id": technician_id,
			"previous_technician_id": previous, "moved": True}


def _clear_arrival(visit, previous_technician):
	"""Close the previous technician's check-in and unstamp the arrival."""
	from nhk.api.staff import _close_checkin, _open_visit_checkin

	open_checkin = _open_visit_checkin(previous_technician, visit.name)
	if open_checkin and open_checkin.name:
		_close_checkin(open_checkin.name, "Reassigned")

	visit.started_at = None
	visit.start_latitude = None
	visit.start_longitude = None
