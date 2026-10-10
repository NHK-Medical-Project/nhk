"""A technician arranging the pickup of their own sleep study delivery.

Everywhere else the office gives out work and the technician answers it
(`nhk.api.assignment.reassign_visit`, `nhk.api.staff.reject_job`). Sleep studies
are the exception (decided 2026-10-09). The device goes in at night and comes
back the next morning, and nobody is in the office at either end to assign the
pickup. So the technician who completed the delivery assigns it, to
themselves or to another technician, from the app. The app reaches this through
`nhk.api.staff.assign_pickup` and `pickup_technicians`.

The exception is kept narrow on purpose:

* **Only from a sleep study delivery the caller completed.** That is
  `technician_category` starting with `Sleep Study`, `type` Delivery,
  `status` Delivered, and the caller is the technician on it (`owned_visit`).
  The order must be `Active`, as `make_delivered` leaves it.
* **Only once, then only while unanswered.** The technician who arranged it can
  move it to someone else until that technician accepts. After that, or if
  the office assigned the pickup, changing it is the office's job
  (`reassign_visit`).
* **The office keeps the job.** The pickup visit is owned by, and `assigned_by`,
  whoever owns the delivery. So the office hears when the pickup technician
  accepts or rejects (`nhk.api.notify.tell_office`), and a rejection goes back
  to the office like any other. The technician who arranged it is recorded on
  `pickup_arranged_by` and in the timeline. They do not own the visit, because
  `NHK Technician` reads and writes `if_owner` and that would give them write
  on a visit they handed to someone else.

Works off duty, like `accept_job`: the delivery ends late, and the technician
may already have checked out.

The Sales Order half copies `make_ready_for_pickup` in the ERPNext fork but leaves
out its `frappe.db.begin()` and its `rollback`. `begin` commits whatever the request
has done so far, and `rollback` undoes it. Here the request commits once, so the
order and the visit are saved together or not at all.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cstr, get_datetime, getdate, now_datetime, today

from nhk.api.guards import (
	RESPONSE_ACCEPTED,
	RESPONSE_PENDING,
	current_technician,
	owned_visit,
	response_of,
)
from nhk.api.visits import SLOTS

#: `Technician Category` names that are sleep studies: Level 1, 2, 3 and Split night.
SLEEP_STUDY_PREFIX = "Sleep Study"

#: The Sales Order status `make_delivered` leaves a delivered rental in.
DELIVERED_ORDER_STATUS = "Active"
READY_FOR_PICKUP = "Ready for Pickup"

#: `Sales Order.pickup_reason` is a fixed list with nothing about a study ending.
PICKUP_REASON = "Other Reason"
PICKUP_REMARK = "Sleep study complete. Pickup arranged by {0} from the technician app."

#: Where in its day a pickup is placed on `scheduled_datetime`. The slot is the
#: real promise. The time only sorts the day list and fills in the notification's
#: "when".
SLOT_STARTS = {"Morning": "09:00:00", "Afternoon": "13:00:00", "Evening": "17:00:00"}
DEFAULT_SLOT = "Morning"


def pickup_reasons():
	"""`Sales Order.pickup_reason`'s options, the empty one left out."""
	options = frappe.get_meta("Sales Order").get_field("pickup_reason").options or ""
	return [o for o in options.split("\n") if o.strip()]


def validated_pickup_reason(reason):
	if reason not in pickup_reasons():
		frappe.throw(_("Pick why the device is being picked up."))
	return reason


def is_sleep_study(visit) -> bool:
	return cstr(visit.get("technician_category")).startswith(SLEEP_STUDY_PREFIX)


def _open_pickup(sales_order):
	"""The order's open Pickup visit, if any."""
	return frappe.db.get_value(
		"Technician Visit Entry",
		{"sales_order_id": sales_order, "type": "Pickup", "status": "Assigned"},
		["name", "technician_id", "technician_name", "technician_response",
		 "pickup_arranged_by", "scheduled_datetime", "slot"],
		as_dict=True,
		order_by="creation desc",
	)


def pickup_state(visit, technician=None):
	"""What the app shows for a delivery's pickup, and whether it may assign it.

	`None` for any visit this does not apply to, so `job` and `complete_job` can
	include it without the app having to know the rule.
	"""
	if visit.get("type") != "Delivery" or not is_sleep_study(visit) or not visit.get("sales_order_id"):
		return None

	technician = technician or current_technician()
	pickup = _open_pickup(visit.sales_order_id)
	order_status = frappe.db.get_value("Sales Order", visit.sales_order_id, "status")

	if pickup:
		can_change = (
			visit.get("status") == "Delivered"
			and pickup.pickup_arranged_by == technician
			and response_of(pickup) == RESPONSE_PENDING
		)
	else:
		can_change = visit.get("status") == "Delivered" and order_status in (DELIVERED_ORDER_STATUS, READY_FOR_PICKUP)

	return {
		"can_assign": bool(can_change),
		"pickup_visit": pickup.name if pickup else None,
		"technician_id": pickup.technician_id if pickup else None,
		"technician_name": pickup.technician_name if pickup else None,
		"technician_response": response_of(pickup) if pickup else None,
		"scheduled_datetime": pickup.scheduled_datetime if pickup else None,
		"slot": pickup.slot if pickup else None,
		"arranged_by_me": bool(pickup and pickup.pickup_arranged_by == technician),
	}


def pickup_technicians():
	"""Who a pickup can be given to: every technician with an app login.

	The caller first, so "Me" is always at the top of the list.
	"""
	me = current_technician()
	rows = frappe.get_all(
		"Technician Details",
		filters={"user_mail_id": ("is", "set")},
		fields=["name", "name1", "mobile_number"],
		order_by="name1 asc",
		ignore_permissions=True,
	)
	rows.sort(key=lambda r: r.name != me)
	return [{"technician_id": r.name, "technician_name": r.name1 or r.name,
			 "mobile_number": r.mobile_number, "is_me": r.name == me} for r in rows]


def assign_pickup(visit_id, technician_id, pickup_date=None, slot=None):
	"""Assign the pickup of a sleep study delivery to `technician_id`.

	`visit_id` is the caller's completed Delivery visit, not the pickup.
	`pickup_date` defaults to tomorrow and `slot` to Morning. Calling it again
	before the pickup technician has answered moves the pickup to whoever is
	named this time.
	"""
	me = current_technician()
	delivery = owned_visit(visit_id, technician=me)
	target = _pickup_technician(technician_id)
	when, slot = _when(pickup_date, slot)

	if delivery.type != "Delivery" or not is_sleep_study(delivery):
		frappe.throw(_("Only a sleep study delivery's pickup can be assigned from the app."))
	if delivery.status != "Delivered":
		frappe.throw(_("Complete the delivery before you assign its pickup."))
	if not delivery.sales_order_id:
		frappe.throw(_("Visit {0} has no order to pick up from. Call the office.").format(delivery.name))

	pickup = _open_pickup(delivery.sales_order_id)
	if pickup:
		return _change(delivery, pickup, me, target, when, slot)

	order_status = frappe.db.get_value("Sales Order", delivery.sales_order_id, "status")
	if order_status not in (DELIVERED_ORDER_STATUS, READY_FOR_PICKUP):
		frappe.throw(
			_("Order {0} is {1}, so its pickup is with the office.").format(
				delivery.sales_order_id, order_status)
		)

	_mark_ready_for_pickup(delivery.sales_order_id, target, when, me)
	name = _create_pickup(delivery, target, when, slot, me)
	return _result(name, created=True)


def ready_for_pickup(visit_id, pickup_date=None, slot=None):
	"""Mark the sleep study order Ready for Pickup without assigning a technician.

	Called by the delivery technician when leaving the pickup to the office.
	"""
	me = current_technician()
	delivery = owned_visit(visit_id, technician=me)
	if delivery.type != "Delivery" or not is_sleep_study(delivery):
		frappe.throw(_("Only a sleep study delivery can be marked ready for pickup."))
	if delivery.status != "Delivered":
		frappe.throw(_("Complete the delivery before you mark it ready for pickup."))
	if not delivery.sales_order_id:
		frappe.throw(_("Visit {0} has no order to pick up from.").format(delivery.name))

	order_status = frappe.db.get_value("Sales Order", delivery.sales_order_id, "status")
	if order_status not in (DELIVERED_ORDER_STATUS, READY_FOR_PICKUP):
		frappe.throw(_("Order {0} is already {1}.").format(delivery.sales_order_id, order_status))

	when, slot = _when(pickup_date, slot)
	_mark_ready_for_pickup(delivery.sales_order_id, target=None, when=when, me=me)
	return {"status": READY_FOR_PICKUP, "sales_order": delivery.sales_order_id}


def _pickup_technician(technician_id):
	if not technician_id or not frappe.db.exists("Technician Details", technician_id):
		frappe.throw(_("Pick a technician for the pickup."))
	row = frappe.db.get_value("Technician Details", technician_id,
							  ["name", "name1", "user_mail_id"], as_dict=True)
	if not row.user_mail_id:
		frappe.throw(_("{0} has no app login, so they would never see the job.")
					 .format(row.name1 or row.name))
	return row


def _when(pickup_date, slot):
	slot = slot or DEFAULT_SLOT
	if slot not in SLOTS:
		frappe.throw(_("Slot must be one of {0}.").format(", ".join(SLOTS)))
	day = getdate(pickup_date) if pickup_date else getdate(add_days(today(), 1))
	if day < getdate(today()):
		frappe.throw(_("The pickup date cannot be in the past."))
	return get_datetime("%s %s" % (day, SLOT_STARTS[slot])), slot


def _mark_ready_for_pickup(sales_order, target, when, me=None, reason=PICKUP_REASON, remark=None):
	"""The Sales Order half of `make_ready_for_pickup`, without its commit.

	`reason` and `remark` default to the sleep study's (ADR-0006). The office
	passes its own for every other rental (`nhk.api.ops.assign_pickup`).
	"""
	if remark is None:
		who = frappe.db.get_value("Technician Details", me, "name1") or me if me else None
		remark = PICKUP_REMARK.format(who) if who else _("Sleep study complete. Order marked Ready for Pickup.")

	order = frappe.get_doc("Sales Order", sales_order)
	order.status = READY_FOR_PICKUP
	order.pickup_date = when
	order.pickup_reason = reason
	# The order carries the remark as well as its items, as `make_ready_for_pickup` writes it.
	order.pickup_remark = remark
	order.custom_technician_id_pickup = target.name if target else None
	order.save(ignore_permissions=True)

	for name in frappe.get_all("Sales Order Item", filters={"parent": sales_order}, pluck="name"):
		item = frappe.get_doc("Sales Order Item", name)
		item.child_status = READY_FOR_PICKUP
		item.pickup_date = when
		item.pickup_reason = reason
		item.pickup_remark = remark
		item.technician_id_after_delivered = target.name if target else None
		item.save(ignore_permissions=True)


def _create_pickup(delivery, target, when, slot, me):
	"""The Pickup visit, owned by the office that gave out the delivery.

	The caller has no `create` on Technician Visit Entry, so this inserts with
	`ignore_permissions`. The checks in `assign_pickup` stand in for it.
	"""
	office = delivery.assigned_by or delivery.owner

	visit = frappe.get_doc({
		"doctype": "Technician Visit Entry",
		"sales_order_id": delivery.sales_order_id,
		"technician_id": target.name,
		"type": "Pickup",
		"status": "Assigned",
		"patient_id": delivery.patient_id,
		"technician_category": delivery.technician_category,
		"scheduled_datetime": when,
		"slot": slot,
		"pickup_arranged_by": me,
		# Accepting is a promise, and a technician who takes their own pickup has
		# just made it.
		"technician_response": RESPONSE_ACCEPTED if target.name == me else RESPONSE_PENDING,
		"technician_response_at": now_datetime() if target.name == me else None,
	}).insert(ignore_permissions=True)

	# Insert stamps both with the caller (`stamp_assigned_by`, and Frappe's own
	# owner). Hand them to the office, see the module docstring.
	frappe.db.set_value("Technician Visit Entry", visit.name,
						{"owner": office, "assigned_by": office}, update_modified=False)

	frappe.share.add_docshare("Technician Visit Entry", visit.name, target.user_mail_id,
							  read=1, write=1, flags={"ignore_share_permission": True})

	line = _("Pickup assigned to {0} by {1}, from the app after delivery {2}.").format(
		target.name1 or target.name, frappe.db.get_value("Technician Details", me, "name1") or me,
		delivery.name)
	visit.add_comment("Comment", line)
	frappe.get_doc("Sales Order", delivery.sales_order_id).add_comment("Comment", line)
	return visit.name


def _change(delivery, pickup, me, target, when, slot):
	"""Move a pickup this technician assigned, before anyone has accepted it.

	A pickup they took themselves is accepted on creation, so they can still
	give it away. "Before anyone accepted" means before someone else did.
	"""
	accepted_by_other = (response_of(pickup) == RESPONSE_ACCEPTED and pickup.technician_id != me)
	if pickup.pickup_arranged_by != me or accepted_by_other:
		frappe.throw(
			_("The pickup is already with {0}. Call the office to change it.").format(
				pickup.technician_name or pickup.technician_id)
		)

	visit = frappe.get_doc("Technician Visit Entry", pickup.name)
	if visit.technician_id == target.name and visit.scheduled_datetime == when and visit.slot == slot:
		return _result(visit.name, created=False)

	# `reassign_visit` is the office's, gated on `share`. The parts that matter
	# run from `nhk.api.assignment.sync_assignment` on save anyway: the share,
	# the answer reset, the order's technician fields and the timeline comment.
	visit.technician_id = target.name
	visit.scheduled_datetime = when
	visit.slot = slot
	visit.save(ignore_permissions=True)

	# The save re-stamped `assigned_by` with the caller. Put the office back.
	office = delivery.assigned_by or delivery.owner
	values = {"assigned_by": office}
	if target.name == me:
		values.update(technician_response=RESPONSE_ACCEPTED, technician_response_at=now_datetime())
	frappe.db.set_value("Technician Visit Entry", visit.name, values, update_modified=False)

	frappe.db.set_value("Sales Order", delivery.sales_order_id, "pickup_date", when,
						update_modified=False)
	for item in frappe.get_all("Sales Order Item", filters={"parent": delivery.sales_order_id},
							   pluck="name"):
		frappe.db.set_value("Sales Order Item", item, "pickup_date", when, update_modified=False)

	return _result(visit.name, created=False)


def _result(name, created):
	row = frappe.db.get_value(
		"Technician Visit Entry", name,
		["name", "technician_id", "technician_name", "technician_response",
		 "scheduled_datetime", "slot"], as_dict=True)
	row["technician_response"] = response_of(row)
	row["created"] = created
	return row


@frappe.whitelist()
def assign_pickup_for_order(sales_order_id, technician_id, pickup_date=None, slot=None, technician_category=None,
							pickup_reason=None, pickup_remark=None):
	"""Assign the pickup of an Active or Ready for Pickup rental (the office's call).

	From the desk after the order was readied without a technician, and from the
	app's Office tab (`nhk.api.ops.assign_pickup`) for any rental. A reason left
	out is the sleep study's, which is all the desk dialogs have sent so far.
	"""
	# The office's call, as `reassign_visit`: `share` is what means "the office".
	frappe.has_permission("Technician Visit Entry", "share", throw=True)

	if not sales_order_id or not frappe.db.exists("Sales Order", sales_order_id):
		frappe.throw(_("Sales Order {0} does not exist.").format(sales_order_id))

	order = frappe.get_doc("Sales Order", sales_order_id)
	if order.status not in (DELIVERED_ORDER_STATUS, READY_FOR_PICKUP):
		frappe.throw(_("Order {0} is {1}. Only an Active or Ready for Pickup order can have its pickup assigned.")
					 .format(sales_order_id, order.status))

	existing = _open_pickup(sales_order_id)
	if existing:
		frappe.throw(_("Order {0} already has an assigned pickup visit ({1}).").format(sales_order_id, existing.name))

	target = _pickup_technician(technician_id)
	when, slot = _when(pickup_date, slot)
	reason = validated_pickup_reason(pickup_reason) if pickup_reason else PICKUP_REASON

	if not technician_category:
		technician_category = frappe.db.get_value(
			"Technician Visit Entry",
			{"sales_order_id": sales_order_id, "type": "Delivery"},
			"technician_category",
			order_by="creation desc",
		)
	if not technician_category:
		# The category sets the technician's pay, so it is never guessed.
		frappe.throw(_("Order {0} has no delivery visit to take the category from. Assign the pickup from the order's visit table instead.").format(sales_order_id))

	_mark_ready_for_pickup(sales_order_id, target, when, me=None, reason=reason, remark=pickup_remark)

	office = frappe.session.user
	visit = frappe.get_doc({
		"doctype": "Technician Visit Entry",
		"sales_order_id": sales_order_id,
		"technician_id": target.name,
		"type": "Pickup",
		"status": "Assigned",
		"patient_id": order.customer,
		"technician_category": technician_category,
		"scheduled_datetime": when,
		"slot": slot,
		"pickup_arranged_by": None,
		"technician_response": RESPONSE_PENDING,
	}).insert(ignore_permissions=True)

	frappe.db.set_value("Technician Visit Entry", visit.name,
						{"owner": office, "assigned_by": office}, update_modified=False)

	if target.user_mail_id:
		frappe.share.add_docshare("Technician Visit Entry", visit.name, target.user_mail_id,
								  read=1, write=1, flags={"ignore_share_permission": True})

	line = _("Pickup assigned to {0} by office ({1}).").format(target.name1 or target.name, office)
	visit.add_comment("Comment", line)
	order.add_comment("Comment", line)

	return _result(visit.name, created=True)

