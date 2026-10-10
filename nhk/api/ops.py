"""The office's work from the NHK Technician app: the Office tab.

Giving out field work used to need the desk. Sleep studies go in at night, a
rejection arrives in the evening, and whoever could reassign it is away from a
laptop. The Office tab lets an `NHK Admin` do it from the phone (bench spec
`office-assignment-on-mobile`, 2026-10-10).

Every endpoint here starts with `require_office`, then calls the function the
desk already uses, so the desk's own permission checks still run behind it.

Why the gate is the `NHK Admin` role and not `share` on Technician Visit Entry,
which is what "the office" means on the desk (`nhk.api.assignment.reassign_visit`):
`share` is also held by `System Manager`, and the phone is meant to be the
narrower surface. Decided 2026-10-10.

Who is a technician is still decided by `Technician Details`, never by role
(`nhk.api.guards`). One person can be both, and the app shows them both halves.
"""

import re

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate
from frappe.utils import today as _today  # `today` is the Today board's endpoint

from nhk.api.guards import OPEN_STATUSES, RESPONSE_PENDING, NotATechnician, current_technician

#: The role that opens the Office tab.
OFFICE_ROLE = "NHK Admin"


class NotOffice(frappe.PermissionError):
	"""The session user does not hold `NHK Admin`."""


def is_office(user: str | None = None) -> bool:
	"""Whether `user` (the session user by default) may use the Office tab.

	Administrator is refused, as `current_technician` refuses it: it is not a
	person in the office, and letting it through would make every test of the
	gate pass on a superuser.
	"""
	user = user or frappe.session.user
	if user in ("Guest", "Administrator"):
		return False
	return OFFICE_ROLE in frappe.get_roles(user)


def require_office() -> None:
	if not is_office():
		frappe.throw(_("Only {0} users can do this from the app.").format(OFFICE_ROLE), NotOffice)


@frappe.whitelist()
def whoami():
	"""Which halves of the app the caller gets: technician, office, or both.

	Never throws for a signed-in user, so the app can call it right after login
	and build its tabs from the answer. A login linked to no Technician Details
	record, or to more than one, is not a technician here, as `current_technician`
	decides.
	"""
	try:
		technician_id = current_technician()
	except NotATechnician:
		technician_id = None
		# `frappe.throw` queued its message before raising. Left there, it rides
		# back in `_server_messages` and the app shows it as an error.
		frappe.clear_messages()

	return {
		"is_technician": bool(technician_id),
		"is_office": is_office(),
		"technician_id": technician_id,
	}


# ---------------------------------------------------------------------------
# Sales Orders: the list and one order
# ---------------------------------------------------------------------------

#: A page of the list. The phone scrolls for more; it never asks for everything.
PAGE_SIZE = 30
MAX_PAGE_SIZE = 100

#: The status whose list starts at a window rather than at the beginning of time.
#: 5,738 Sales and Service orders sit in `Order` on nhk.local (2026-10-10), 2,550
#: of them from 2024-25: most were sold over the counter and never needed a
#: technician. A search, or `since="all"`, reaches the rest.
WINDOWED_STATUS = "Order"
DEFAULT_WINDOW_DAYS = 60

#: Whether the order still has an item to deliver -- the desk's `allow_delivery`,
#: which gates Assign Technician on a Service order (`sales_order.js:624`).
_UNDELIVERED_ITEM = """exists(select 1 from `tabSales Order Item` i where i.parent = so.name
	and ifnull(i.delivered_by_supplier, 0) = 0 and i.qty > ifnull(i.delivered_qty, 0))"""

#: The order fields the assign rules read, and nothing else does. Not sent.
_RULE_FIELDS = ("per_billed", "per_delivered", "skip_delivery_note", "has_undelivered_item")

#: What the list says about each order. `customer_mobile_no` is the mobile the
#: desk shows and searches; it is filled on 20,403 of 20,701 submitted orders.
_ORDER_FIELDS = f"""so.name, so.order_type, so.status, so.customer, so.customer_name,
	so.customer_mobile_no, so.transaction_date, so.delivery_date, so.end_date,
	so.grand_total, so.per_billed, so.per_delivered, so.skip_delivery_note,
	{_UNDELIVERED_ITEM} as has_undelivered_item"""

#: `get_sales_order_details` returns the order's whole ledger. The phone shows
#: what is owed, not every entry behind it -- as `nhk.api.staff.job` does.
_LEDGER_KEYS = ("payment_entries", "journal_entries", "all_payment_entries")


@frappe.whitelist()
def sales_orders(order_type=None, status=None, search=None, since=None, cursor=None, limit=PAGE_SIZE,
				 month=None, shortcut=None):
	"""One page of submitted Sales Orders, with counts for the filters and shortcuts.

	`month` (`YYYY-MM`) limits the list to that month, as the Office tab asks
	(2026-10-10). `shortcut` is one of `MONTH_SHORTCUTS` and replaces
	`order_type` / `status` with its own rule; without one, `order_type` and
	`status` filter the month's orders by hand. Without `month` the list is
	every order, as before.

	`search` matches the order's name, the customer's name, or their mobile (by
	digits, so spaces and a +91 do not matter). Without `month`, `since` is a
	date, `"all"`, or left out: left out, status `Order` without a search starts
	at `DEFAULT_WINDOW_DAYS` ago, echoed back as `since`.

	`counts` say how many orders each Order Type and each status would show with
	the *other* filters left as they are. `shortcuts` are the month's three
	shortcuts with their counts under the same search.

	Pages are keyed on the sort date and the name, not offsets, so an order
	submitted while someone scrolls does not shift the rest by one.
	"""
	require_office()

	limit = min(max(cint(limit) or PAGE_SIZE, 1), MAX_PAGE_SIZE)
	search = (search or "").strip()
	bounds = _month_bounds(month) if month else None

	if shortcut:
		if not bounds:
			bounds = _month_bounds(None)
		where, values, sort, ascending = _shortcut_scope(shortcut, bounds, search)
		filters = None
		applied_since = None
	else:
		if bounds:
			applied_since = None
			filters = {"order_type": order_type or None, "status": status or None, "search": search,
					   "since": bounds[0], "until": bounds[1]}
		else:
			applied_since = _window(since, status, search)
			filters = {"order_type": order_type or None, "status": status or None, "search": search,
					   "since": applied_since}
		where, values = _where(**filters)
		sort, ascending = "transaction_date", False

	if cursor:
		after_date, after_name = _parse_cursor(cursor)
		op = ">" if ascending else "<"
		where += f""" and (so.{sort} {op} %(after_date)s
			or (so.{sort} = %(after_date)s and so.name {op} %(after_name)s))"""
		values.update(after_date=after_date, after_name=after_name)

	direction = "asc" if ascending else "desc"
	rows = frappe.db.sql(
		f"""select {_ORDER_FIELDS} from `tabSales Order` so where {where}
		order by so.{sort} {direction}, so.name {direction} limit %(limit)s""",
		{**values, "limit": limit + 1}, as_dict=True,
	)
	more = len(rows) > limit
	rows = rows[:limit]
	last = rows[-1] if rows else None

	_add_list_details(rows)

	return {
		"rows": rows,
		"next_cursor": "%s|%s" % (last[sort], last.name) if more else None,
		"since": str(applied_since) if applied_since else None,
		"month": bounds[0].strftime("%Y-%m") if bounds else None,
		"counts": {
			"order_type": _counts("order_type", filters) if filters else {},
			"status": _counts("status", filters) if filters else {},
		},
		"shortcuts": _shortcuts(search, bounds or _month_bounds(None)),
	}


#: The Office tab's shortcuts for a month (2026-10-10), in order: key, label.
#: Three, each something to look at or act on that month:
#:
#: * **total** -- the orders taken that month.
#: * **to_assign** -- that month's Sales and Service orders still in `Order`:
#:   no technician given yet (`assign_technician`).
#: * **pickups_due** -- rentals still out (`Active` or `Ready for Pickup`)
#:   whose `end_date` falls in the month; for the current month, overdue ones
#:   too. Soonest end first (`assign_pickup`).
MONTH_SHORTCUTS = (
	("total", "Total"),
	("to_assign", "To assign"),
	("pickups_due", "Pickups due"),
)

#: The rental statuses a pickup is still to be done from.
_PICKUP_PENDING_STATUSES = ("Active", "Ready for Pickup")


def _month_bounds(month):
	"""`(first day, first day of the next month)` for `YYYY-MM`, this month if None."""
	from frappe.utils import get_first_day

	# Checked by shape first: `getdate` reads "October-01" as a date.
	if month and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(month)):
		frappe.throw(_("Month must look like 2026-10."))
	start = get_first_day(getdate(f"{month}-01") if month else getdate(_today()))
	return start, add_days(frappe.utils.get_last_day(start), 1)


def _shortcut_scope(key, bounds, search):
	"""The `where`, its values, and the sort for one of `MONTH_SHORTCUTS`."""
	start, end = bounds
	if key == "total":
		where, values = _where(search=search, since=start, until=end)
		return where, values, "transaction_date", False
	if key == "to_assign":
		where, values = _where(status=UNASSIGNED_ORDER_STATUS, search=search, since=start, until=end)
		where += " and so.order_type in %(assignable_types)s"
		values["assignable_types"] = tuple(ASSIGNMENT_VISIT_TYPES)
		return where, values, "transaction_date", False
	if key == "pickups_due":
		where, values = _where(order_type="Rental", search=search)
		current = start <= getdate(_today()) < end
		where += """ and so.status in %(pickup_pending)s and so.end_date is not null
			and so.end_date < %(end)s"""
		if not current:
			# Another month: only what fell due in it. This month: overdue too.
			where += " and so.end_date >= %(start)s"
		values.update(pickup_pending=_PICKUP_PENDING_STATUSES, start=start, end=end)
		return where, values, "end_date", True
	frappe.throw(_("There is no shortcut called {0}.").format(key))


def _shortcuts(search, bounds):
	"""Each of the month's shortcuts and how many orders it shows now."""
	out = []
	for key, label in MONTH_SHORTCUTS:
		where, values, _sort, _asc = _shortcut_scope(key, bounds, search)
		count = frappe.db.sql(f"select count(*) from `tabSales Order` so where {where}", values)[0][0]
		out.append({"key": key, "label": label, "count": count})
	return out


@frappe.whitelist()
def sales_order(name):
	"""One submitted Sales Order: customer, address, items, what is owed, its visits.

	The order block is `get_sales_order_details` -- the figures the job screen
	and the desk's "Enter Payment Details" use -- without the ledger, with the
	resolved address and Maps link from `nhk.api.addresses`. `payment_status` is
	Pending or Paid as the office's day block reads it, not the stored field.

	Visits come from `nhk.api.visits.for_sales_order`, the Sales Order form's own
	table, so the phone and the desk show the same rows. Their `actions` are the
	phone's (`_set_visit_actions`), not the desk's: the phone cannot complete a
	visit or settle an extra payment.
	"""
	require_office()

	order = frappe.db.get_value(
		"Sales Order", name,
		["name", "docstatus", "order_type", "status", "customer", "transaction_date", "delivery_date",
		 "end_date", "pickup_date", "grand_total", "reason_for_payment_pending",
		 "per_billed", "per_delivered", "skip_delivery_note"],
		as_dict=True,
	)
	if not order or order.docstatus != 1:
		frappe.throw(_("Sales Order {0} is not a submitted order.").format(name), frappe.DoesNotExistError)
	from nhk.api.pickup import _open_pickup

	order["has_undelivered_item"] = _has_undelivered_item(name)
	actions = _order_actions(order, has_open_pickup=bool(_open_pickup(name)))
	for field in _RULE_FIELDS:
		order.pop(field)

	from nhk.api import addresses, visits
	from nhk.custom_script import get_sales_order_details

	detail = get_sales_order_details(name)
	for key in _LEDGER_KEYS:
		detail.pop(key, None)
	where = addresses.for_order(name, customer=order.customer)
	order.pop("docstatus")

	order_visits = visits.for_sales_order(name)
	_set_visit_actions(order_visits)

	return {
		"order": {
			**detail,
			**order,
			"customer_name": (detail.get("customer_name") or "").strip(),
			"payment_status": _payment_status(detail),
			"address": where["address"],
			"map_url": where["map_url"],
		},
		"visits": order_visits,
		"actions": actions,
		"assign": _assign_choices(order, actions),
	}


def _window(since, status, search):
	"""The earliest `transaction_date` the list starts at, or None for no limit."""
	if since == "all":
		return None
	if since:
		return getdate(since)
	if status == WINDOWED_STATUS and not search:
		return getdate(add_days(_today(), -DEFAULT_WINDOW_DAYS))
	return None


def _where(order_type=None, status=None, search="", since=None, until=None):
	"""The list's `where` clause for the filters given, and its values.

	`since` and `until` bound `transaction_date`, `until` exclusive.
	"""
	clauses = ["so.docstatus = 1"]
	values = {}
	if order_type:
		clauses.append("so.order_type = %(order_type)s")
		values["order_type"] = order_type
	if status:
		clauses.append("so.status = %(status)s")
		values["status"] = status
	if since:
		clauses.append("so.transaction_date >= %(since)s")
		values["since"] = since
	if until:
		clauses.append("so.transaction_date < %(until)s")
		values["until"] = until
	if search:
		matches = ["so.name like %(like)s", "so.customer_name like %(like)s"]
		# `%` and `_` typed into the search are text, not wildcards.
		literal = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
		values["like"] = "%" + literal + "%"
		digits = re.sub(r"\D", "", search)
		if len(digits) >= 4:
			# The last ten digits: a number typed with +91 still matches one
			# stored without it, and the other way round.
			matches.append("replace(replace(so.customer_mobile_no, ' ', ''), '-', '') like %(digits)s")
			values["digits"] = "%" + digits[-10:] + "%"
		clauses.append("(" + " or ".join(matches) + ")")
	return " and ".join(clauses), values


def _counts(field, filters):
	"""How many orders each value of `field` has, under every other filter."""
	where, values = _where(**{**filters, field: None})
	return dict(frappe.db.sql(
		f"select so.{field}, count(*) from `tabSales Order` so where {where} group by so.{field}",
		values,
	))


def _parse_cursor(cursor):
	try:
		after_date, after_name = cursor.split("|", 1)
		return getdate(after_date), after_name
	except Exception:
		frappe.throw(_("That page of orders has expired. Pull down to refresh."))


def _add_list_details(rows):
	"""Items, the open visits and `actions`, on one page of orders.

	No payment status on the list. Reading it means the order's whole ledger
	(`get_sales_order_details`), about 35 ms an order on nhk.local: 1.1 s of a
	1.3 s page. The list is for finding an order; its detail says what is owed.
	"""
	if not rows:
		return
	names = [r.name for r in rows]

	items = {}
	for parent, item_name in frappe.db.sql(
		"select parent, item_name from `tabSales Order Item` where parent in %(n)s order by parent, idx",
		{"n": names},
	):
		items.setdefault(parent, []).append(item_name)

	open_visits = {}
	for visit in frappe.db.sql(
		"""select name, sales_order_id, type, technician_id, technician_name, scheduled_datetime, slot,
			ifnull(nullif(technician_response, ''), 'Pending') as technician_response
		from `tabTechnician Visit Entry`
		where sales_order_id in %(n)s and status in %(open)s
		order by creation desc""",
		{"n": names, "open": OPEN_STATUSES}, as_dict=True,
	):
		visit["technician_name"] = (visit.technician_name or "").strip()
		open_visits.setdefault(visit.sales_order_id, []).append(visit)

	for row in rows:
		row["customer_name"] = (row.customer_name or "").strip()
		row["items"] = items.get(row.name, [])
		row["open_visits"] = open_visits.get(row.name, [])
		row["actions"] = _order_actions(
			row, has_open_pickup=any(v.type == "Pickup" for v in row["open_visits"]))
		for field in _RULE_FIELDS:
			row.pop(field, None)


def _payment_status(detail):
	"""Pending or Paid, as `nhk.api.office._orders` reads it from the same figures."""
	owed = ("Unpaid", "Partially Paid")
	pending = detail.get("rental_payment_status") in owed or detail.get("security_deposit_payment_status") in owed
	return "Pending" if pending else "Paid"


def _order_actions(order, has_open_pickup=False):
	"""What the office may do to this order from the phone now, as action keys.

	`order` needs the list's fields and `_RULE_FIELDS`. Each endpoint checks the
	same rule again when the action arrives.
	"""
	actions = []
	if not _why_not_assign_technician(order):
		actions.append("assign_technician")
	if _pickup_can_be_assigned(order, has_open_pickup):
		actions.append("assign_pickup")
	return actions


def _assign_choices(order, actions):
	"""What the assign sheet offers for each assign action open on the order.

	No default category. It selects the slab the technician is paid from, so it
	is the office's choice every time, as the desk's dialog makes it (`reqd`).
	"""
	from nhk.api.pickup import DEFAULT_SLOT
	from nhk.api.visits import SLOTS

	choices = {}
	if "assign_technician" in actions:
		choices["assign_technician"] = {
			"visit_type": ASSIGNMENT_VISIT_TYPES[order.order_type],
			"categories": frappe.get_all("Technician Category", order_by="name asc", pluck="name"),
			"slots": list(SLOTS),
			"default_slot": DEFAULT_SLOT,
		}
	if "assign_pickup" in actions:
		from nhk.api.pickup import pickup_reasons

		choices["assign_pickup"] = {
			"reasons": pickup_reasons(),
			# Not for a sleep study: the desk asks none (`assign_pickup`).
			"reason_required": not _is_sleep_study_order(order.name),
			"categories": frappe.get_all("Technician Category", order_by="name asc", pluck="name"),
			# The delivery's, as `assign_pickup_for_order` takes it when none is
			# given. None when the order has no delivery: then the office picks.
			"default_category": _delivery_category(order.name),
			"slots": list(SLOTS),
			"default_slot": DEFAULT_SLOT,
			"default_date": str(add_days(_today(), 1)),
		}
	return choices


def _has_undelivered_item(sales_order):
	return bool(frappe.db.sql(
		f"select {_UNDELIVERED_ITEM} from `tabSales Order` so where so.name = %s", sales_order)[0][0])


# ---------------------------------------------------------------------------
# Assign Technician: the first technician on a Sales or Service order
# ---------------------------------------------------------------------------

#: The visit a Sales Order's Assign Technician creates, by Order Type. Sales is
#: an installation; Service is a service call (`nhk.api.staff.MONTH_CARDS`).
ASSIGNMENT_VISIT_TYPES = {
	"Sales": "Technician Assignment For Sales",
	"Service": "Technician Assignment For Service",
}

#: The order status Assign Technician starts from, and the one it leaves.
UNASSIGNED_ORDER_STATUS = "Order"
ASSIGNED_ORDER_STATUS = "Technician Assigned"


def _why_not_assign_technician(order):
	"""Why the order cannot be given its first technician now, or None if it can.

	The desk's own rule for showing the button (`sales_order.js:979`, `:1131`):
	a Sales order not fully billed, or a Service order not fully delivered with
	an item still to deliver, in status `Order`.
	"""
	visit_type = ASSIGNMENT_VISIT_TYPES.get(order.order_type)
	if not visit_type:
		return _("Assign Technician is for Sales and Service orders. {0} is a {1} order.").format(
			order.name, order.order_type)
	if order.status != UNASSIGNED_ORDER_STATUS:
		return _("Order {0} is {1}. Reassign its visit instead.").format(order.name, order.status)
	if order.order_type == "Sales" and flt(order.per_billed, 2) >= 100:
		return _("Order {0} is fully billed.").format(order.name)
	if order.order_type == "Service" and (
		flt(order.per_delivered, 2) >= 100 or cint(order.skip_delivery_note) or not order.has_undelivered_item
	):
		return _("Order {0} has nothing left to deliver.").format(order.name)
	return None


@frappe.whitelist()
def assign_technician(sales_order_id, technician_id, technician_category, scheduled_date=None, slot=None):
	"""Give a Sales or Service order in `Order` its first technician.

	What the desk's Assign Technician does (`assign_technician` and
	`assign_technician_service` in the ERPNext fork), written here because the
	fork's version cannot be called from the app: it runs `frappe.db.begin()`,
	which commits whatever the request has done, then commits itself, and
	`msgprint`s on the share. Here the request commits once, at the end, so the
	order and its visit are saved together or not at all.

	A date or a slot schedules the visit, as a pickup is scheduled
	(`nhk.api.pickup`). Left out, the visit is unscheduled, as the desk leaves it.
	"""
	require_office()

	order = frappe.get_doc("Sales Order", sales_order_id) if sales_order_id and frappe.db.exists(
		"Sales Order", sales_order_id) else None
	if not order or order.docstatus != 1:
		frappe.throw(_("Sales Order {0} is not a submitted order.").format(sales_order_id))
	order.has_undelivered_item = any(
		not cint(i.delivered_by_supplier) and flt(i.qty) > flt(i.delivered_qty) for i in order.items)
	reason = _why_not_assign_technician(order)
	if reason:
		frappe.throw(reason)

	visit_type = ASSIGNMENT_VISIT_TYPES[order.order_type]
	open_visit = frappe.db.get_value(
		"Technician Visit Entry",
		{"sales_order_id": order.name, "type": visit_type, "status": ("in", OPEN_STATUSES)}, "name")
	if open_visit:
		# The order says `Order` but a visit is already out: someone made it by
		# hand. A second one would pay two technicians for one job.
		frappe.throw(_("Order {0} already has an open visit, {1}. Reassign that one instead.").format(
			order.name, open_visit))

	technician = _technician(technician_id)
	if not technician_category or not frappe.db.exists("Technician Category", technician_category):
		frappe.throw(_("Pick the technician category. It sets what the technician is paid."))

	when = None
	if scheduled_date or slot:
		from nhk.api.pickup import _when

		when, slot = _when(scheduled_date or _today(), slot)

	order.custom_technician_id_before_delivered = technician.name
	order.save(ignore_permissions=True)
	# Set directly, as the fork does: the status is NHK's own, and a save would
	# have ERPNext's `set_status` put it back.
	frappe.db.set_value("Sales Order", order.name, "status", ASSIGNED_ORDER_STATUS)
	for item in order.items:
		frappe.db.set_value("Sales Order Item", item.name, {
			"child_status": ASSIGNED_ORDER_STATUS,
			"technician_id_before_deliverd": technician.name,
		})

	# Office users hold `create` and `share` on visits, so neither skips the
	# permission check. `stamp_assigned_by` records the caller as `assigned_by`,
	# so accept and reject reach them (`nhk.api.notify.tell_office`); the insert
	# itself pushes the technician (`nhk.api.notify.on_visit_update`).
	visit = frappe.get_doc({
		"doctype": "Technician Visit Entry",
		"sales_order_id": order.name,
		"technician_id": technician.name,
		"type": visit_type,
		"status": "Assigned",
		"patient_id": order.customer,
		"technician_category": technician_category,
		"scheduled_datetime": when,
		"slot": slot if when else None,
		"technician_response": RESPONSE_PENDING,
	}).insert()
	frappe.share.add("Technician Visit Entry", visit.name, technician.user_mail_id, read=1, write=1)

	line = _("Technician {0} assigned by {1} from the app.").format(
		technician.name1 or technician.name, frappe.utils.get_fullname(frappe.session.user))
	visit.add_comment("Comment", line)
	order.add_comment("Comment", line)

	return {
		"name": visit.name,
		"sales_order_id": order.name,
		"order_status": ASSIGNED_ORDER_STATUS,
		"type": visit_type,
		"technician_id": technician.name,
		"technician_name": (technician.name1 or "").strip(),
		"scheduled_datetime": visit.scheduled_datetime,
		"slot": visit.slot or None,
		"technician_response": RESPONSE_PENDING,
	}


def _technician(technician_id):
	"""The Technician Details row work can be given to: one with an app login."""
	if not technician_id or not frappe.db.exists("Technician Details", technician_id):
		frappe.throw(_("Pick a technician."))
	row = frappe.db.get_value("Technician Details", technician_id,
							  ["name", "name1", "user_mail_id"], as_dict=True)
	if not row.user_mail_id:
		frappe.throw(_("{0} has no app login, so they would never see the job.").format(row.name1 or row.name))
	return row


# ---------------------------------------------------------------------------
# Pickups: every rental still out with a patient
# ---------------------------------------------------------------------------

#: The rental statuses a pickup can be assigned from, as `assign_pickup_for_order` allows.
PICKUP_ORDER_STATUSES = ("Active", "Ready for Pickup")

#: The board's tabs, most urgent first.
#:
#: * **To Assign** -- the order is `Ready for Pickup` and nobody has the pickup,
#:   or the technician who had it rejected it.
#: * **With Patient** -- `Active` with no pickup arranged. Soonest `end_date` first.
#: * **Assigned** -- a technician has the pickup and has not done it yet.
PICKUP_TABS = ("To Assign", "With Patient", "Assigned")


@frappe.whitelist()
def pickups(group=None, search=None, cursor=None, limit=PAGE_SIZE):
	"""One page of a Pickups tab, with counts for every tab.

	`office.sleep_study_pickups` widened from sleep studies to every submitted
	Rental order in `Active` or `Ready for Pickup` (368 on nhk.local,
	2026-10-10), so it reads them all, groups them, and pages in memory. Sleep
	studies are marked with `is_sleep_study`, from their latest delivery.

	`search` is the Sales Orders list's: order, customer name, or mobile.
	`cursor` is an offset into the tab, `next_cursor` the next one.
	"""
	require_office()

	from nhk.api.office import _open_pickups
	from nhk.api.pickup import SLEEP_STUDY_PREFIX

	group = group or PICKUP_TABS[0]
	if group not in PICKUP_TABS:
		frappe.throw(_("Pickups has no tab called {0}.").format(group))
	limit = min(max(cint(limit) or PAGE_SIZE, 1), MAX_PAGE_SIZE)
	offset = max(cint(cursor), 0)

	where, values = _where(order_type="Rental", search=(search or "").strip())
	orders = frappe.db.sql(
		f"""select so.name as sales_order_id, so.status as order_status, so.order_type,
			so.customer, so.customer_name, so.customer_mobile_no, so.end_date, so.pickup_date,
			d.name as delivery_visit, d.technician_category,
			d.technician_id as delivery_technician_id, d.technician_name as delivery_technician_name,
			d.area, coalesce(d.completed_at, d.technician_update_datetime) as delivered_at
		from `tabSales Order` so
		left join `tabTechnician Visit Entry` d on d.name = (
			select d2.name from `tabTechnician Visit Entry` d2
			where d2.sales_order_id = so.name and d2.type = 'Delivery'
			order by d2.creation desc limit 1)
		where {where} and so.status in %(pickup_statuses)s""",
		{**values, "pickup_statuses": PICKUP_ORDER_STATUSES}, as_dict=True,
	)
	open_pickups = _open_pickups([o.sales_order_id for o in orders])

	tabs = {tab: [] for tab in PICKUP_TABS}
	for row in orders:
		pickup = open_pickups.get(row.sales_order_id)
		if row.order_status == "Active" and not pickup:
			tab = "With Patient"
		elif not pickup or pickup.technician_response == "Rejected":
			tab = "To Assign"
		else:
			tab = "Assigned"
		row["group"] = tab
		row["pickup"] = pickup
		row["is_sleep_study"] = (row.technician_category or "").startswith(SLEEP_STUDY_PREFIX)
		row["customer_name"] = (row.customer_name or "").strip()
		row["delivery_technician_name"] = (row.delivery_technician_name or "").strip()
		row["actions"] = _order_actions(
			frappe._dict(name=row.sales_order_id, order_type=row.order_type, status=row.order_status),
			has_open_pickup=bool(pickup))
		tabs[tab].append(row)

	far = "9999-12-31"
	tabs["To Assign"].sort(key=lambda r: (str(r.pickup_date or far), r.sales_order_id))
	tabs["With Patient"].sort(key=lambda r: (str(r.end_date or far), r.sales_order_id))
	tabs["Assigned"].sort(key=lambda r: (str(r.pickup.scheduled_datetime or far), r.sales_order_id))

	rows = tabs[group][offset:offset + limit]
	more = offset + limit < len(tabs[group])
	for row in rows:
		if row.pickup:
			row.pickup.setdefault("status", "Assigned")  # `_open_pickups` reads only open ones
	_set_visit_actions([r.pickup for r in rows if r.pickup])
	return {
		"group": group,
		"rows": rows,
		"next_cursor": str(offset + limit) if more else None,
		"counts": {tab: len(tabs[tab]) for tab in PICKUP_TABS},
	}


@frappe.whitelist()
def assign_pickup(sales_order_id, technician_id, pickup_reason=None, pickup_remark=None, pickup_date=None, slot=None,
				  technician_category=None):
	"""Give the pickup of an Active or Ready for Pickup rental to a technician.

	`nhk.api.pickup.assign_pickup_for_order`, the desk's own, with the reason the
	office picked. It readies the order for pickup if it is still `Active`,
	creates the Pickup visit owned by the office, shares it with the technician
	and writes both timelines. An order whose pickup is already out is refused:
	the visit is reassigned instead.

	A sleep study needs no reason, as the desk block's Assign Pickup asks none:
	the study ending is the reason, and the order gets the sleep study's
	(ADR-0006). Every other rental needs one.
	"""
	require_office()

	from nhk.api.pickup import assign_pickup_for_order, validated_pickup_reason

	if pickup_reason or not _is_sleep_study_order(sales_order_id):
		reason = validated_pickup_reason(pickup_reason)
		remark = (pickup_remark or "").strip() or _("Pickup assigned by {0} from the app.").format(
			frappe.utils.get_fullname(frappe.session.user))
	else:
		reason, remark = None, (pickup_remark or "").strip() or None

	result = assign_pickup_for_order(sales_order_id, technician_id, pickup_date=pickup_date, slot=slot,
									 technician_category=technician_category or None,
									 pickup_reason=reason, pickup_remark=remark)
	result["slot"] = result.get("slot") or None
	result["sales_order_id"] = sales_order_id
	result["order_status"] = frappe.db.get_value("Sales Order", sales_order_id, "status")
	return result


def _pickup_can_be_assigned(order, has_open_pickup):
	return (order.order_type == "Rental" and order.status in PICKUP_ORDER_STATUSES
			and not has_open_pickup)


def _is_sleep_study_order(sales_order):
	from nhk.api.pickup import SLEEP_STUDY_PREFIX

	return (_delivery_category(sales_order) or "").startswith(SLEEP_STUDY_PREFIX)


def _delivery_category(sales_order):
	return frappe.db.get_value(
		"Technician Visit Entry", {"sales_order_id": sales_order, "type": "Delivery"},
		"technician_category", order_by="creation desc")


# ---------------------------------------------------------------------------
# Visits: the day, what needs chasing, and moving one
# ---------------------------------------------------------------------------

#: The visit actions the phone has. The desk has more (`visits._actions`:
#: complete, the rental buttons, extra payment); the phone offers none of them.
#:
#: * `reassign` -- to another technician, while open and nobody has arrived.
#:   A visit someone is standing at is moved from the desk, where
#:   `reassign_visit(force=1)` closes their check-in deliberately.
#: * `reschedule` -- to another day and slot, while open and not rejected: a
#:   rejected visit needs a technician first. The desk's Technician Visits block
#:   offers the same buttons (`technician_visits_block.js`), so the office sees
#:   one set of rules on both.
VISIT_ACTIONS = ("reassign", "reschedule")

#: A Pending visit older than this, since it was last given out, needs chasing.
#: A guess (2026-10-10): see the spec's open questions.
UNANSWERED_AFTER_HOURS = 2

#: What `open_visits` can list. Each is one card on the Office home.
OPEN_VISIT_KINDS = ("rejected", "unanswered")

#: When a visit was last given out: created, or reassigned since. There is no
#: field for it; `assignment._record_handover` writes "Reassigned from ..." to the
#: timeline on every move, so the latest such comment is the reassignment time.
_ASSIGNED_AT = """greatest(v.creation, coalesce((select max(c.creation) from `tabComment` c
	where c.reference_doctype = 'Technician Visit Entry' and c.reference_name = v.name
	and c.comment_type = 'Comment' and c.content like 'Reassigned from%%'), v.creation))"""


@frappe.whitelist()
def today(date=None):
	"""One day's visits by where they stand: `nhk.api.office.technician_visits`.

	The NHK Technician workspace's block, with the phone's `actions` on each row.
	"""
	require_office()

	from nhk.api.office import technician_visits

	day = technician_visits(date)
	_set_visit_actions(day["rows"])
	return day


@frappe.whitelist()
def sleep_study_pickups():
	"""Every sleep study still out with a patient: `nhk.api.office.sleep_study_pickups`.

	The desk block's second group -- With Patient, To Assign, Assigned -- row
	for row, with the phone's `actions`: `assign_pickup` while no pickup is out,
	and the pickup visit's own `reassign` / `reschedule` once one is.
	"""
	require_office()

	from nhk.api.office import sleep_study_pickups as board

	result = board()
	for row in result["rows"]:
		row["actions"] = ["assign_pickup"] if not row.get("pickup") and row.get("order_status") in PICKUP_ORDER_STATUSES else []
		if row.get("pickup"):
			row["pickup"].setdefault("status", "Assigned")  # `_open_pickups` reads only open ones
	_set_visit_actions([r["pickup"] for r in result["rows"] if r.get("pickup")])
	return result


@frappe.whitelist()
def open_visits(kind):
	"""Open visits that need the office, on orders still running, oldest first.

	* `rejected` -- the technician handed it back. Reassign it.
	* `unanswered` -- nobody has accepted it `UNANSWERED_AFTER_HOURS` after it was
	  given out. Chase or reassign.

	Not limited to a day, unlike `today`: a rejection from last week is still
	work.
	"""
	require_office()

	from nhk.api.office import FINISHED_ORDER_STATUSES

	if kind not in OPEN_VISIT_KINDS:
		frappe.throw(_("There is no list of {0} visits.").format(kind))
	if kind == "rejected":
		answered = "v.technician_response = 'Rejected'"
	else:
		answered = f"""ifnull(nullif(v.technician_response, ''), 'Pending') = 'Pending'
			and {_ASSIGNED_AT} < %(cutoff)s"""

	rows = frappe.db.sql(
		f"""select v.name, v.type, v.status, v.technician_id, v.technician_name, v.technician_mobile_no,
			v.sales_order_id, v.patient_name, v.area, v.scheduled_datetime, v.slot,
			ifnull(nullif(v.technician_response, ''), 'Pending') as technician_response,
			v.technician_response_at, v.rejection_reason, {_ASSIGNED_AT} as assigned_at
		from `tabTechnician Visit Entry` v
		left join `tabSales Order` so on so.name = v.sales_order_id
		where v.status in %(open)s and {answered}
			and ifnull(so.status, '') not in %(finished)s
		order by assigned_at asc, v.name asc""",
		{"open": OPEN_STATUSES, "finished": FINISHED_ORDER_STATUSES,
		 "cutoff": frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-UNANSWERED_AFTER_HOURS)},
		as_dict=True,
	)
	for row in rows:
		row["technician_name"] = (row.technician_name or "").strip()
	_set_visit_actions(rows)
	return {"kind": kind, "rows": rows}


@frappe.whitelist()
def attention():
	"""The Office home's cards: how much of each kind of work is waiting.

	Each count is the length of the list its card opens, read through the same
	endpoint, so a card never promises rows its list does not have.
	"""
	require_office()

	orders = sales_orders(status=UNASSIGNED_ORDER_STATUS)["counts"]["order_type"]
	return {
		"pickups_to_assign": pickups(group="To Assign", limit=1)["counts"]["To Assign"],
		"rejected": len(open_visits("rejected")["rows"]),
		"unanswered": len(open_visits("unanswered")["rows"]),
		"orders_to_assign": sum(orders.get(t, 0) for t in ASSIGNMENT_VISIT_TYPES),
		"unanswered_after_hours": UNANSWERED_AFTER_HOURS,
	}


@frappe.whitelist()
def technicians(date=None):
	"""Who work can be given to, and how busy each is on `date` (today by default).

	Every technician with an enabled app login. On duty first, then the fewest
	open visits that day, so the likeliest choice is at the top. "Open that day"
	is the dashboard's rule (`nhk.api.staff._OPEN_FOR_MONTH`) for one day.
	"""
	require_office()

	from nhk.api.staff import _OPEN_FOR_MONTH

	day = getdate(date or _today())
	rows = frappe.db.sql(
		"""select td.name as technician_id, trim(td.name1) as technician_name, td.mobile_number
		from `tabTechnician Details` td
		join `tabUser` u on u.name = td.user_mail_id and u.enabled = 1
		order by td.name1""",
		as_dict=True,
	)
	on_duty = set(frappe.get_all("Technician Check In", filters={
		"kind": "Duty", "closed_at": ("is", "not set")}, pluck="technician_id"))
	busy = dict(frappe.db.sql(
		f"""select technician_id, count(*) from `tabTechnician Visit Entry`
		where {_OPEN_FOR_MONTH} group by technician_id""",
		{"start": day, "end": add_days(day, 1)},
	))
	for row in rows:
		row["on_duty"] = row.technician_id in on_duty
		row["open_visits"] = busy.get(row.technician_id, 0)
	rows.sort(key=lambda r: (not r.on_duty, r.open_visits, (r.technician_name or "").lower()))
	return {"date": str(day), "rows": rows}


@frappe.whitelist()
def reassign_visit(visit_id, technician_id):
	"""Move an open visit to another technician: `nhk.api.assignment.reassign_visit`.

	Without `force`. If the technician holding it has arrived, the phone says
	so and stops; the desk's Reassign closes their check-in on purpose. The
	new technician must have an app login, or they would never see the job.
	"""
	require_office()

	from nhk.api.assignment import reassign_visit as reassign

	visit = frappe.db.get_value("Technician Visit Entry", visit_id,
								["name", "status", "technician_id", "technician_name"], as_dict=True)
	if not visit:
		frappe.throw(_("Visit {0} does not exist.").format(visit_id), frappe.DoesNotExistError)
	target = _technician(technician_id)
	if visit.technician_id != target.name and visit.name in _arrived([visit.name]):
		frappe.throw(_("{0} has already arrived at visit {1}. Move it from the desk.").format(
			(visit.technician_name or visit.technician_id).strip(), visit.name))

	result = reassign(visit.name, target.name)
	result["technician_name"] = (target.name1 or "").strip()
	result["technician_response"] = frappe.db.get_value("Technician Visit Entry", visit.name, "technician_response")
	return result


@frappe.whitelist()
def reschedule(visit_id, scheduled_date, slot=None):
	"""Move an open visit to another day and slot: `nhk.api.visits.reschedule`.

	A day and a slot, as every other sheet in the app takes them, placed at the
	slot's start as pickups are (`nhk.api.pickup.SLOT_STARTS`). Not in the past.
	"""
	require_office()

	from nhk.api.pickup import _when
	from nhk.api.visits import reschedule as move

	if not scheduled_date:
		frappe.throw(_("Pick the new day."))
	when, slot = _when(scheduled_date, slot)
	result = move(visit_id, when, slot)
	result["slot"] = result.get("slot") or None
	return result


def _set_visit_actions(rows):
	"""Put the phone's `actions` on each visit row (needs name, status, technician_id)."""
	arrived = _arrived([r["name"] for r in rows if r.get("status") in OPEN_STATUSES])
	for row in rows:
		actions = []
		if row.get("status") in OPEN_STATUSES:
			if row["name"] not in arrived:
				actions.append("reassign")
			if (row.get("technician_response") or "Pending") != "Rejected":
				actions.append("reschedule")
		row["actions"] = actions


def _arrived(visit_names):
	"""The visits among these that someone has an open Arrival at."""
	if not visit_names:
		return set()
	return set(frappe.get_all("Technician Check In", filters={
		"kind": "Visit", "closed_at": ("is", "not set"), "visit_entry": ("in", visit_names)},
		pluck="visit_entry"))
