"""Caller-identity guards for the technician staff app.

Every endpoint the phone calls resolves the session user through here before it
touches a document. The desk keeps calling the existing functions in
`nhk.custom_script` and the ERPNext fork directly; this module exists so that
the app never has to trust a docname handed to it over HTTP.

Why identity is resolved through `Technician Details` and never through roles:
30 users hold the `NHK Technician` role but only 22 `Technician Details` records
carry a `user_mail_id`, and two real technicians also hold `NHK Admin`. The
`Technician Details` row is the only thing that actually makes someone a
technician.
"""

import frappe
from frappe import _
from frappe.utils import today

#: Statuses a technician is allowed to act on. Everything past these belongs to
#: the back-office payout run, which the app does not touch.
OPEN_STATUSES = ("Assigned",)

#: `Technician Visit Entry.technician_response`. A job is assigned by the office
#: and then answered by the technician; nothing in the field starts until the
#: answer is `Accepted`.
RESPONSE_PENDING = "Pending"
RESPONSE_ACCEPTED = "Accepted"
RESPONSE_REJECTED = "Rejected"


class NotATechnician(frappe.PermissionError):
	"""The session user has no Technician Details record."""


def current_technician(user: str | None = None) -> str:
	"""Return the `Technician Details` name for the calling user.

	Raises NotATechnician if the caller is not a technician. Administrator is
	rejected too: it is not a person in the field, and letting it through would
	make every guard below a no-op during testing.
	"""
	user = user or frappe.session.user

	if user in ("Guest", "Administrator"):
		frappe.throw(_("No technician is linked to {0}.").format(user), NotATechnician)

	names = frappe.get_all(
		"Technician Details",
		filters={"user_mail_id": user},
		pluck="name",
		limit=2,
		ignore_permissions=True,
	)

	if not names:
		frappe.throw(_("No technician is linked to {0}.").format(user), NotATechnician)

	if len(names) > 1:
		# Two technician records pointing at one login would make "whose job is
		# this" ambiguous. Fail loudly rather than pick one.
		frappe.throw(
			_("{0} is linked to more than one Technician Details record: {1}.").format(
				user, ", ".join(names)
			),
			NotATechnician,
		)

	return names[0]


def owned_visit(visit_id: str, technician: str | None = None):
	"""Load a Technician Visit Entry, asserting it belongs to the caller.

	Ownership is checked against `technician_user_id` rather than against the
	DocShare row, because a reassignment rewrites shares and we want the check to
	agree with the field the visit itself carries.
	"""
	technician = technician or current_technician()
	user = frappe.session.user

	visit = frappe.get_doc("Technician Visit Entry", visit_id)

	if visit.technician_id != technician or visit.technician_user_id != user:
		# Deliberately the same message as a missing record: a technician probing
		# ids should not be able to tell an existing visit from a non-existent one.
		frappe.throw(
			_("Visit {0} not found.").format(visit_id), frappe.DoesNotExistError
		)

	return visit


def assert_open(visit) -> None:
	"""Assert the visit is still in a status the technician may act on."""
	if visit.status not in OPEN_STATUSES:
		frappe.throw(
			_("Visit {0} is already {1} and can no longer be changed from the app.").format(
				visit.name, visit.status
			)
		)


class OffDuty(frappe.PermissionError):
	"""The caller has no open Duty check-in for today."""


def open_duty(technician: str | None = None):
	"""The technician's Duty check-in for today, if it is still open.

	Duty expires at local midnight rather than on a missed check-out, so a
	technician who forgets to go off duty is not left on duty for a week. An
	explicit `end_duty` closes it early and records where they were.
	"""
	technician = technician or current_technician()

	return frappe.db.get_value(
		"Technician Check In",
		{
			"technician_id": technician,
			"kind": "Duty",
			"checked_in_at": (">=", today()),
			"closed_at": ("is", "not set"),
		},
		["name", "checked_in_at", "latitude", "longitude"],
		as_dict=True,
	)


def assert_on_duty(technician: str | None = None):
	"""Assert the caller has an open duty check-in, and return it.

	Being on duty is what makes a technician's jobs visible at all -- not just
	what makes them actionable. Off duty the app shows nothing, so the customer
	names, addresses, phone numbers and outstanding dues a visit carries are not
	sitting on a phone screen after the shift ends.
	"""
	duty = open_duty(technician)
	if not duty:
		frappe.throw(_("You are off duty. Go on duty to see your jobs."), OffDuty)
	return duty


def response_of(visit) -> str:
	"""The technician's answer to a visit, treating a blank as `Pending`.

	Rows created before the field existed carry NULL, and an unanswered job is
	exactly what `Pending` means.
	"""
	return visit.get("technician_response") or RESPONSE_PENDING


def assert_accepted(visit) -> None:
	"""Assert the technician has taken the job on."""
	response = response_of(visit)

	if response == RESPONSE_REJECTED:
		frappe.throw(_("You rejected visit {0}. The office has to reassign it.").format(visit.name))
	if response != RESPONSE_ACCEPTED:
		frappe.throw(_("Accept visit {0} before you start it.").format(visit.name))
