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
from nhk.api.visits import (
	SLOTS,
	STILL_OUT_STATUSES,
	_assert_office_may_change,
	_mark_rows_picked_up,
	complete_visit,
	pickup_rows,
)

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


def _mark_ready_for_pickup(sales_order, target, when, me=None, reason=PICKUP_REASON, remark=None,
						   statuses=STILL_OUT_STATUSES):
	"""The Sales Order half of `make_ready_for_pickup`, without its commit.

	`reason` and `remark` default to the sleep study's (ADR-0006). The office
	passes its own for every other rental (`nhk.api.ops.assign_pickup`).

	Only rows at one of `statuses` move, still at the patient's home by default.
	`make_ready_for_pickup` moves every row, so readying an order whose other
	item was already collected put that item back to Ready for Pickup
	(SAL-ORD-2026-11982 on nhk.local, 2026-10-21). Returns the rows it moved,
	as `name` and `item_code`.
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

	rows = frappe.get_all("Sales Order Item", filters={"parent": sales_order, "child_status": ("in", statuses)},
						  fields=["name", "item_code"], order_by="idx asc")
	for row in rows:
		item = frappe.get_doc("Sales Order Item", row.name)
		item.child_status = READY_FOR_PICKUP
		item.pickup_date = when
		item.pickup_reason = reason
		item.pickup_remark = remark
		item.technician_id_after_delivered = target.name if target else None
		item.save(ignore_permissions=True)
	return rows


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
	if order.status not in ITEM_PICKUP_ORDER_STATUSES:
		frappe.throw(_("Order {0} is {1}. Only an Active or Ready for Pickup order can have its pickup assigned.")
					 .format(sales_order_id, order.status))

	existing = _open_pickup(sales_order_id)
	if existing:
		frappe.throw(_("Order {0} already has an assigned pickup visit ({1}).").format(sales_order_id, existing.name))

	target = _pickup_technician(technician_id)
	when, slot = _when(pickup_date, slot)
	# Left out, keep what the order was readied with, as the desk's Ready for
	# Pickup leaves it; the sleep study's defaults only for a sleep study.
	reason = validated_pickup_reason(pickup_reason) if pickup_reason else (order.pickup_reason or PICKUP_REASON)
	technician_category = _pickup_category(sales_order_id, technician_category)
	if not pickup_remark and not cstr(technician_category).startswith(SLEEP_STUDY_PREFIX):
		pickup_remark = order.pickup_remark or _("Pickup assigned by office.")

	rows = _mark_ready_for_pickup(sales_order_id, target, when, me=None, reason=reason, remark=pickup_remark)
	if not rows:
		frappe.throw(_("Nothing on order {0} is still with the patient.").format(sales_order_id))
	# The visit names its rows, so closing it moves only them: an item already
	# collected or back at the office stays where it is.
	visit = _create_office_pickup(order, target, technician_category, when, slot, rows)

	line = _("Pickup assigned to {0} by office ({1}).").format(target.name1 or target.name, frappe.session.user)
	visit.add_comment("Comment", line)
	order.add_comment("Comment", line)

	return _result(visit.name, created=True)


@frappe.whitelist()
def ready_order_for_pickup(sales_order_id, pickup_date, pickup_reason, pickup_remark):
	"""The order's own Ready for Pickup, for the items still at the patient's home.

	Replaces the desk's call to `make_ready_for_pickup`, which set every row
	Ready for Pickup, collected or not. Rows already readied keep their pickup
	and technician; only `Active` rows move. No visit is made: Assign Pickup
	gives it out.
	"""
	frappe.has_permission("Sales Order", "write", sales_order_id, throw=True)
	order = frappe.get_doc("Sales Order", sales_order_id)
	if order.status not in ITEM_PICKUP_ORDER_STATUSES:
		frappe.throw(_("Order {0} is {1}, so it cannot be readied for pickup.").format(sales_order_id, order.status))

	reason = validated_pickup_reason(pickup_reason)
	rows = _mark_ready_for_pickup(sales_order_id, target=None, when=get_datetime(pickup_date), reason=reason,
								  remark=pickup_remark or "", statuses=(DELIVERED_ORDER_STATUS,))
	if not rows:
		frappe.throw(_("No item on order {0} is Active.").format(sales_order_id))
	return {"status": READY_FOR_PICKUP, "rows": [r.name for r in rows]}


def _pickup_category(sales_order, technician_category=None):
	"""The category a pickup is paid at: the one given, else the delivery's."""
	if not technician_category:
		technician_category = frappe.db.get_value(
			"Technician Visit Entry",
			{"sales_order_id": sales_order, "type": "Delivery"},
			"technician_category",
			order_by="creation desc",
		)
	if not technician_category:
		# The category sets the technician's pay, so it is never guessed.
		frappe.throw(_("Order {0} has no delivery visit to take the category from. Assign the pickup from the order's visit table instead.").format(sales_order))
	return technician_category


def _create_office_pickup(order, target, technician_category, when, slot, rows=()):
	"""A Pickup visit the office gave out: owned by the caller, shared with `target`.

	`rows` are the Sales Order Item rows it collects; none means the whole order.
	"""
	office = frappe.session.user
	visit = frappe.get_doc({
		"doctype": "Technician Visit Entry",
		"sales_order_id": order.name,
		"technician_id": target.name,
		"type": "Pickup",
		"status": "Assigned",
		"patient_id": order.customer,
		"technician_category": technician_category,
		"scheduled_datetime": when,
		"slot": slot,
		"pickup_arranged_by": None,
		"technician_response": RESPONSE_PENDING,
	})
	for row in rows:
		visit.append("items", {"sales_order_item": row.name, "item_code": row.item_code})
	_label_items(visit)
	visit.insert(ignore_permissions=True)

	frappe.db.set_value("Technician Visit Entry", visit.name,
						{"owner": office, "assigned_by": office}, update_modified=False)

	if target.user_mail_id:
		frappe.share.add_docshare("Technician Visit Entry", visit.name, target.user_mail_id,
								  read=1, write=1, flags={"ignore_share_permission": True})
	return visit


# ---------------------------------------------------------------------------
# Item pickups
#
# A rental's items can come back on different days: one device early, the rest
# at the end. The office readies chosen rows for Pickup rather than the whole
# order. A Pickup visit is still one trip, paid once by category and distance,
# so rows given to a technician who already has an open pickup on the order join
# that visit (decided 2026-10-21). Until then the per-row button made one unpaid
# visit per item (`.scratch/per-item-pickup/spec.md`).
# ---------------------------------------------------------------------------

#: Order statuses an item pickup can be given out from. `Partially Closed` is
#: what the per-row Submitted to Office leaves while other items are still out.
ITEM_PICKUP_ORDER_STATUSES = (DELIVERED_ORDER_STATUS, READY_FOR_PICKUP, "Partially Closed")


@frappe.whitelist()
def assign_item_pickup(sales_order_id, rows, technician_id, technician_category=None, pickup_date=None,
					   slot=None, pickup_reason=None, pickup_remark=None):
	"""Ready some of a rental's items for Pickup and give them to a technician.

	`rows` are Sales Order Item row names, each still `Active`. If the technician
	already has an open Pickup visit on the order, the rows join it and keep its
	date, slot and category: it is the same trip. Otherwise a new visit is made.
	The order turns Ready for Pickup only once no row is left Active.
	"""
	frappe.has_permission("Technician Visit Entry", "share", throw=True)

	if not sales_order_id or not frappe.db.exists("Sales Order", sales_order_id):
		frappe.throw(_("Sales Order {0} does not exist.").format(sales_order_id))
	order = frappe.get_doc("Sales Order", sales_order_id)
	if order.status not in ITEM_PICKUP_ORDER_STATUSES:
		frappe.throw(_("Order {0} is {1}, so its items cannot be readied for pickup.")
					 .format(sales_order_id, order.status))

	chosen = _chosen_rows(order, rows)
	carried = _rows_on_open_pickups(sales_order_id)
	for row in chosen:
		if row.name in carried:
			visit = carried[row.name]
			frappe.throw(_("{0} is already on pickup {1} with {2}.").format(
				row.item_code, visit.name, visit.technician_name or visit.technician_id))

	target = _pickup_technician(technician_id)
	reason = validated_pickup_reason(pickup_reason) if pickup_reason else PICKUP_REASON

	visit = _open_pickup_of(sales_order_id, target.name)
	if visit:
		when, slot = visit.scheduled_datetime, visit.slot
	else:
		when, slot = _when(pickup_date, slot)
		technician_category = _pickup_category(sales_order_id, technician_category)

	for row in chosen:
		item = frappe.get_doc("Sales Order Item", row.name)
		item.child_status = READY_FOR_PICKUP
		item.pickup_date = when
		item.pickup_reason = reason
		item.pickup_remark = pickup_remark
		item.technician_id_after_delivered = target.name
		item.save(ignore_permissions=True)

	if order.status == DELIVERED_ORDER_STATUS and not _rows_in(sales_order_id, (DELIVERED_ORDER_STATUS,)):
		# Fresh: saving the copy read above would write its rows back as they were.
		order = frappe.get_doc("Sales Order", sales_order_id)
		order.status = READY_FOR_PICKUP
		order.pickup_date = when
		order.pickup_reason = reason
		order.pickup_remark = pickup_remark
		order.custom_technician_id_pickup = target.name
		order.save(ignore_permissions=True)

	codes = ", ".join(row.item_code for row in chosen)
	created = not visit
	if visit:
		_adopt_legacy_item(visit)
		for row in chosen:
			visit.append("items", {"sales_order_item": row.name, "item_code": row.item_code})
		_label_items(visit)
		visit.save(ignore_permissions=True)
		line = _("{0} added to pickup {1} with {2} by office ({3}).").format(
			codes, visit.name, target.name1 or target.name, frappe.session.user)
	else:
		visit = _create_office_pickup(order, target, technician_category, when, slot, chosen)
		line = _("Pickup of {0} assigned to {1} by office ({2}).").format(
			codes, target.name1 or target.name, frappe.session.user)

	visit.add_comment("Comment", line)
	order.add_comment("Comment", line)
	return _result(visit.name, created=created)


@frappe.whitelist()
def release_item_pickup(sales_order_id, row):
	"""Put one Ready for Pickup row back to Active, taking it off its pickup.

	The desk's Back To Active. A pickup left with nothing to collect is closed
	rather than left open at no pay. A row whose pickup the technician already
	closed is refused: that visit is the office's to correct, not the row.
	"""
	frappe.has_permission("Technician Visit Entry", "share", throw=True)

	if not sales_order_id or not frappe.db.exists("Sales Order", sales_order_id):
		frappe.throw(_("Sales Order {0} does not exist.").format(sales_order_id))
	order = frappe.get_doc("Sales Order", sales_order_id)
	(item,) = _chosen_rows(order, [row], status=READY_FOR_PICKUP)

	visit = _rows_on_open_pickups(sales_order_id).get(item.name)
	if visit and not pickup_rows(visit):
		frappe.throw(_("{0} is on pickup {1} for the whole order. Reassign or close that visit instead.")
					 .format(item.item_code, visit.name))

	doc = frappe.get_doc("Sales Order Item", item.name)
	doc.child_status = DELIVERED_ORDER_STATUS
	doc.pickup_date = None
	doc.save(ignore_permissions=True)

	if visit:
		_adopt_legacy_item(visit)
		visit.items = [r for r in visit.items if r.sales_order_item != item.name]
		_label_items(visit)
		if not visit.items:
			visit.status = "Closed"
		visit.save(ignore_permissions=True)
		line = (_("{0} taken off pickup {1}; nothing left to collect, so it is closed.")
				if visit.status == "Closed" else _("{0} taken off pickup {1}.")).format(item.item_code, visit.name)
		visit.add_comment("Comment", line)
		order.add_comment("Comment", line)

	if order.status == READY_FOR_PICKUP:
		# Fresh, as in `assign_item_pickup`.
		order = frappe.get_doc("Sales Order", sales_order_id)
		order.status = DELIVERED_ORDER_STATUS
		order.pickup_date = None
		order.save(ignore_permissions=True)

	return {"sales_order_item": item.name, "child_status": DELIVERED_ORDER_STATUS,
			"pickup_visit": visit.name if visit else None,
			"pickup_status": visit.status if visit else None}


@frappe.whitelist()
def item_pickup_visit(sales_order_id, row):
	"""The open Pickup visit a row is on, for the desk's Picked Up to show first.

	`None` when the row is on none. Otherwise who has it and every item it
	carries: Picked Up closes the visit, so all of them go together.
	"""
	frappe.has_permission("Technician Visit Entry", "share", throw=True)
	visit = _rows_on_open_pickups(sales_order_id).get(row)
	if not visit:
		return None
	rows = pickup_rows(visit) or frappe.get_all("Sales Order Item", filters={"parent": sales_order_id},
												pluck="name")
	return {
		"name": visit.name,
		"technician_id": visit.technician_id,
		"technician_name": visit.technician_name or visit.technician_id,
		"technician_category": visit.technician_category,
		"item_codes": [frappe.db.get_value("Sales Order Item", r, "item_code") for r in rows],
	}


@frappe.whitelist()
def pick_up_item(sales_order_id, row, kilometers=None):
	"""The desk's per-row Picked Up.

	A row on an open Pickup visit closes that visit, at `kilometers`, exactly as
	the technician closing it would: every item it carries moves, because it is
	one trip (`nhk.api.visits.complete_visit`). Left open, the visit was never
	paid, and the technician closing it later moved the order's other items too
	(SAL-ORD-2026-12054, 19 Oct). Items that did not come back are taken off
	first with Back To Active. A row on no visit -- the office collected it --
	moves alone.
	"""
	frappe.has_permission("Technician Visit Entry", "share", throw=True)

	if not sales_order_id or not frappe.db.exists("Sales Order", sales_order_id):
		frappe.throw(_("Sales Order {0} does not exist.").format(sales_order_id))
	order = frappe.get_doc("Sales Order", sales_order_id)
	(item,) = _chosen_rows(order, [row], status=READY_FOR_PICKUP)

	visit = _rows_on_open_pickups(sales_order_id).get(item.name)
	if not visit:
		_mark_rows_picked_up(sales_order_id, [item.name], frappe.utils.nowdate())
		return {"sales_order_item": item.name, "pickup_visit": None}

	_assert_office_may_change(visit)
	complete_visit(visit, kilometers)
	line = _("Pickup {0} closed by office ({1}) from the order's item table, at {2} km.").format(
		visit.name, frappe.session.user, visit.kilometers)
	visit.add_comment("Comment", line)
	order.add_comment("Comment", line)
	return {"sales_order_item": item.name, "pickup_visit": visit.name, "status": visit.status,
			"charges": visit.charges}


def _chosen_rows(order, rows, status=DELIVERED_ORDER_STATUS):
	"""The order's rows named in `rows`, each required to be at `status`."""
	names = frappe.parse_json(rows) if isinstance(rows, str) else rows
	if not names:
		frappe.throw(_("Pick the items to pick up."))
	by_name = {row.name: row for row in order.items}
	chosen = []
	for name in dict.fromkeys(names):
		row = by_name.get(name)
		if not row:
			frappe.throw(_("Row {0} is not on order {1}.").format(name, order.name))
		if row.child_status != status:
			frappe.throw(_("{0} is {1}. Only an item that is {2} can do this.")
						 .format(row.item_code, row.child_status or _("not set"), status))
		chosen.append(row)
	return chosen


def _rows_on_open_pickups(sales_order):
	"""{Sales Order Item row: its open Pickup visit}. A whole-order pickup holds every row."""
	carried = {}
	for name in frappe.get_all("Technician Visit Entry",
							   filters={"sales_order_id": sales_order, "type": "Pickup", "status": "Assigned"},
							   pluck="name"):
		visit = frappe.get_doc("Technician Visit Entry", name)
		rows = pickup_rows(visit) or frappe.get_all("Sales Order Item", filters={"parent": sales_order},
													 pluck="name")
		for row in rows:
			carried[row] = visit
	return carried


def _open_pickup_of(sales_order, technician_id):
	"""This technician's open item Pickup visit on the order, if any."""
	name = frappe.db.get_value(
		"Technician Visit Entry",
		{"sales_order_id": sales_order, "type": "Pickup", "status": "Assigned", "technician_id": technician_id},
		"name", order_by="creation desc")
	return frappe.get_doc("Technician Visit Entry", name) if name else None


def _rows_in(sales_order, statuses):
	return frappe.get_all("Sales Order Item",
						  filters={"parent": sales_order, "child_status": ("in", statuses)}, pluck="name")


def _adopt_legacy_item(visit):
	"""Give a visit from the old per-row button its row in `items`.

	Those visits carry the item on `item_code` alone (`pickup_rows`), so a row
	added or removed now would otherwise drop it.
	"""
	if visit.get("items"):
		return
	for name in pickup_rows(visit):
		visit.append("items", {"sales_order_item": name,
							   "item_code": frappe.db.get_value("Sales Order Item", name, "item_code")})


def _label_items(visit):
	"""`item_code` is what the app's visit tile shows: the items, as one line."""
	if visit.get("items"):
		visit.item_code = ", ".join(r.item_code for r in visit.items if r.item_code)

