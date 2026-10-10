"""The Office tab's API (`nhk.api.ops`).

Run:  cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_ops.py
"""

import sys

import frappe

sys.path.insert(0, __file__.rsplit("/", 1)[0])


# Logins are compared in lower case. MariaDB matches `user_mail_id` to the login
# without case, so `current_technician` finds a record typed `Name@...` for the
# login `name@...`; a Python set would not.

def _holders(role):
	return {u.lower() for u in frappe.get_all(
		"Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent")}


def _people():
	"""Enabled logins that are real people, not Administrator or Guest."""
	return {u.lower() for u in frappe.get_all("User", filters={"enabled": 1}, pluck="name")} - {
		"administrator", "guest"}


def _technician_logins():
	return {u.strip().lower() for u in frappe.get_all(
		"Technician Details", filters={"user_mail_id": ("is", "set")}, pluck="user_mail_id")}


def _one(users, what):
	"""A real login of the kind the test needs.

	Real people, as `test_visits._office_user` does: what matters is what the
	people pressing the buttons can do, and Administrator passes everything.
	"""
	if not users:
		raise AssertionError("no enabled user on this site who is %s" % what)
	return sorted(users)[0]


def office_only():
	return _one((_holders("NHK Admin") & _people()) - _technician_logins(), "NHK Admin and not a technician")


def technician_only():
	return _one((_technician_logins() & _people()) - _holders("NHK Admin"), "a technician without NHK Admin")


def technician_and_office():
	return _one(_holders("NHK Admin") & _people() & _technician_logins(), "both NHK Admin and a technician")


def _as(user, fn, *args, **kwargs):
	frappe.set_user(user)
	try:
		return fn(*args, **kwargs)
	finally:
		frappe.set_user("Administrator")


def _refused(user, fn, *args, **kwargs):
	"""True when `fn` refuses `user` with the Office gate's own exception."""
	from nhk.api.ops import NotOffice

	try:
		_as(user, fn, *args, **kwargs)
	except NotOffice:
		return True
	return False


# --------------------------------------------------------------------------
# whoami
# --------------------------------------------------------------------------

def test_whoami_for_an_office_user_who_is_not_a_technician(cleanup):
	from nhk.api import ops

	me = _as(office_only(), ops.whoami)
	assert me == {"is_technician": False, "is_office": True, "technician_id": None}, me


def test_whoami_for_a_technician_without_the_office_role(cleanup):
	from nhk.api import ops

	user = technician_only()
	me = _as(user, ops.whoami)
	assert me["is_technician"] is True and me["is_office"] is False, me
	assert me["technician_id"] == frappe.db.get_value("Technician Details", {"user_mail_id": user}, "name"), me


def test_whoami_for_someone_who_is_both(cleanup):
	from nhk.api import ops

	me = _as(technician_and_office(), ops.whoami)
	assert me["is_technician"] is True and me["is_office"] is True, me


def test_whoami_leaves_no_error_message_for_the_app_to_show(cleanup):
	"""`current_technician` throws for a non-technician, and `throw` queues its
	message first. The app shows `_server_messages` as an error snackbar."""
	from nhk.api import ops

	frappe.clear_messages()
	_as(office_only(), ops.whoami)
	assert not frappe.local.message_log, frappe.local.message_log


# --------------------------------------------------------------------------
# require_office
# --------------------------------------------------------------------------

def test_the_office_gate_lets_nhk_admin_through(cleanup):
	from nhk.api.ops import require_office

	_as(office_only(), require_office)
	_as(technician_and_office(), require_office)


def test_the_office_gate_refuses_a_technician(cleanup):
	from nhk.api.ops import require_office

	assert _refused(technician_only(), require_office)


def test_the_office_gate_refuses_a_system_manager_without_nhk_admin(cleanup):
	"""`share` on Technician Visit Entry is the desk's office gate, and System
	Manager holds it. The phone's gate is the role, so this is refused."""
	from nhk.api.ops import require_office

	user = _one((_holders("System Manager") & _people()) - _holders("NHK Admin"),
				"System Manager without NHK Admin")
	assert frappe.has_permission("Technician Visit Entry", "share", user=user), \
		"expected System Manager to hold share; the test no longer shows what it means to"
	assert _refused(user, require_office)


def test_the_office_gate_refuses_administrator(cleanup):
	from nhk.api.ops import require_office

	assert _refused("Administrator", require_office)



# --------------------------------------------------------------------------
# sales_orders: the list
# --------------------------------------------------------------------------

def _list(**kwargs):
	from nhk.api import ops

	return _as(office_only(), ops.sales_orders, **kwargs)


def _every_page(**kwargs):
	names, cursor, pages = [], None, 0
	while True:
		page = _list(cursor=cursor, **kwargs)
		names += [r["name"] for r in page["rows"]]
		pages += 1
		cursor = page["next_cursor"]
		if not cursor:
			return names, pages


def _busy(min_orders, max_orders):
	"""An (Order Type, status) with between `min_orders` and `max_orders` submitted orders."""
	row = frappe.db.sql(
		"""select order_type, status from `tabSales Order` where docstatus = 1
		group by order_type, status having count(*) between %s and %s
		order by count(*) desc limit 1""", (min_orders, max_orders))
	if not row:
		raise AssertionError("no order type and status with %s-%s orders" % (min_orders, max_orders))
	return row[0]


def test_paging_returns_every_order_once_newest_first(cleanup):
	order_type, status = _busy(25, 200)
	names, pages = _every_page(order_type=order_type, status=status, since="all", limit=10)

	expected = frappe.get_all(
		"Sales Order", filters={"docstatus": 1, "order_type": order_type, "status": status},
		order_by="transaction_date desc, name desc", pluck="name")
	assert names == expected, (len(names), len(expected))
	assert pages > 1


def test_status_order_starts_at_the_window_unless_searched_or_all(cleanup):
	from nhk.api.ops import DEFAULT_WINDOW_DAYS

	start = frappe.utils.getdate(frappe.utils.add_days(frappe.utils.today(), -DEFAULT_WINDOW_DAYS))
	windowed = _list(status="Order")
	assert windowed["since"] == str(start), windowed["since"]
	assert all(r["transaction_date"] >= start for r in windowed["rows"])

	everything = _list(status="Order", since="all")
	assert everything["since"] is None
	assert sum(everything["counts"]["order_type"].values()) > sum(windowed["counts"]["order_type"].values())

	old = frappe.db.get_value("Sales Order", {"docstatus": 1, "status": "Order",
											  "transaction_date": ("<", start)}, "name")
	searched = _list(status="Order", search=old)
	assert searched["since"] is None and old in [r["name"] for r in searched["rows"]]


def test_other_lists_start_at_the_beginning(cleanup):
	assert _list()["since"] is None
	assert _list(status="Active")["since"] is None


def test_draft_and_cancelled_orders_are_never_listed(cleanup):
	for docstatus in (0, 2):
		name = frappe.db.get_value("Sales Order", {"docstatus": docstatus}, "name")
		if name:
			assert name not in [r["name"] for r in _list(search=name, since="all")["rows"]], name


def test_search_finds_an_order_by_its_customers_mobile_however_it_is_typed(cleanup):
	order, mobile = frappe.db.sql(
		"""select name, customer_mobile_no from `tabSales Order`
		where docstatus = 1 and customer_mobile_no regexp '^[0-9]{10}$' order by transaction_date desc limit 1""")[0]
	typed = "+91 %s %s" % (mobile[:5], mobile[5:])
	assert order in _every_page(search=typed)[0], typed


def test_search_finds_an_order_by_customer_name_and_by_name(cleanup):
	order, customer = frappe.db.sql(
		"""select name, customer_name from `tabSales Order` where docstatus = 1
		and char_length(trim(customer_name)) > 6 order by transaction_date desc limit 1""")[0]
	assert order in _every_page(search=customer.strip()[:6])[0]
	assert [r["name"] for r in _list(search=order)["rows"]][:1] == [order]


def test_a_percent_sign_in_the_search_is_text_not_a_wildcard(cleanup):
	rows = _list(search="%", since="all")["rows"]
	assert all("%" in r["name"] or "%" in r["customer_name"] for r in rows), [r["name"] for r in rows][:3]


def test_counts_say_what_each_filter_would_show(cleanup):
	order_type, status = _busy(5, 100)
	page = _list(order_type=order_type, since="all")
	assert page["counts"]["status"][status] == len(_every_page(order_type=order_type, status=status, since="all")[0])
	# The Order Type counts ignore the Order Type filter itself.
	assert set(page["counts"]["order_type"]) >= {"Sales", "Service", "Rental"}, page["counts"]["order_type"]


def test_a_row_says_who_has_the_open_visit_and_whether_they_answered(cleanup):
	from test_staff_api import _visit

	order = frappe.db.get_value("Sales Order", {"docstatus": 1, "status": "Active"}, "name")
	visit = _visit(cleanup, response="Pending", sales_order=order)

	row = next(r for r in _list(search=order)["rows"] if r["name"] == order)
	mine = next(v for v in row["open_visits"] if v["name"] == visit)
	assert mine["technician_response"] == "Pending" and mine["technician_id"], mine
	assert isinstance(row["items"], list)
	# Read from the ledger, order by order: the detail carries it, not the list.
	assert "payment_status" not in row


def test_an_expired_cursor_says_so(cleanup):
	try:
		_list(cursor="not a cursor")
	except frappe.ValidationError as exc:
		assert "refresh" in str(exc).lower(), exc
	else:
		raise AssertionError("a broken cursor was accepted")


# --------------------------------------------------------------------------
# sales_order: one order
# --------------------------------------------------------------------------

def test_one_order_has_its_customer_items_what_is_owed_and_its_visits(cleanup):
	from nhk.api import ops, visits

	order = frappe.db.sql(
		"""select sales_order_id from `tabTechnician Visit Entry` v
		join `tabSales Order` so on so.name = v.sales_order_id and so.docstatus = 1
		order by v.creation desc limit 1""")[0][0]
	result = _as(office_only(), ops.sales_order, order)

	o = result["order"]
	assert o["name"] == o["sales_order_id"] == order
	assert o["customer"] and o["items"] and o["order_type"], o
	assert o["payment_status"] in ("Pending", "Paid") and "map_url" in o and "address" in o
	assert not set(o) & {"payment_entries", "journal_entries", "docstatus"}, set(o)
	assert [v["name"] for v in result["visits"]] == [v["name"] for v in visits.for_sales_order(order)]
	assert not set(o) & {"per_billed", "per_delivered", "skip_delivery_note", "has_undelivered_item"}, set(o)


def test_a_draft_order_cannot_be_opened(cleanup):
	from nhk.api import ops

	draft = frappe.db.get_value("Sales Order", {"docstatus": 0}, "name")
	if not draft:
		return
	try:
		_as(office_only(), ops.sales_order, draft)
	except frappe.DoesNotExistError:
		return
	raise AssertionError("a draft order was served")


def test_only_the_office_reads_orders(cleanup):
	from nhk.api import ops

	order = frappe.db.get_value("Sales Order", {"docstatus": 1}, "name")
	assert _refused(technician_only(), ops.sales_orders)
	assert _refused(technician_only(), ops.sales_order, order)


# --------------------------------------------------------------------------
# assign_technician: the first technician on a Sales or Service order
# --------------------------------------------------------------------------
#
# These write to real orders. `assign_technician` never commits -- the request
# does -- so each test rolls back, and `_unchanged` then proves nothing was
# committed part way through.

ASSIGNEE = "NHK-TEC-002"  # test_staff_api.PILOT_TECH


def _unassigned(order_type):
	"""A recent submitted order the desk would offer Assign Technician on."""
	from nhk.api import ops

	for name in frappe.get_all(
		"Sales Order", filters={"docstatus": 1, "order_type": order_type, "status": "Order"},
		order_by="transaction_date desc", pluck="name", limit=50,
	):
		order = frappe.get_doc("Sales Order", name)
		order.has_undelivered_item = ops._has_undelivered_item(name)
		if not ops._why_not_assign_technician(order) and not frappe.db.exists(
				"Technician Visit Entry", {"sales_order_id": name, "status": "Assigned"}):
			return name
	raise AssertionError("no %s order to assign on this site" % order_type)


def _assign(order, **kwargs):
	from nhk.api import ops

	kwargs.setdefault("technician_id", ASSIGNEE)
	kwargs.setdefault("technician_category", "Visit")
	return _as(office_only(), ops.assign_technician, order, **kwargs)


def _unchanged(order):
	"""After the rollback: the order is as it was and has no new visit."""
	frappe.db.rollback()
	assert frappe.db.get_value("Sales Order", order, "status") == "Order", "an assignment was committed"
	assert not frappe.db.exists("Technician Visit Entry", {"sales_order_id": order, "status": "Assigned"})


def _refusal(order, **kwargs):
	try:
		_assign(order, **kwargs)
	except frappe.ValidationError as exc:
		return str(exc)
	finally:
		frappe.db.rollback()
	raise AssertionError("assign_technician accepted %s %s" % (order, kwargs))


def test_a_sales_order_gets_an_installation_visit_and_moves_to_technician_assigned(cleanup):
	order = _unassigned("Sales")
	office = office_only()
	technician_user = frappe.db.get_value("Technician Details", ASSIGNEE, "user_mail_id")
	try:
		result = _assign(order, technician_category="Order")

		assert frappe.db.get_value("Sales Order", order, ["status", "custom_technician_id_before_delivered"]) == (
			"Technician Assigned", ASSIGNEE)
		for item in frappe.get_all("Sales Order Item", filters={"parent": order},
								   fields=["child_status", "technician_id_before_deliverd"]):
			assert (item.child_status, item.technician_id_before_deliverd) == ("Technician Assigned", ASSIGNEE), item

		visit = frappe.get_doc("Technician Visit Entry", result["name"])
		assert (visit.type, visit.status, visit.technician_id, visit.technician_category, visit.technician_response) == (
			"Technician Assignment For Sales", "Assigned", ASSIGNEE, "Order", "Pending"), visit.as_dict()
		assert visit.patient_id == frappe.db.get_value("Sales Order", order, "customer")
		assert visit.owner == visit.assigned_by == office, (visit.owner, visit.assigned_by)
		assert visit.charges, "the slab did not price the visit"
		assert frappe.db.get_value("DocShare", {"share_doctype": "Technician Visit Entry", "share_name": visit.name,
												"user": technician_user}, "write") == 1
		for doctype, name in (("Technician Visit Entry", visit.name), ("Sales Order", order)):
			assert frappe.db.exists("Comment", {"reference_doctype": doctype, "reference_name": name,
												"content": ("like", "%assigned by%from the app%")}), doctype
		assert result["order_status"] == "Technician Assigned" and result["technician_response"] == "Pending"
	finally:
		_unchanged(order)


def test_a_service_order_gets_a_service_visit(cleanup):
	order = _unassigned("Service")
	try:
		result = _assign(order)
		assert result["type"] == "Technician Assignment For Service"
		assert frappe.db.get_value("Sales Order", order, "status") == "Technician Assigned"
	finally:
		_unchanged(order)


def test_a_date_and_slot_schedule_the_visit_and_none_leaves_it_unscheduled(cleanup):
	order = _unassigned("Sales")
	tomorrow = frappe.utils.add_days(frappe.utils.today(), 1)
	try:
		result = _assign(order, scheduled_date=tomorrow, slot="Evening")
		assert str(result["scheduled_datetime"]) == "%s 17:00:00" % tomorrow and result["slot"] == "Evening", result
	finally:
		_unchanged(order)
	try:
		result = _assign(order)
		assert result["scheduled_datetime"] is None and result["slot"] is None, result
	finally:
		_unchanged(order)


def test_the_technician_is_pushed_once_the_assignment_commits(cleanup):
	order = _unassigned("Sales")
	frappe.flags.nhk_mute_notifications = False
	try:
		_assign(order)
		queued = [getattr(f, "func", f).__name__ for f in frappe.db.after_commit._functions]
		assert "_notify" in queued, queued
	finally:
		frappe.flags.nhk_mute_notifications = True
		_unchanged(order)  # the rollback drops the queued push with it


def test_assign_technician_is_refused_where_the_desk_does_not_offer_it(cleanup):
	rental = frappe.db.get_value("Sales Order", {"docstatus": 1, "order_type": "Rental", "status": "Active"}, "name")
	assert "Sales and Service" in _refusal(rental)

	assigned = frappe.db.get_value("Sales Order", {"docstatus": 1, "order_type": "Sales",
												   "status": "Technician Assigned"}, "name")
	assert "Reassign" in _refusal(assigned)


def test_assign_technician_needs_a_category_a_technician_with_a_login_and_no_past_date(cleanup):
	order = _unassigned("Sales")
	assert "category" in _refusal(order, technician_category="")
	assert "category" in _refusal(order, technician_category="No Such Category")

	no_login = frappe.db.get_value("Technician Details", {"user_mail_id": ("is", "not set")}, "name")
	if no_login:
		assert "app login" in _refusal(order, technician_id=no_login)
	assert "past" in _refusal(order, scheduled_date=frappe.utils.add_days(frappe.utils.today(), -1))
	_unchanged(order)


def test_an_order_with_an_open_visit_already_is_not_given_a_second(cleanup):
	from test_staff_api import _visit

	order = _unassigned("Sales")
	try:
		existing = _visit(cleanup, response="Pending", sales_order=order, type_="Technician Assignment For Sales")
		assert existing in _refusal(order)
	finally:
		frappe.db.rollback()


def test_only_the_office_assigns(cleanup):
	from nhk.api import ops

	order = _unassigned("Sales")
	assert _refused(technician_only(), ops.assign_technician, order, ASSIGNEE, "Visit")
	_unchanged(order)


def test_the_list_and_the_detail_offer_assign_technician_where_it_applies(cleanup):
	from nhk.api import ops

	order = _unassigned("Service")
	row = next(r for r in _list(search=order)["rows"] if r["name"] == order)
	assert row["actions"] == ["assign_technician"], row["actions"]
	assert not set(row) & {"per_billed", "has_undelivered_item"}, set(row)

	detail = _as(office_only(), ops.sales_order, order)
	choice = detail["assign"]["assign_technician"]
	assert detail["actions"] == ["assign_technician"]
	assert choice["visit_type"] == "Technician Assignment For Service"
	assert {"Order", "Visit"} <= set(choice["categories"]) and choice["slots"] == ["Morning", "Afternoon", "Evening"]

	finished = frappe.db.get_value("Sales Order", {"docstatus": 1, "order_type": "Rental",
												   "status": "Submitted to Office"}, "name")
	finished_detail = _as(office_only(), ops.sales_order, finished)
	assert finished_detail["actions"] == [] and finished_detail["assign"] == {}


def test_the_core_assign_functions_still_write_what_the_copy_writes(cleanup):
	"""`ops.assign_technician` copies the fork's `assign_technician` and
	`assign_technician_service` (`docs/core-modifications.md`). If an ERPNext merge
	changes what they write, the copy has to change too; this is the alarm."""
	import inspect

	from erpnext.selling.doctype.sales_order import sales_order as core

	for fn, visit_type in ((core.assign_technician, "Technician Assignment For Sales"),
						   (core.assign_technician_service, "Technician Assignment For Service")):
		source = inspect.getsource(fn)
		for written in ("custom_technician_id_before_delivered", "'Technician Assigned'", "child_status",
						"technician_id_before_deliverd", "create_technician_portal_entry", visit_type):
			assert written in source, "%s no longer writes %s" % (fn.__name__, written)


# --------------------------------------------------------------------------
# pickups and assign_pickup
# --------------------------------------------------------------------------
#
# Real rental orders, through `test_pickup`'s fixtures: `_order` snapshots the
# order and item fields a pickup writes and puts them back; `_forget_office_pickup`
# registers what `assign_pickup` created.

def _rental(cleanup, status="Active"):
	from test_pickup import _order

	return _order(cleanup, status=status)


def _delivered(cleanup, so, category="Order"):
	from test_pickup import _delivery

	return _delivery(cleanup, so, category=category)


def _forget_office_pickup(cleanup, so):
	"""Register the pickup visits `assign_pickup` made on `so`, and their comments.

	`_rental` picks an order with no open pickup, so every open one is the test's.
	"""
	frappe.set_user("Administrator")
	visits = frappe.get_all("Technician Visit Entry", filters={
		"sales_order_id": so, "type": "Pickup", "status": "Assigned"}, pluck="name")
	for doctype, names in (("Sales Order", [so]), ("Technician Visit Entry", visits)):
		if names:
			for name in frappe.get_all("Comment", filters={
					"reference_doctype": doctype, "reference_name": ("in", names),
					"content": ("like", "Pickup assigned%")}, pluck="name"):
				cleanup.add("Comment", name)
	for name in visits:
		cleanup.add("Technician Visit Entry", name)


def _assign_pickup(cleanup, so, **kwargs):
	from nhk.api import ops

	kwargs.setdefault("technician_id", ASSIGNEE)
	kwargs.setdefault("pickup_reason", "Patient recovered")
	try:
		return _as(office_only(), ops.assign_pickup, so, **kwargs)
	finally:
		_forget_office_pickup(cleanup, so)


def _pickup_refusal(cleanup, so, **kwargs):
	try:
		_assign_pickup(cleanup, so, **kwargs)
	except frappe.ValidationError as exc:
		return str(exc)
	raise AssertionError("assign_pickup accepted %s %s" % (so, kwargs))


def _board(group, **kwargs):
	from nhk.api import ops

	rows, cursor = [], None
	while True:
		page = _as(office_only(), ops.pickups, group=group, cursor=cursor, **kwargs)
		rows += page["rows"]
		cursor = page["next_cursor"]
		if not cursor:
			return rows, page["counts"]


def _tab_of(so):
	from nhk.api.ops import PICKUP_TABS

	for tab in PICKUP_TABS:
		row = next((r for r in _board(tab, search=so)[0] if r["sales_order_id"] == so), None)
		if row:
			return tab, row
	return None, None


def test_every_rental_out_with_a_patient_is_on_exactly_one_tab(cleanup):
	from nhk.api.ops import PICKUP_TABS

	seen = []
	for tab in PICKUP_TABS:
		rows, counts = _board(tab, limit=50)
		assert len(rows) == counts[tab], (tab, len(rows), counts[tab])
		assert all(r["group"] == tab for r in rows)
		seen += [r["sales_order_id"] for r in rows]
	expected = frappe.get_all("Sales Order", filters={
		"docstatus": 1, "order_type": "Rental", "status": ("in", ("Active", "Ready for Pickup"))}, pluck="name")
	assert sorted(seen) == sorted(expected), (len(seen), len(expected))


def test_with_patient_is_soonest_end_date_first(cleanup):
	rows, _counts = _board("With Patient", limit=100)
	ends = [str(r["end_date"]) for r in rows if r["end_date"]]
	assert ends == sorted(ends)


def test_an_active_rental_is_with_the_patient_and_offers_assign_pickup(cleanup):
	so = _rental(cleanup)
	_delivered(cleanup, so)
	tab, row = _tab_of(so)
	assert tab == "With Patient" and row["actions"] == ["assign_pickup"], (tab, row and row["actions"])
	assert row["is_sleep_study"] is False


def test_assigning_a_pickup_readies_the_order_with_the_reason_the_office_picked(cleanup):
	so = _rental(cleanup)
	_delivered(cleanup, so, category="Order")
	office = office_only()

	result = _assign_pickup(cleanup, so, pickup_reason="Patient recovered", pickup_remark="Called, collect after 4pm",
							slot="Afternoon")

	assert frappe.db.get_value("Sales Order", so, ["status", "pickup_reason", "pickup_remark",
												   "custom_technician_id_pickup"]) == (
		"Ready for Pickup", "Patient recovered", "Called, collect after 4pm", ASSIGNEE)
	for item in frappe.get_all("Sales Order Item", filters={"parent": so},
							   fields=["child_status", "pickup_reason", "pickup_remark"]):
		assert (item.child_status, item.pickup_reason, item.pickup_remark) == (
			"Ready for Pickup", "Patient recovered", "Called, collect after 4pm"), item

	visit = frappe.get_doc("Technician Visit Entry", result["name"])
	assert (visit.type, visit.technician_id, visit.technician_category, visit.slot, visit.technician_response) == (
		"Pickup", ASSIGNEE, "Order", "Afternoon", "Pending"), visit.as_dict()
	assert visit.owner == visit.assigned_by == office
	assert result["order_status"] == "Ready for Pickup"
	assert _tab_of(so)[0] == "Assigned"


def test_a_pickup_without_a_remark_says_who_assigned_it_from_the_app(cleanup):
	so = _rental(cleanup)
	_delivered(cleanup, so)
	_assign_pickup(cleanup, so)
	assert "from the app" in frappe.db.get_value("Sales Order", so, "pickup_remark")


def test_a_pickup_needs_a_reason_from_the_list(cleanup):
	so = _rental(cleanup)
	_delivered(cleanup, so)
	assert "picked up" in _pickup_refusal(cleanup, so, pickup_reason="")
	assert "picked up" in _pickup_refusal(cleanup, so, pickup_reason="Because")
	assert frappe.db.get_value("Sales Order", so, "status") == "Active"


def test_an_order_whose_pickup_is_out_is_not_given_another(cleanup):
	so = _rental(cleanup)
	_delivered(cleanup, so)
	first = _assign_pickup(cleanup, so)
	assert first["name"] in _pickup_refusal(cleanup, so, technician_id="NHK-TEC-003")
	assert "assign_pickup" not in _tab_of(so)[1]["actions"]


def test_a_rejected_pickup_goes_back_to_to_assign(cleanup):
	from nhk.api import staff
	from test_staff_api import OTHER_USER

	so = _rental(cleanup)
	_delivered(cleanup, so)
	result = _assign_pickup(cleanup, so, technician_id="NHK-TEC-003")
	frappe.set_user(OTHER_USER)
	try:
		staff.reject_job(result["name"], "Feeling unwell")
	finally:
		frappe.set_user("Administrator")

	tab, row = _tab_of(so)
	assert tab == "To Assign" and row["pickup"]["technician_response"] == "Rejected", (tab, row and row["pickup"])
	# The pickup visit still exists: it is reassigned (issue 05), not assigned again.
	assert "assign_pickup" not in row["actions"]


def test_an_order_with_no_delivery_needs_the_category_picked(cleanup):
	so = _rental(cleanup)
	if frappe.db.exists("Technician Visit Entry", {"sales_order_id": so, "type": "Delivery"}):
		return  # the borrowed order has a real delivery; nothing to show
	assert "category" in _pickup_refusal(cleanup, so)
	assert _assign_pickup(cleanup, so, technician_category="Visit")["name"]


def test_the_detail_offers_the_reasons_and_the_deliverys_category(cleanup):
	from nhk.api import ops

	so = _rental(cleanup)
	_delivered(cleanup, so, category="Sleep Study Level 1")
	detail = _as(office_only(), ops.sales_order, so)
	choice = detail["assign"]["assign_pickup"]
	assert "assign_pickup" in detail["actions"]
	assert "Patient recovered" in choice["reasons"] and "" not in choice["reasons"]
	assert choice["default_category"] == "Sleep Study Level 1"
	assert choice["reason_required"] is False, "the desk asks no reason for a sleep study"
	assert choice["default_date"] == str(frappe.utils.add_days(frappe.utils.today(), 1))


def test_only_the_office_sees_and_assigns_pickups(cleanup):
	from nhk.api import ops

	so = _rental(cleanup)
	assert _refused(technician_only(), ops.pickups)
	assert _refused(technician_only(), ops.assign_pickup, so, ASSIGNEE, "Patient recovered")
	assert frappe.db.get_value("Sales Order", so, "status") == "Active"


# --------------------------------------------------------------------------
# today, open_visits, attention, technicians, reassign_visit, reschedule
# --------------------------------------------------------------------------

OTHER = "NHK-TEC-003"  # test_staff_api.OTHER_TECH


def _open_visit(cleanup, response="Pending", type_="Delivery", hours_old=0):
	"""A visit on a real order that is still running, so the office's lists show it.

	Reassignment writes the technician onto the order; its fields are snapshot
	and handed back, as `test_assignment._visit` does.
	"""
	from test_office import _order
	from test_staff_api import _visit

	so = _order()
	for field in ("custom_technician_id_before_delivered", "custom_technician_id_pickup"):
		cleanup.restore("Sales Order", so, field)
	for item in frappe.get_all("Sales Order Item", filters={"parent": so}, pluck="name"):
		for field in ("technician_id_before_deliverd", "technician_id_after_delivered"):
			cleanup.restore("Sales Order Item", item, field)

	name = _visit(cleanup, response=response, type_=type_, sales_order=so)
	if response == "Rejected":
		frappe.db.set_value("Technician Visit Entry", name, "rejection_reason", "Bike Service")
	if hours_old:
		frappe.db.set_value("Technician Visit Entry", name, "creation",
							frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-hours_old),
							update_modified=False)
	return name


def _forget_comments(cleanup, visit):
	for name in frappe.get_all("Comment", filters={"reference_doctype": "Technician Visit Entry",
												   "reference_name": visit}, pluck="name"):
		cleanup.add("Comment", name)


def _office(fn, *args, **kwargs):
	return _as(office_only(), fn, *args, **kwargs)


def _row(rows, visit):
	return next((r for r in rows if r["name"] == visit), None)


def test_the_day_carries_the_phones_actions(cleanup):
	from nhk.api import ops

	open_visit = _open_visit(cleanup, response="Pending")
	done = _open_visit(cleanup, response="Accepted")
	frappe.db.set_value("Technician Visit Entry", done, {"status": "Delivered",
														 "completed_at": frappe.utils.now_datetime()})
	rows = _office(ops.today)["rows"]
	assert _row(rows, open_visit)["actions"] == ["reassign", "reschedule"]
	assert _row(rows, done)["actions"] == []


def test_reassigning_hands_the_visit_over_unanswered_and_pushes_the_new_technician(cleanup):
	from nhk.api import ops

	visit = _open_visit(cleanup, response="Rejected")
	frappe.flags.nhk_mute_notifications = False
	try:
		result = _office(ops.reassign_visit, visit, OTHER)
		queued = [getattr(f, "func", f).__name__ for f in frappe.db.after_commit._functions]
	finally:
		# Clear the push before anything commits: OTHER is a real person.
		frappe.db.after_commit.reset()
		frappe.flags.nhk_mute_notifications = True
		_forget_comments(cleanup, visit)

	assert result["moved"] is True and result["technician_response"] == "Pending", result
	assert frappe.db.get_value("Technician Visit Entry", visit, ["technician_id", "rejection_reason"]) == (OTHER, None)
	assert "_notify" in queued, queued
	assert _row(_office(ops.open_visits, "rejected")["rows"], visit) is None


def test_a_visit_someone_has_arrived_at_is_moved_from_the_desk(cleanup):
	from nhk.api import ops, staff
	from test_staff_api import PILOT_USER

	visit = _open_visit(cleanup, response="Accepted")
	frappe.set_user(PILOT_USER)
	cleanup.add("Technician Check In", staff.start_duty()["name"])
	cleanup.add("Technician Check In", staff.check_in(visit, latitude=12.9, longitude=77.5)["name"])
	frappe.set_user("Administrator")

	assert _row(_office(ops.today)["rows"], visit)["actions"] == ["reschedule"]
	try:
		_office(ops.reassign_visit, visit, OTHER)
	except frappe.ValidationError as exc:
		assert "desk" in str(exc), exc
	else:
		raise AssertionError("a visit someone is at was moved from the phone")
	finally:
		_forget_comments(cleanup, visit)
	assert frappe.db.get_value("Technician Visit Entry", visit, "technician_id") == ASSIGNEE


def test_a_visit_cannot_go_to_a_technician_with_no_login(cleanup):
	from nhk.api import ops

	no_login = frappe.db.get_value("Technician Details", {"user_mail_id": ("is", "not set")}, "name")
	if not no_login:
		return
	visit = _open_visit(cleanup)
	try:
		_office(ops.reassign_visit, visit, no_login)
	except frappe.ValidationError as exc:
		assert "app login" in str(exc), exc
	else:
		raise AssertionError("reassigned to a technician who cannot see it")


def test_rescheduling_moves_the_visit_to_the_slot_on_that_day(cleanup):
	from nhk.api import ops

	visit = _open_visit(cleanup)
	tomorrow = frappe.utils.add_days(frappe.utils.today(), 1)
	result = _office(ops.reschedule, visit, tomorrow, "Evening")
	assert (str(result["scheduled_datetime"]), result["slot"]) == ("%s 17:00:00" % tomorrow, "Evening"), result
	assert str(frappe.db.get_value("Technician Visit Entry", visit, "scheduled_datetime")) == "%s 17:00:00" % tomorrow


def test_rescheduling_refuses_the_past_and_a_closed_visit(cleanup):
	from nhk.api import ops

	visit = _open_visit(cleanup)
	for args in ((visit, frappe.utils.add_days(frappe.utils.today(), -1), "Morning"),):
		try:
			_office(ops.reschedule, *args)
		except frappe.ValidationError as exc:
			assert "past" in str(exc), exc
		else:
			raise AssertionError("rescheduled into the past")

	frappe.db.set_value("Technician Visit Entry", visit, "status", "Delivered")
	try:
		_office(ops.reschedule, visit, frappe.utils.add_days(frappe.utils.today(), 1))
	except frappe.ValidationError as exc:
		assert "Delivered" in str(exc), exc
	else:
		raise AssertionError("a delivered visit was rescheduled")


def test_rejected_visits_are_listed_whatever_day_they_were_for(cleanup):
	from nhk.api import ops

	old = _open_visit(cleanup, response="Rejected", hours_old=24 * 9)
	frappe.db.set_value("Technician Visit Entry", old, "scheduled_datetime",
						frappe.utils.add_days(frappe.utils.now_datetime(), -9), update_modified=False)
	row = _row(_office(ops.open_visits, "rejected")["rows"], old)
	# Reassign only: a rejected visit needs a technician before a new time, as on the desk.
	assert row and row["rejection_reason"] == "Bike Service" and row["actions"] == ["reassign"], row


def test_unanswered_counts_from_when_the_visit_was_last_given_out(cleanup):
	from nhk.api import ops
	from nhk.api.ops import UNANSWERED_AFTER_HOURS

	stale = _open_visit(cleanup, hours_old=UNANSWERED_AFTER_HOURS + 1)
	fresh = _open_visit(cleanup)
	moved = _open_visit(cleanup, hours_old=UNANSWERED_AFTER_HOURS + 1)
	_office(ops.reassign_visit, moved, OTHER)  # given out again just now
	_forget_comments(cleanup, moved)

	listed = {r["name"] for r in _office(ops.open_visits, "unanswered")["rows"]}
	assert stale in listed and fresh not in listed and moved not in listed, (stale, fresh, moved)


def test_the_office_home_counts_what_each_card_opens(cleanup):
	from nhk.api import ops

	_open_visit(cleanup, response="Rejected")
	counts = _office(ops.attention)
	assert counts["rejected"] == len(_office(ops.open_visits, "rejected")["rows"]) >= 1
	assert counts["unanswered"] == len(_office(ops.open_visits, "unanswered")["rows"])
	assert counts["pickups_to_assign"] == _office(ops.pickups, group="To Assign")["counts"]["To Assign"]
	orders = _office(ops.sales_orders, status="Order")["counts"]["order_type"]
	assert counts["orders_to_assign"] == orders.get("Sales", 0) + orders.get("Service", 0)


def test_technicians_are_the_enabled_logins_on_duty_first_least_busy_next(cleanup):
	from nhk.api import ops
	from test_staff_api import _on_duty

	_open_visit(cleanup)  # ASSIGNEE has one open visit today
	_on_duty(cleanup)     # and is on duty
	frappe.set_user("Administrator")

	rows = _office(ops.technicians)["rows"]
	me = next(r for r in rows if r["technician_id"] == ASSIGNEE)
	assert me["on_duty"] is True and me["open_visits"] >= 1, me
	keys = [(not r["on_duty"], r["open_visits"]) for r in rows]
	assert keys == sorted(keys), keys
	enabled = {u.lower() for u in frappe.get_all("User", filters={"enabled": 1}, pluck="name")}
	for r in rows:
		login = frappe.db.get_value("Technician Details", r["technician_id"], "user_mail_id")
		assert login and login.lower() in enabled, r


def test_order_visits_and_pickups_carry_only_the_phones_actions(cleanup):
	from nhk.api import ops
	from nhk.api.ops import VISIT_ACTIONS

	order = frappe.db.sql("""select sales_order_id from `tabTechnician Visit Entry`
		where status not in ('Assigned') and sales_order_id is not null order by creation desc limit 1""")[0][0]
	for visit in _office(ops.sales_order, order)["visits"]:
		assert set(visit["actions"]) <= set(VISIT_ACTIONS), visit["actions"]

	for row in _board("Assigned")[0]:
		assert row["pickup"]["actions"], row["pickup"]


def test_only_the_office_sees_and_moves_visits(cleanup):
	from nhk.api import ops

	visit = _open_visit(cleanup)
	user = technician_only()
	for fn, args in ((ops.today, ()), (ops.open_visits, ("rejected",)), (ops.attention, ()),
					 (ops.technicians, ()), (ops.reassign_visit, (visit, OTHER)),
					 (ops.reschedule, (visit, frappe.utils.add_days(frappe.utils.today(), 1)))):
		assert _refused(user, fn, *args), fn.__name__
	assert frappe.db.get_value("Technician Visit Entry", visit, "technician_id") == ASSIGNEE


# --------------------------------------------------------------------------
# sleep_study_pickups: the desk block's second group, on the phone
# --------------------------------------------------------------------------

def test_sleep_study_pickups_are_the_desk_blocks_rows_with_actions(cleanup):
	from nhk.api import office, ops

	so = _rental(cleanup)
	_delivered(cleanup, so, category="Sleep Study Level 2")
	phone = _office(ops.sleep_study_pickups)
	desk = _office(office.sleep_study_pickups)
	assert [r["sales_order_id"] for r in phone["rows"]] == [r["sales_order_id"] for r in desk["rows"]]
	assert phone["counts"] == desk["counts"]
	row = next(r for r in phone["rows"] if r["sales_order_id"] == so)
	assert row["group"] == "With Patient" and row["actions"] == ["assign_pickup"], row


def test_a_sleep_study_pickup_needs_no_reason_and_gets_the_studys(cleanup):
	from nhk.api import ops

	so = _rental(cleanup)
	_delivered(cleanup, so, category="Sleep Study Level 2")
	result = _assign_pickup(cleanup, so, pickup_reason=None, technician_id="NHK-TEC-003")
	assert frappe.db.get_value("Sales Order", so, ["status", "pickup_reason"]) == ("Ready for Pickup", "Other Reason")
	assert frappe.db.get_value("Sales Order", so, "pickup_remark").startswith("Sleep study complete")

	row = next(r for r in _office(ops.sleep_study_pickups)["rows"] if r["sales_order_id"] == so)
	assert row["group"] == "Assigned" and row["actions"] == [], row
	assert row["pickup"]["name"] == result["name"]
	assert row["pickup"]["actions"] == ["reassign", "reschedule"], row["pickup"]


def test_any_other_rental_still_needs_a_reason(cleanup):
	so = _rental(cleanup)
	_delivered(cleanup, so, category="Order")
	assert "picked up" in _pickup_refusal(cleanup, so, pickup_reason=None)


def test_only_the_office_sees_sleep_study_pickups(cleanup):
	from nhk.api import ops

	assert _refused(technician_only(), ops.sleep_study_pickups)


# --------------------------------------------------------------------------
# month and shortcuts: the Office tab's three pills
# --------------------------------------------------------------------------

def _all_of(**kwargs):
	names, cursor = [], None
	while True:
		page = _list(cursor=cursor, limit=100, **kwargs)
		names += [r["name"] for r in page["rows"]]
		cursor = page["next_cursor"]
		if not cursor:
			return names, page


def test_three_shortcuts_each_counting_what_it_opens(cleanup):
	for month in ("2026-09", frappe.utils.today()[:7]):
		page = _list(month=month)
		assert [sh["key"] for sh in page["shortcuts"]] == ["total", "to_assign", "pickups_due"], page["shortcuts"]
		assert page["month"] == month
		for sh in page["shortcuts"]:
			names, _last = _all_of(month=month, shortcut=sh["key"])
			assert len(names) == len(set(names)) == sh["count"], (month, sh, len(names))


def test_total_and_to_assign_are_the_months_orders(cleanup):
	month = "2026-09"
	total, _ = _all_of(month=month, shortcut="total")
	expected = frappe.get_all("Sales Order", filters={
		"docstatus": 1, "transaction_date": ("between", ("2026-09-01", "2026-09-30"))}, pluck="name")
	assert sorted(total) == sorted(expected), (len(total), len(expected))

	to_assign, _ = _all_of(month=month, shortcut="to_assign")
	rows = frappe.get_all("Sales Order", filters={"name": ("in", to_assign or [""])},
						  fields=["order_type", "status", "transaction_date"])
	assert all(r.status == "Order" and r.order_type in ("Sales", "Service") for r in rows)
	assert all(str(r.transaction_date)[:7] == month for r in rows)


def test_pickups_due_soonest_first_overdue_only_this_month(cleanup):
	this_month = frappe.utils.today()[:7]
	start = frappe.utils.getdate(this_month + "-01")
	names, _ = _all_of(month=this_month, shortcut="pickups_due")
	rows = {r.name: r for r in frappe.get_all("Sales Order", filters={"name": ("in", names or [""])},
											   fields=["name", "order_type", "status", "end_date"])}
	ends = [rows[n].end_date for n in names]
	assert ends == sorted(ends), "not soonest first"
	assert all(rows[n].order_type == "Rental" and rows[n].status in ("Active", "Ready for Pickup") for n in names)
	assert any(e < start for e in ends), "this month should include overdue rentals"

	past, _ = _all_of(month="2026-08", shortcut="pickups_due")
	past_ends = frappe.get_all("Sales Order", filters={"name": ("in", past or [""])}, pluck="end_date")
	assert all(str(e)[:7] == "2026-08" for e in past_ends), "another month shows only what fell due in it"


def test_hand_set_filters_stay_inside_the_month(cleanup):
	names, page = _all_of(month="2026-09", order_type="Rental")
	dates = frappe.get_all("Sales Order", filters={"name": ("in", names or [""])},
						   fields=["transaction_date", "order_type"])
	assert all(str(d.transaction_date)[:7] == "2026-09" and d.order_type == "Rental" for d in dates)
	assert page["counts"]["order_type"], "the filter sheet still gets its counts"


def test_a_month_must_look_like_a_month(cleanup):
	try:
		_list(month="October")
	except frappe.ValidationError as exc:
		assert "2026-10" in str(exc), exc
	else:
		raise AssertionError("a malformed month was accepted")


if __name__ == "__main__":
	import harness
	raise SystemExit(harness.run(sys.modules[__name__]))
