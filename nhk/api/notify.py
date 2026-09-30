"""Push a technician's phone when a visit is assigned to them, and tell the
office when the technician answers.

**To the technician.** Hooked on Technician Visit Entry `on_update`, which
runs on insert as well: a visit with no previous version is a new assignment,
and one whose `technician_user_id` changed has been reassigned. Only the
technician who now holds the job is told.

The notification says enough to decide from the lock screen -- when, customer,
address, item -- and carries Accept / Reject (decided 2026-09-29; this reverses
an earlier choice to keep patient details off an off-duty phone). Buttons need
the app to draw the notification itself, so the message is **data only**, high
priority, sent through `firebase_admin` directly: `fcm_360ithub`'s
`send_fcm_notification` always adds a notification payload, which Android draws
without buttons. Its Firebase initialisation and its log are reused.

It is queued **only after the transaction commits** -- an assignment that rolls
back must not ping anyone -- and a failure never fails the assignment.

**To the office.** `tell_office` is called when the technician accepts or
rejects (`nhk.api.staff`). The user who assigned the visit, or last reassigned
it (`assigned_by`, falling back to `owner`), gets a bell notification and a
pop-up (`nhk/public/js/nhk_desk.js`). Alert-type notifications never email.
"""

import functools
import re

import frappe
from frappe import _
from frappe.utils import cstr, format_date, format_datetime, strip_html

from nhk.api import addresses
from nhk.api.devices import tokens_for
from nhk.api.guards import OPEN_STATUSES, RESPONSE_REJECTED

#: Realtime event the desk listens for (`nhk_desk.js`).
OFFICE_EVENT = "nhk_visit_response"

#: Long text is cut here: a notification shows about two lines of each.
ADDRESS_LIMIT = 120


# ---------------------------------------------------------------------------
# to the technician
# ---------------------------------------------------------------------------


def on_visit_update(doc, method=None):
	"""`on_update` on Technician Visit Entry: notify a newly assigned technician."""
	if frappe.flags.nhk_mute_notifications:
		# Set by the test harness: fixture visits go to real technicians, and
		# their phones must not buzz on every test run.
		return
	before = doc.get_doc_before_save()
	newly_theirs = not before or before.technician_user_id != doc.technician_user_id
	if not newly_theirs or not doc.technician_user_id:
		return
	if doc.status not in OPEN_STATUSES or doc.technician_response == RESPONSE_REJECTED:
		return

	frappe.db.after_commit.add(functools.partial(_notify, doc.name, doc.technician_user_id))


def assignment_message(visit_name):
	"""What the technician is told about one visit: title, body, and the data the
	app needs to draw it and act on it. Every value is a string, as FCM requires."""
	visit = frappe.db.get_value(
		"Technician Visit Entry", visit_name,
		["name", "type", "sales_order_id", "patient_id", "patient_name", "item_code", "area",
		 "scheduled_datetime", "slot"],
		as_dict=True,
	)
	order = frappe._dict()
	if visit.sales_order_id:
		order = frappe.db.get_value(
			"Sales Order", visit.sales_order_id,
			["customer_name", "delivery_date"],
			as_dict=True,
		) or frappe._dict()

	when = _when(visit, order)
	customer = visit.patient_name or order.customer_name or _("Customer not named")
	where = addresses.for_order(visit.sales_order_id, visit.area, visit.patient_id)
	address = _one_line(where["address"]) or _("No address on the order")
	item = _item(visit)

	title = _("New {0} job · {1}").format(_(visit.type or "Visit"), when)
	body = "\n".join([
		_("Customer: {0}").format(customer),
		_("Address: {0}").format(address),
		_("Item: {0}").format(item),
	])
	return title, body, {
		"event": "assigned",
		"visit_id": visit.name,
		"task_id": visit.name,
		"type": cstr(visit.type),
		"title": title,
		"body": body,
		"when": when,
		"customer": customer,
		"address": address,
		"map_url": where["map_url"],
		"item": item,
		"sales_order_id": cstr(visit.sales_order_id),
	}


def _when(visit, order):
	if visit.scheduled_datetime:
		when = format_datetime(visit.scheduled_datetime, "dd MMM, hh:mm a")
		return "%s (%s)" % (when, _(visit.slot)) if visit.slot else when
	if order.get("delivery_date"):
		# Only 4 of 2,810 visits carry their own schedule; the order's date is what
		# the office actually fills in.
		return _("due {0}").format(format_date(order.delivery_date, "dd MMM"))
	return _("not scheduled")


def _item(visit):
	if visit.item_code:
		return frappe.db.get_value("Item", visit.item_code, "item_name") or visit.item_code
	if not visit.sales_order_id:
		return _("Not given")
	names = frappe.get_all(
		"Sales Order Item", filters={"parent": visit.sales_order_id}, pluck="item_name", order_by="idx"
	)
	if not names:
		return _("Not given")
	return names[0] if len(names) == 1 else _("{0} + {1} more").format(names[0], len(names) - 1)


def _one_line(text):
	text = re.sub(r"\s+", " ", strip_html(cstr(text))).strip(" ,")
	return text if len(text) <= ADDRESS_LIMIT else text[: ADDRESS_LIMIT - 1].rstrip() + "…"


def _notify(visit_name, user):
	# Runs after the assignment has committed, so a raise here would show the
	# office an error for an assignment that did happen. Nothing gets out.
	try:
		tokens = tokens_for(user)
		if not tokens:
			return
		title, body, data = assignment_message(visit_name)
	except Exception:
		frappe.log_error(title="Assignment notification failed", message=frappe.get_traceback())
		return

	for token in tokens:
		try:
			_send_one(token=token, title=title, body=body, data=data, user=user, visit_name=visit_name)
		except Exception:
			frappe.log_error(title="Assignment notification failed", message=frappe.get_traceback())


def _send_one(**kwargs):
	"""Queue one push. The one seam this module has to Firebase; tests replace it."""
	frappe.enqueue("nhk.api.notify.push", queue="short", enqueue_after_commit=True, **kwargs)


def push(token, title, body, data, user, visit_name):
	"""Background job: log the push the way `fcm_360ithub` does, then send it data-only."""
	from fcm_360ithub.fcm_functions import create_fcm_log, initialize_firebase
	from firebase_admin import messaging

	create_fcm_log(
		title=title, body=body, doctype="Technician Visit Entry", task_id=visit_name,
		user_doctype="User", user=user, notification_type="Alert", details=data,
	)
	initialize_firebase()
	try:
		messaging.send(messaging.Message(
			token=token,
			data={k: cstr(v) for k, v in data.items()},
			# High priority so Android wakes the app to draw it with its buttons;
			# a day's life, after which a job offer is stale.
			android=messaging.AndroidConfig(priority="high", ttl=86400),
		))
	except Exception:
		frappe.log_error(title="Assignment push failed", message=frappe.get_traceback())


# ---------------------------------------------------------------------------
# to the office
# ---------------------------------------------------------------------------


def tell_office(visit, response, reason=None):
	"""Tell whoever assigned `visit` that the technician accepted or rejected it.

	After commit, like the push: the answer is recorded first, and a failure
	here never takes it back.
	"""
	if frappe.flags.nhk_mute_notifications:
		return
	frappe.db.after_commit.add(functools.partial(
		_tell_office, visit.name, response, reason, frappe.session.user
	))


def _tell_office(visit_name, response, reason, technician_user):
	try:
		visit = frappe.db.get_value(
			"Technician Visit Entry", visit_name,
			["name", "type", "technician_name", "technician_id", "sales_order_id",
			 "patient_name", "assigned_by", "owner"],
			as_dict=True,
		)
		to = visit.assigned_by or visit.owner
		if not to or to == technician_user or to == "Guest":
			return

		who = visit.technician_name or visit.technician_id
		customer = visit.patient_name
		if not customer and visit.sales_order_id:
			customer = frappe.db.get_value("Sales Order", visit.sales_order_id, "customer_name")
		customer = customer or visit.name
		if response == RESPONSE_REJECTED:
			subject = _("{0} rejected {1} ({2}): {3}").format(who, customer, _(visit.type), reason or _("no reason"))
		else:
			subject = _("{0} accepted {1} ({2})").format(who, customer, _(visit.type))

		_office_alert(to, subject, visit, response, reason)
	except Exception:
		frappe.log_error(title="Office alert failed", message=frappe.get_traceback())


def _office_alert(to, subject, visit, response, reason):
	"""The bell notification and the pop-up. Tests replace this."""
	frappe.get_doc({
		"doctype": "Notification Log",
		"for_user": to,
		"from_user": frappe.session.user,
		"type": "Alert",
		"document_type": "Technician Visit Entry",
		"document_name": visit.name,
		"subject": subject,
	}).insert(ignore_permissions=True)
	frappe.publish_realtime(OFFICE_EVENT, {
		"visit": visit.name,
		"sales_order": visit.sales_order_id,
		"response": response,
		"reason": reason,
		"message": subject,
	}, user=to)
	frappe.db.commit()
