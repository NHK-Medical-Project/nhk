"""Closing a Technician Visit Entry: the one routine every surface shares.

The app (`nhk.api.staff.complete_job`), the Sales Order and the visit form each
used to close a visit their own way. The app priced it and stamped it; the
order's `Installation Done` / `Service Done` wrote the status with
`db.set_value`, so no distance was asked for, no charge was calculated and no
completion time was written; the visit form went through
`nhk.custom_script.change_status_sales`, which also commits mid-call. The same
job looked different afterwards depending on who pressed the button.

Two halves, so a caller takes exactly what it needs:

* `close_visit` -- the visit alone: distance, slab price, completion time,
  status, arrival closed. For callers where the Sales Order is already being
  moved by something else, such as the rental buttons, which run the core
  `make_delivered` themselves.
* `complete_visit` -- `close_visit`, then the Sales Order moved to match.

**Neither commits.** The request does, once, at the end, so a Sales Order that
cannot be advanced takes the visit back with it. The visit is also saved
*before* the order moves, and that order is load-bearing: moving a rental order
to `Active` fires the core `validate_technician_visit`, which sets every open
Delivery visit on the order to `Delivered` itself. A visit still `Assigned` at
that point was flipped behind the caller's back, and the `Assigned -> Delivered`
change that followed threw "Invalid status change".

Gates -- who may close which visit -- belong to the callers. The app requires
duty, ownership, acceptance and a check-in; the office requires none of those.
"""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from nhk.api.guards import OPEN_STATUSES

#: The status each visit type closes at.
#:
#: The last three are the Sales and Service order flow: the Sales Order form's
#: Assign Technician creates the two `Technician Assignment` types, and the desk
#: has closed all three through `change_status_sales`.
COMPLETION_STATUS = {
	"Delivery": "Delivered",
	"Pickup": "Picked up",
	"Service": "Service Done",
	"Technician Assignment For Sales": "Installation Done",
	"Technician Assignment For Service": "Service Done",
}

#: Completion statuses that close work on a Sales or Service order rather than
#: moving stock -- see `_advance_sales_order`.
WORK_DONE_STATUSES = ("Installation Done", "Service Done")


#: What the Sales Order's Technician Visits section shows for each visit. The
#: technician's side -- their answer, arrival and attachments -- is the point:
#: it is what the office used to open the visit to find out.
SALES_ORDER_VISIT_FIELDS = [
	"name", "type", "status",
	"technician_id", "technician_name", "technician_mobile_no",
	"technician_response", "technician_response_at", "rejection_reason",
	"scheduled_datetime", "slot", "started_at", "completed_at",
	"kilometers", "calculated_kilometers", "distance_source", "distance_method", "straight_line_kilometers",
	"charges", "incentive_amount_to_be_processed", "payment_status",
	"extra_payment", "extra_payment_reason", "extra_payment_note", "payout_month",
	"notes", "order_notes", "patient_signature", "creation",
]

#: A visit's statuses once the work is done, before the payout run touches it.
DONE_STATUSES = tuple(dict.fromkeys(COMPLETION_STATUS.values()))

#: Visit statuses whose pay is still to be settled by a month.
COUNTED_STATUSES = DONE_STATUSES + ("Incentive Finalize",)

#: Who may see and settle technician pay (`nhk.api.payouts`). The visit form
#: hid its payout buttons from everyone else, but `nhk.custom_script.change_status`
#: behind them checked nothing; the payout endpoints check it on the server.
PAYOUT_ROLE = "NHK Admin"

#: `Technician Visit Entry.slot` options.
SLOTS = ("Morning", "Afternoon", "Evening")

#: Delivery and Pickup close through the order's own button (issue 04). The row
#: offers that button when the order is where ERPNext itself offers it
#: (`sales_order.js`: `DELIVERED` on a dispatched rental that is not fully
#: billed, `Submitted To Office` on a picked-up rental).
ORDER_BUTTONS = {
	"Delivery": {"action": "mark_delivered", "order_status": "DISPATCHED", "label": "DELIVERED"},
	"Pickup": {"action": "submit_to_office", "order_status": "Picked Up", "label": "Submitted To Office"},
}


@frappe.whitelist()
def for_sales_order(sales_order):
	"""Every visit on one Sales Order, newest first, with what the caller may do.

	Gated on the order, not on a role. `NHK Technician` has no read on Sales
	Order, which keeps technicians out; refusing the role outright would also
	lock out the two real technicians who hold `NHK Admin` as well. Whoever may
	read the order may see its visits -- they are the order's field work.

	Each row also says, in words, what is happening (`stage`) and what comes
	next (`next_step`), and lists the `actions` the caller may take on it. The
	form only draws them; every endpoint checks the same thing again when the
	action arrives. `can_complete` stays for callers that read it.
	"""
	if not frappe.has_permission("Sales Order", "read", sales_order):
		frappe.throw(_("Not permitted to read {0}.").format(sales_order), frappe.PermissionError)

	rows = frappe.get_all(
		"Technician Visit Entry",
		filters={"sales_order_id": sales_order},
		fields=SALES_ORDER_VISIT_FIELDS,
		order_by="creation desc",
	)
	if not rows:
		return []

	files = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Technician Visit Entry",
			"attached_to_name": ("in", [r.name for r in rows]),
		},
		fields=["name", "file_name", "file_url", "file_size", "attached_to_name"],
		order_by="creation asc",
		ignore_permissions=True,
	)
	attachments_by_visit = {}
	for f in files:
		attachments_by_visit.setdefault(f.attached_to_name, []).append(f)

	order = frappe.db.get_value(
		"Sales Order", sales_order, ["status", "order_type", "per_billed"], as_dict=True
	)
	may_change_order = frappe.has_permission("Sales Order", "write", sales_order)

	for row in rows:
		row["attachments"] = list(attachments_by_visit.get(row.name, []))
		if row.get("patient_signature"):
			sig_url = row.patient_signature
			if not any(f.get("file_url") == sig_url for f in row["attachments"]):
				row["attachments"].append({
					"name": "patient_signature",
					"file_name": _("Patient Signature"),
					"file_url": sig_url,
				})
		row["attachment_count"] = len(row["attachments"])
		may_change_visit = may_change_order and frappe.has_permission(
			"Technician Visit Entry", "write", row.name
		)
		row["actions"] = _actions(
			row, order,
			office=may_change_visit,
			share=frappe.has_permission("Technician Visit Entry", "share", row.name),
		)
		row["can_complete"] = "complete" in row["actions"]
		row["stage"], row["next_step"] = _describe(row)
		row["progress"] = _progress(row)

	return rows


#: The steps every visit goes through, in order, as the table's progress shows them.
#: "Paid" is the month's payout (or, for older visits, the per-visit payment run).
PROGRESS_STEPS = ("Assigned", "Accepted", "Arrived", "Completed", "Paid")


def _progress(row):
	"""How far along `PROGRESS_STEPS` the visit is, and whether it was turned down.

	A visit closed by the office may never have been accepted or arrived at; the
	later step still counts as reached, because the work is done either way.
	"""
	if row.payout_month or row.status in ("Amount Settled", "Closed"):
		reached = 4
	elif row.status in DONE_STATUSES or row.status == "Incentive Finalize":
		reached = 3
	elif row.started_at:
		reached = 2
	elif (row.technician_response or "Pending") == "Accepted":
		reached = 1
	else:
		reached = 0
	return {
		"steps": [_(s) for s in PROGRESS_STEPS],
		"reached": reached,
		"rejected": row.status in OPEN_STATUSES and row.technician_response == "Rejected",
	}


@frappe.whitelist()
def attachments_for_visit(visit_id):
	"""Files on one visit, for the order's table. Gated on reading the visit's order."""
	sales_order = frappe.db.get_value("Technician Visit Entry", visit_id, "sales_order_id")
	if not sales_order or not frappe.has_permission("Sales Order", "read", sales_order):
		frappe.throw(_("Not permitted to read {0}.").format(visit_id), frappe.PermissionError)

	from nhk.api.staff import _attachments_of

	return _attachments_of(visit_id)


def _actions(row, order, office, share):
	"""What the caller may do to this visit now, as action keys the form knows.

	No per-visit payout actions: pay is settled a month at a time, on the
	Technician Payouts page (decided 2026-09-28).
	"""
	actions = []
	if row.status in OPEN_STATUSES:
		if office and completes_from_the_order(row.type):
			actions.append("complete")
		button = ORDER_BUTTONS.get(row.type)
		if office and button and _order_offers(order, button):
			actions.append(button["action"])
		if share:
			actions.append("reassign")
		if office:
			actions.append("reschedule")
	if office and _extra_is_open(row):
		actions.append("extra_payment")
	return actions


def _extra_is_open(row):
	"""The office may still correct the extra payment: its month is not processed,
	and the old per-visit payment run has not settled it either."""
	return not row.payout_month and row.status not in ("Amount Settled", "Closed")


def _order_offers(order, button):
	"""Whether ERPNext itself shows this rental button on the order right now."""
	if order.order_type != "Rental" or order.status != button["order_status"]:
		return False
	if button["action"] == "mark_delivered":
		return flt(order.per_billed) < 100
	return True


def _describe(row):
	"""(stage, next step) in plain words, for someone who never opens the visit."""
	who = row.technician_name or row.technician_id or _("the technician")
	when = lambda value: frappe.utils.format_datetime(value) if value else ""

	if row.status in OPEN_STATUSES:
		button = ORDER_BUTTONS.get(row.type)
		closes = (
			_("It closes when the order is marked {0}.").format(button["label"]) if button
			else _("Complete it here when the work is done.")
		)
		response = row.technician_response or "Pending"
		if response == "Rejected":
			return (
				_("Rejected by {0}").format(who),
				_("Rejected: {0}. Reassign it to another technician.").format(
					row.rejection_reason or _("no reason given")
				),
			)
		if row.started_at:
			return _("Arrived {0}").format(when(row.started_at)), closes
		if response == "Accepted":
			return (
				_("Accepted {0}").format(when(row.technician_response_at)),
				_("{0} has not arrived yet. {1}").format(who, closes),
			)
		return _("Waiting for {0}").format(who), _("Waiting for {0} to accept the job.").format(who)

	if row.payout_month:
		return (
			_("Paid in the {0} payout").format(row.payout_month),
			_("Settled. Nothing left to do."),
		)
	if row.status in DONE_STATUSES or row.status == "Incentive Finalize":
		stage = "%s %s" % (_(row.status), when(row.completed_at))
		return stage.strip(), _("Paid with this month's technician payout.")
	if row.status in ("Amount Settled", "Closed"):
		return _(row.status), _("Settled before monthly payouts. Nothing left to do.")
	return _(row.status or ""), ""


@frappe.whitelist()
def reschedule(visit_id, scheduled_datetime, slot=None):
	"""Move an open visit to another time. The office's call, not the technician's."""
	visit = frappe.get_doc("Technician Visit Entry", visit_id)
	if visit.status not in OPEN_STATUSES:
		frappe.throw(_("{0} is already {1}.").format(visit.name, visit.status))
	if slot and slot not in SLOTS:
		frappe.throw(_("Slot must be one of {0}.").format(", ".join(SLOTS)))
	if not scheduled_datetime:
		frappe.throw(_("Pick the new date and time."))

	_assert_office_may_change(visit)

	visit.scheduled_datetime = frappe.utils.get_datetime(scheduled_datetime)
	visit.slot = slot or visit.slot
	visit.save()
	return {"name": visit.name, "scheduled_datetime": visit.scheduled_datetime, "slot": visit.slot}


@frappe.whitelist()
def complete_from_sales_order(visit_id, kilometers, notes=None):
	"""The office closing a visit from its Sales Order.

	Replaces the order's `Installation Done` / `Service Done`, which wrote the
	visit's status with `db.set_value` -- no distance, no charge, no completion
	time. This asks for the distance and closes the visit through
	`complete_visit`, exactly as the app does.

	None of the app's gates apply: the office closes visits nobody accepted or
	arrived at, and that is its call. What it must have is write on both the
	order and the visit. `NHK Technician` has no permission on Sales Order, so
	a technician cannot use this to skip the app's own checks.

	The office's notes are *added* to the visit's: `notes` is also where the
	technician writes from the doorstep, and that must survive the office
	closing the job.
	"""
	visit = frappe.get_doc("Technician Visit Entry", visit_id)
	if not visit.sales_order_id:
		frappe.throw(_("{0} is not on a Sales Order.").format(visit.name))
	if not completes_from_the_order(visit.type):
		frappe.throw(
			_("A {0} visit is closed by the order's own {1} button.").format(
				visit.type, _("DELIVERED") if visit.type == "Delivery" else _("Submitted To Office")
			)
		)

	_assert_office_may_change(visit)

	notes = (notes or "").strip()
	if notes and visit.notes:
		notes = "%s\n\n%s" % (visit.notes, notes)

	completed_at = complete_visit(visit, kilometers, notes=notes or None)

	return {"name": visit.name, "status": visit.status, "kilometers": visit.kilometers,
			"charges": visit.charges, "completed_at": completed_at}


#: How long a distance entered at the order's button waits for the order to
#: move. Long enough to fill in the order's own dialog, short enough that an
#: abandoned one cannot surface on a later, unrelated close.
HELD_DISTANCE_SECONDS = 30 * 60


def _held_distance_key(visit_name):
	return "nhk:held_distance:%s" % visit_name


@frappe.whitelist()
def set_distance(visit_id, kilometers):
	"""Hold the distance for an open Delivery or Pickup visit, from its order.

	The order's `DELIVERED` and `Submitted To Office` buttons close these visits
	themselves, through the core `validate_technician_visit`, which only checks
	that a distance is there -- and `validate()` fills an empty one with 1.0 on
	every save, so it always is. Deliveries closed at 1 km, the bottom slab.

	The distance is **held, not saved.** The form asks for it before the
	order's own dialog; saving it then meant that cancelling that dialog, or
	`make_delivered` raising, left the visit re-priced and still open. It is
	applied by `stamp_visits_closed_by_the_order`, in the same save that closes
	the visit, or not at all.
	"""
	visit = frappe.get_doc("Technician Visit Entry", visit_id)
	if not visit.sales_order_id:
		frappe.throw(_("{0} is not on a Sales Order.").format(visit.name))
	if visit.type not in ORDER_CLOSED_TYPES:
		frappe.throw(_("The distance for a {0} visit is entered when it is completed.").format(visit.type))
	if visit.status not in OPEN_STATUSES:
		frappe.throw(_("{0} is already {1}.").format(visit.name, visit.status))

	_assert_office_may_change(visit)

	distance = _validated_distance(kilometers)
	frappe.cache.set_value(_held_distance_key(visit.name), distance, expires_in_sec=HELD_DISTANCE_SECONDS)
	return {"name": visit.name, "kilometers": distance, "held": True}


#: The order transitions that close a visit in the core
#: (`SalesOrder.validate_technician_visit`, `sales_order.py:360`):
#: (order status before, after) -> visit type it closes. A copy of the core's
#: table, which is not importable; `test_visits.py` pins the behaviour.
ORDER_TRANSITIONS = {
	("DISPATCHED", "Active"): "Delivery",
	("Picked Up", "Submitted to Office"): "Pickup",
}

#: Visit types the order's own buttons close.
ORDER_CLOSED_TYPES = tuple(ORDER_TRANSITIONS.values())


def stamp_visits_closed_by_the_order(doc, method=None):
	"""`on_update_after_submit` on Sales Order: finish the visits the order closed.

	The core closes them with `db.set_value`, so nothing else on the visit
	moves: no completion time, and the distance the office entered at the
	button is still only held (`set_distance`). This applies both, on exactly
	the visits this save closed -- the ones the core wrote during it, which is
	what `modified >=` the order's own save time picks out (`Document._save`
	stamps the order before any hook runs). Older closed visits carry no
	completion time either, and must not get today's.

	Saved normally, so `validate()` prices the new distance from the slab as
	every other path does. Calling `update_technician_charge` directly would
	not: on a freshly loaded document `has_value_changed` reports every field
	changed, and it returns early on `charges`.

	Permissions were checked when the distance was held, and the order's own
	save runs without them (`make_delivered` saves with `ignore_permissions`),
	so the visit is saved the same way.

	Deliberately **not** closing the technician's check-in: decided 2026-09-25,
	no automatic checkout for technicians.
	"""
	before = doc.get_doc_before_save()
	visit_type = ORDER_TRANSITIONS.get((before and before.status, doc.status))
	if not visit_type:
		return

	closed = frappe.get_all(
		"Technician Visit Entry",
		filters={
			"sales_order_id": doc.name,
			"type": visit_type,
			"status": COMPLETION_STATUS[visit_type],
			"completed_at": ("is", "not set"),
			"modified": (">=", doc.modified),
		},
		pluck="name",
	)
	now = now_datetime()
	for name in closed:
		visit = frappe.get_doc("Technician Visit Entry", name)
		key = _held_distance_key(name)
		held = frappe.cache.get_value(key)
		if held:
			visit.kilometers = held
		visit.completed_at = now
		visit.technician_update_datetime = now
		visit.flags.ignore_permissions = True
		visit.save()
		# Used once: a later close must not pick up a distance meant for this one.
		frappe.cache.delete_value(key)


def _assert_office_may_change(visit):
	"""Write on the visit's order and on the visit, or a refusal that says why.

	`NHK Technician` has no permission on Sales Order, so this keeps
	technicians to the app -- decided 2026-09-25 -- where duty, acceptance and
	arrival are checked. Not a role check: two technicians also hold `NHK Admin`
	and keep their office access.
	"""
	for doctype, name in (("Sales Order", visit.sales_order_id), ("Technician Visit Entry", visit.name)):
		if frappe.has_permission(doctype, "write", name):
			continue
		if frappe.db.exists("Technician Details", {"user_mail_id": frappe.session.user}):
			# The desk visit form still shows technicians the button, so say
			# where to go instead of a bare refusal.
			frappe.throw(_("Complete this job from the NHK technician app."), frappe.PermissionError)
		frappe.throw(_("Not permitted to change {0}.").format(name), frappe.PermissionError)


def completes_from_the_order(visit_type):
	"""Whether the office may close this type straight from the order's list.

	Installation and service only: closing them is a status change. Delivery and
	Pickup move stock, and the order's `DELIVERED` / `Submitted To Office`
	dialogs collect the agreement, ID and payment details that go with that --
	a completion from the list would skip them.
	"""
	return COMPLETION_STATUS.get(visit_type) in WORK_DONE_STATUSES


def close_visit(visit, kilometers, notes=None, latitude=None, longitude=None, extra=None):
	"""Close one visit. Does not touch its Sales Order, does not commit.

	`visit` is the Technician Visit Entry document. It is saved normally, as the
	caller, so the slab price in `TechnicianVisitEntry.validate` and the
	assignment hooks run exactly as they do on a desk save.

	`extra` is the technician's extra payment, `{amount, reason, note}`, when
	there is one; `TechnicianVisitEntry.validate` checks it.

	Returns the completion time.
	"""
	if visit.status not in OPEN_STATUSES:
		frappe.throw(_("{0} is already {1}.").format(visit.name, visit.status))

	new_status = COMPLETION_STATUS.get(visit.type)
	if not new_status:
		frappe.throw(_("A {0} visit cannot be completed.").format(visit.type))

	completed_at = now_datetime()

	# The distance and the status go in one save: the slab lookup runs in
	# validate(), so it sees the real number, and there is no moment where the
	# visit is priced but still open for someone else's code to close.
	visit.kilometers = _validated_distance(kilometers)
	if notes:
		visit.notes = notes
	visit.completed_at = completed_at
	visit.technician_update_datetime = completed_at
	visit.complete_latitude = flt(latitude)
	visit.complete_longitude = flt(longitude)
	visit.status = new_status
	if extra and flt(extra.get("amount")):
		visit.extra_payment = flt(extra.get("amount"))
		visit.extra_payment_reason = extra.get("reason")
		visit.extra_payment_note = (extra.get("note") or "").strip() or None
	visit.save()

	_close_arrivals(visit.name)

	return completed_at


def complete_visit(visit, kilometers, notes=None, latitude=None, longitude=None, extra=None):
	"""Close one visit and move its Sales Order to match. Does not commit."""
	completed_at = close_visit(
		visit, kilometers, notes=notes, latitude=latitude, longitude=longitude, extra=extra
	)
	_advance_sales_order(visit, visit.status)
	return completed_at


def _close_arrivals(visit_name):
	"""Close whatever check-in is still open on this visit.

	By visit rather than by technician: a visit the office closes may have been
	arrived at by someone the caller is not, and an arrival left open outlives
	the job -- "where is this technician right now" keeps answering with it.
	"""
	# Imported here: `staff` imports this module at load time.
	from nhk.api.staff import _close_checkin

	for name in frappe.get_all(
		"Technician Check In",
		filters={"visit_entry": visit_name, "kind": "Visit", "closed_at": ("is", "not set")},
		pluck="name",
	):
		_close_checkin(name, "Completed")


def _validated_distance(kilometers):
	"""Distance must be a whole number of at least 1 km.

	The slab boundaries are integers, so a fractional distance can land between
	two rows and silently leave the payout unchanged.
	"""
	if kilometers in (None, ""):
		frappe.throw(_("Enter the distance travelled."))

	distance = flt(kilometers)
	if distance != int(distance):
		frappe.throw(_("Distance must be a whole number of kilometres."))
	if distance < 1:
		frappe.throw(_("Distance must be at least 1 km."))

	return int(distance)


def _advance_sales_order(visit, new_status):
	"""Drive the Sales Order forward, translating the fork's errors.

	Delivery and Pickup move stock through the fork. Installation and service
	close the technician's part of a Sales or Service order, which is a status
	change only.

	`make_delivered` throws a bare 'Item Is Not Reserved' when stock state does
	not line up. That is unfixable in the field, so it is re-raised as something
	the app can show on a blocking screen with a call-the-office action.

	Note what `make_delivered` wants for `customer_name`: despite the name it
	writes the value into `Item.customer_n`, which is a **Link to Customer**, so
	it has to be the Customer docname (`NHK-CUS-0105`) and not the display name.
	Both desk callers pass the Sales Order's own `customer` field; passing
	`visit.patient_name` here threw `Could not find Customer: <person's name>`
	on every delivery, because customers are named by series and the docname is
	never the display name.
	"""
	from erpnext.selling.doctype.sales_order.sales_order import make_delivered, make_pickedup

	if not visit.sales_order_id:
		# Nothing to advance. Every type that reaches here normally carries an
		# order, but a visit created by hand may not.
		return

	if new_status in WORK_DONE_STATUSES:
		_mark_technician_work_done(visit.sales_order_id)
		return

	stamp = frappe.utils.nowdate()
	try:
		if new_status == "Delivered":
			# Read it off the order being advanced rather than off the visit: the
			# order is what `make_delivered` acts on, and the visit's own
			# `patient_id` is a copy that can drift.
			customer = frappe.db.get_value(
				"Sales Order", visit.sales_order_id, "customer"
			) or visit.patient_id
			make_delivered(visit.sales_order_id, customer, stamp)
		else:
			make_pickedup(visit.sales_order_id, stamp)
	except Exception as exc:
		frappe.throw(
			_("The job could not be closed on order {0}: {1}. Call the office before you leave.")
			.format(visit.sales_order_id, str(exc))
		)


def _mark_technician_work_done(sales_order):
	"""The Sales Order half of `change_status_sales`, without its commit.

	Same rule as the desk: an order still `Technician Assigned` moves to
	`Technician Work Done`, items too. One the office has already taken further
	is left where it is. Written with `db.set_value`, as the desk does, because
	the status is a custom one the ERPNext status machinery does not know.
	"""
	if frappe.db.get_value("Sales Order", sales_order, "status") != "Technician Assigned":
		return

	frappe.db.set_value("Sales Order", sales_order, "status", "Technician Work Done")
	for item in frappe.get_all("Sales Order Item", filters={"parent": sales_order}, pluck="name"):
		frappe.db.set_value("Sales Order Item", item, "child_status", "Technician Work Done")
