"""Behaviour of the shared completion routine (`nhk.api.visits`).

Every surface that closes a visit -- the app, the Sales Order, the visit form --
goes through `close_visit` / `complete_visit`, so what is pinned here is what a
closed visit looks like wherever it was closed from.

Run:  cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_visits.py
"""

import sys

import frappe

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from test_staff_api import PILOT_TECH, PILOT_USER, _assigned_order, _visit


def _doc(name):
	return frappe.get_doc("Technician Visit Entry", name)


def _open_checkin(cleanup, visit):
	return cleanup.add("Technician Check In", frappe.get_doc({
		"doctype": "Technician Check In",
		"technician_id": PILOT_TECH,
		"technician_user_id": PILOT_USER,
		"kind": "Visit",
		"visit_entry": visit,
		"checked_in_at": frappe.utils.now_datetime(),
	}).insert(ignore_permissions=True).name)


def _refuses(fn, *args, **kwargs):
	try:
		fn(*args, **kwargs)
	except frappe.ValidationError:
		return True
	return False


# --------------------------------------------------------------------------
# close_visit: the visit half
# --------------------------------------------------------------------------

def test_close_visit_prices_stamps_and_moves_the_status(cleanup):
	from nhk.api import visits

	name = _visit(cleanup)
	doc = _doc(name)
	visits.close_visit(doc, kilometers=25)

	doc.reload()
	assert doc.status == "Delivered", "closed at %r" % doc.status
	# Order / Delivery / 21-40 km is the 200 rupee slab -- see test_staff_api.
	assert doc.charges == 200, "expected the 21-40km delivery slab (200), got %s" % doc.charges
	assert doc.kilometers == 25
	assert doc.completed_at, "completed_at was not written"
	assert doc.technician_update_datetime, "technician_update_datetime was not written"


def test_close_visit_uses_each_types_completion_status(cleanup):
	from nhk.api import visits

	for type_, expected in visits.COMPLETION_STATUS.items():
		doc = _doc(_visit(cleanup, type_=type_))
		visits.close_visit(doc, kilometers=5)
		assert doc.status == expected, "%s closed at %r, expected %r" % (type_, doc.status, expected)


def test_close_visit_refuses_a_visit_that_is_not_open(cleanup):
	from nhk.api import visits

	doc = _doc(_visit(cleanup, status="Delivered"))
	assert _refuses(visits.close_visit, doc, kilometers=5), "a closed visit was closed again"


def test_close_visit_refuses_a_distance_that_cannot_be_priced(cleanup):
	from nhk.api import visits

	for bad in (None, "", 2.5, 0, -3):
		doc = _doc(_visit(cleanup))
		assert _refuses(visits.close_visit, doc, kilometers=bad), "distance %r was accepted" % (bad,)
		assert frappe.db.get_value("Technician Visit Entry", doc.name, "status") == "Assigned"


def test_close_visit_closes_the_open_checkin(cleanup):
	from nhk.api import visits

	name = _visit(cleanup)
	checkin = _open_checkin(cleanup, name)
	visits.close_visit(_doc(name), kilometers=5)

	closed = frappe.db.get_value("Technician Check In", checkin, ["closed_at", "close_reason"], as_dict=True)
	assert closed.closed_at, "the arrival was left open after the job closed"
	assert closed.close_reason == "Completed", "closed as %r" % closed.close_reason


def test_close_visit_needs_no_checkin(cleanup):
	"""The office completes most visits with nobody having checked in. That is
	the desk's call to make, not this routine's -- `complete_job` requires the
	check-in for the app, on its own."""
	from nhk.api import visits

	doc = _doc(_visit(cleanup))
	visits.close_visit(doc, kilometers=5)
	assert doc.status == "Delivered"


def test_close_visit_does_not_commit(cleanup):
	"""All-or-nothing is the caller's: a later step that raises must be able to
	take the visit back."""
	from nhk.api import visits

	name = _visit(cleanup)
	checkin = _open_checkin(cleanup, name)
	frappe.db.commit()

	visits.close_visit(_doc(name), kilometers=5)
	frappe.db.rollback()

	assert frappe.db.get_value("Technician Visit Entry", name, "status") == "Assigned", (
		"close_visit committed -- a failure after it can no longer be undone"
	)
	assert not frappe.db.get_value("Technician Check In", checkin, "closed_at")


# --------------------------------------------------------------------------
# complete_visit: the visit and its Sales Order, together
# --------------------------------------------------------------------------

def test_complete_visit_moves_the_order_with_the_visit(cleanup):
	from nhk.api import visits

	so = _assigned_order(cleanup, "Service")
	doc = _doc(_visit(cleanup, type_="Technician Assignment For Service", sales_order=so))
	visits.complete_visit(doc, kilometers=5)

	assert doc.status == "Service Done"
	assert frappe.db.get_value("Sales Order", so, "status") == "Technician Work Done"


def test_complete_visit_takes_nothing_back_half_done(cleanup):
	"""A Sales Order that cannot be advanced leaves the visit as it was."""
	from nhk.api import visits

	name = _visit(cleanup)
	frappe.db.commit()

	original = visits._advance_sales_order
	visits._advance_sales_order = lambda *a, **kw: frappe.throw("Item Is Not Reserved")
	try:
		assert _refuses(visits.complete_visit, _doc(name), kilometers=5)
	finally:
		visits._advance_sales_order = original
		frappe.db.rollback()

	assert frappe.db.get_value("Technician Visit Entry", name, "status") == "Assigned"


# --------------------------------------------------------------------------
# for_sales_order: what the Sales Order form shows
# --------------------------------------------------------------------------

def _office_user():
	"""A real office login: `NHK Admin`, and not also a technician.

	Administrator would pass every permission check here trivially; the point is
	what the people pressing the buttons can do.
	"""
	admins = set(frappe.get_all("Has Role", filters={"role": "NHK Admin", "parenttype": "User"}, pluck="parent"))
	techs = set(frappe.get_all("Has Role", filters={"role": "NHK Technician", "parenttype": "User"}, pluck="parent"))
	enabled = set(frappe.get_all("User", filters={"enabled": 1}, pluck="name"))
	office = sorted((admins - techs) & enabled - {"Administrator"})
	if not office:
		raise AssertionError("no enabled NHK Admin who is not also a technician on this site")
	return office[0]


def _order_with_no_visits():
	return frappe.db.sql(
		"""select so.name from `tabSales Order` so
		where so.docstatus = 1 and not exists (
			select 1 from `tabTechnician Visit Entry` v where v.sales_order_id = so.name)
		limit 1"""
	)[0][0]


def test_for_sales_order_lists_the_orders_visits_newest_first(cleanup):
	from nhk.api import visits

	so = _assigned_order(cleanup, "Service")
	first = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so)
	second = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so,
					response="Rejected")
	frappe.db.set_value("Technician Visit Entry", second, "rejection_reason", "Patient not home")
	frappe.db.set_value("Technician Visit Entry", first, "creation",
						frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-1),
						update_modified=False)

	frappe.set_user(_office_user())
	rows = visits.for_sales_order(so)

	names = [r["name"] for r in rows]
	assert first in names and second in names, "the order's visits are missing: %s" % names
	assert names.index(second) < names.index(first), "not newest first: %s" % names

	rejected = next(r for r in rows if r["name"] == second)
	assert rejected["technician_response"] == "Rejected"
	assert rejected["rejection_reason"] == "Patient not home", "the office cannot see why it was rejected"
	for field in ("type", "technician_name", "status", "started_at", "completed_at",
				  "kilometers", "charges", "attachment_count", "can_complete"):
		assert field in rejected, "row is missing %s" % field


def test_for_sales_order_counts_attachments(cleanup):
	from nhk.api import visits

	so = _assigned_order(cleanup, "Service")
	visit = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so)
	for i in range(2):
		cleanup.add("File", frappe.get_doc({
			"doctype": "File",
			"attached_to_doctype": "Technician Visit Entry",
			"attached_to_name": visit,
			"file_name": "photo-%d.txt" % i,
			"is_private": 1,
			"content": b"x",
		}).insert(ignore_permissions=True).name)

	frappe.set_user(_office_user())
	row = next(r for r in visits.for_sales_order(so) if r["name"] == visit)
	assert row["attachment_count"] == 2, "counted %s attachments" % row["attachment_count"]


def test_for_sales_order_offers_completion_only_on_an_open_visit(cleanup):
	from nhk.api import visits

	so = _assigned_order(cleanup, "Service")
	open_ = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so)
	closed = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so,
					status="Service Done")

	delivery = _visit(cleanup, type_="Delivery", sales_order=so)

	frappe.set_user(_office_user())
	rows = {r["name"]: r for r in visits.for_sales_order(so)}
	assert rows[open_]["can_complete"], "the office cannot complete an open visit"
	assert not rows[closed]["can_complete"], "a closed visit was offered for completion"
	# Deliveries and pickups move stock through the order's own buttons, which
	# collect the agreement and payment details first -- see the endpoint.
	assert not rows[delivery]["can_complete"], "a delivery was offered for completion from the row"


def test_for_sales_order_is_empty_for_an_order_without_visits(cleanup):
	from nhk.api import visits

	frappe.set_user(_office_user())
	assert visits.for_sales_order(_order_with_no_visits()) == []


def test_for_sales_order_refuses_a_technician(cleanup):
	"""By the order's own permissions, not by role: two real technicians also
	hold `NHK Admin` and must keep seeing orders. `NHK Technician` has no read
	on Sales Order, so a plain technician is refused -- even on an order that
	holds their own visit."""
	from nhk.api import visits

	so = _assigned_order(cleanup, "Service")
	_visit(cleanup, type_="Technician Assignment For Service", sales_order=so)

	frappe.set_user(PILOT_USER)
	try:
		visits.for_sales_order(so)
	except frappe.PermissionError:
		return
	raise AssertionError("a technician read the order's visit list")


# --------------------------------------------------------------------------
# complete_from_sales_order: the office closing a visit from the order
# --------------------------------------------------------------------------

def _office_completes(cleanup, type_, order_type):
	from nhk.api import visits

	so = _assigned_order(cleanup, order_type)
	visit = _visit(cleanup, type_=type_, sales_order=so)

	frappe.set_user(_office_user())
	result = visits.complete_from_sales_order(visit, kilometers=25)
	frappe.set_user("Administrator")

	doc = _doc(visit)
	return so, doc, result


def test_office_completes_an_installation_from_the_order(cleanup):
	so, doc, result = _office_completes(cleanup, "Technician Assignment For Sales", "Sales")

	assert doc.status == "Installation Done", "closed at %r" % doc.status
	assert result["status"] == "Installation Done"
	assert doc.charges, "closed from the order without a charge -- the bug this replaces"
	assert doc.completed_at, "closed from the order without a completion time"
	assert doc.kilometers == 25
	assert frappe.db.get_value("Sales Order", so, "status") == "Technician Work Done"


def test_office_completes_a_service_from_the_order(cleanup):
	so, doc, _result = _office_completes(cleanup, "Technician Assignment For Service", "Service")

	assert doc.status == "Service Done", "closed at %r" % doc.status
	assert doc.charges and doc.completed_at
	assert frappe.db.get_value("Sales Order", so, "status") == "Technician Work Done"


def test_office_completion_closes_the_technicians_arrival(cleanup):
	from nhk.api import visits

	so = _assigned_order(cleanup, "Service")
	visit = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so)
	checkin = _open_checkin(cleanup, visit)

	frappe.set_user(_office_user())
	visits.complete_from_sales_order(visit, kilometers=5)
	frappe.set_user("Administrator")

	assert frappe.db.get_value("Technician Check In", checkin, "closed_at"), (
		"the technician's arrival stayed open after the office closed the job"
	)


def test_office_notes_are_added_to_the_technicians(cleanup):
	"""`notes` is the technician's field. The office writing at completion must
	not wipe what the technician wrote from the doorstep."""
	from nhk.api import visits

	so = _assigned_order(cleanup, "Service")
	visit = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so)
	frappe.db.set_value("Technician Visit Entry", visit, "notes", "Mask replaced")

	frappe.set_user(_office_user())
	visits.complete_from_sales_order(visit, kilometers=5, notes="Patient confirmed by phone")
	frappe.set_user("Administrator")

	notes = _doc(visit).notes
	assert "Mask replaced" in notes, "the technician's note was overwritten: %r" % notes
	assert "Patient confirmed by phone" in notes, "the office note was dropped: %r" % notes


def test_complete_from_sales_order_refuses_a_technician(cleanup):
	"""Technicians close their jobs through `staff.complete_job`, which checks
	duty, acceptance and arrival. This endpoint skips those, so it must not be
	theirs -- even for their own visit."""
	from nhk.api import visits

	so = _assigned_order(cleanup, "Service")
	visit = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so)

	frappe.set_user(PILOT_USER)
	try:
		visits.complete_from_sales_order(visit, kilometers=5)
	except frappe.PermissionError:
		pass
	else:
		raise AssertionError("a technician completed a visit through the office endpoint")
	finally:
		frappe.set_user("Administrator")

	assert frappe.db.get_value("Technician Visit Entry", visit, "status") == "Assigned"


def test_complete_from_sales_order_leaves_deliveries_to_the_orders_own_buttons(cleanup):
	"""A delivery closed from here would run `make_delivered` without the
	agreement, ID and payment-pending details the order's `DELIVERED` dialog
	collects. Those stay with that button (issue 04)."""
	from nhk.api import visits

	for type_ in ("Delivery", "Pickup"):
		visit = _visit(cleanup, type_=type_)
		frappe.set_user(_office_user())
		try:
			assert _refuses(visits.complete_from_sales_order, visit, kilometers=5), (
				"a %s was completed from the order's visit list" % type_
			)
		finally:
			frappe.set_user("Administrator")
		assert frappe.db.get_value("Technician Visit Entry", visit, "status") == "Assigned"


def test_complete_from_sales_order_refuses_a_visit_with_no_order(cleanup):
	from nhk.api import visits

	visit = _visit(cleanup, type_="Technician Assignment For Service")
	frappe.db.set_value("Technician Visit Entry", visit, "sales_order_id", None)

	frappe.set_user(_office_user())
	try:
		assert _refuses(visits.complete_from_sales_order, visit, kilometers=5), (
			"a visit with no order was completed from 'the order'"
		)
	finally:
		frappe.set_user("Administrator")


def test_the_core_methods_the_form_shadows_still_exist(cleanup):
	"""`nhk/public/js/sales_order.js` takes over the order's buttons by shadowing
	these methods on `frm.cscript`. If ERPNext renames one, its button quietly
	goes back to the core behaviour -- a visit closed with no distance and no
	charge -- so a rename has to fail here instead."""
	path = frappe.get_app_path("erpnext", "selling", "doctype", "sales_order", "sales_order.js")
	source = open(path).read()
	# How each button calls its method: through `this` or through `me`, both of
	# which are `frm.cscript` where the buttons are built.
	calls = {
		"mark_technician_work_done": "this.mark_technician_work_done();",
		"mark_technician_work_done_service": "this.mark_technician_work_done_service();",
		"make_delivered": "me.make_delivered();",
		"make_submitted_to_office": "me.make_submitted_to_office();",
	}
	for method, call in calls.items():
		assert "\n\t%s(" % method in source, "ERPNext no longer defines %s()" % method
		assert call in source, "no ERPNext button calls %s() any more" % method


# --------------------------------------------------------------------------
# change_status_sales: the visit form's buttons
# --------------------------------------------------------------------------
#
# Both copies of the visit form script -- the app file and the enabled Client
# Script `technician Portal Sales order Details 2` -- send their `Service Done`
# / `Installation Done` buttons here, so this is where they are brought onto
# the shared routine. The form saves the distance first, then calls this.

def test_visit_form_completion_matches_an_order_completion(cleanup):
	from nhk.custom_script import change_status_sales

	so = _assigned_order(cleanup, "Service")
	visit = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so)
	checkin = _open_checkin(cleanup, visit)
	frappe.db.set_value("Technician Visit Entry", visit, "kilometers", 25)

	frappe.set_user(_office_user())
	message = change_status_sales(visit, "Service Done")
	frappe.set_user("Administrator")

	doc = _doc(visit)
	assert message, "the form shows the returned message; it must not be empty"
	assert doc.status == "Service Done", "closed at %r" % doc.status
	assert doc.charges, "closed from the visit form without a charge"
	assert doc.completed_at, "closed from the visit form without a completion time"
	assert frappe.db.get_value("Technician Check In", checkin, "closed_at"), "arrival left open"
	assert frappe.db.get_value("Sales Order", so, "status") == "Technician Work Done"


def test_visit_form_distance_travels_with_the_completion(cleanup):
	"""The form used to save the distance, then ask the server to complete. A
	refusal left the visit re-priced and still open. Sent together, a refusal
	takes both back."""
	from nhk.custom_script import change_status_sales

	so = _assigned_order(cleanup, "Service")
	visit = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so)

	frappe.set_user(_office_user())
	change_status_sales(visit, "Service Done", kilometers=25)
	frappe.set_user("Administrator")

	doc = _doc(visit)
	assert doc.status == "Service Done"
	assert doc.kilometers == 25, "the distance sent with the completion was not used: %s" % doc.kilometers


def test_a_refused_visit_form_completion_leaves_the_distance_alone(cleanup):
	from nhk.custom_script import change_status_sales

	so = _assigned_order(cleanup, "Service")
	visit = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so)
	before = frappe.db.get_value("Technician Visit Entry", visit, ["kilometers", "charges"], as_dict=True)
	frappe.db.commit()

	frappe.set_user(PILOT_USER)
	try:
		change_status_sales(visit, "Service Done", kilometers=45)
	except frappe.PermissionError:
		pass
	finally:
		frappe.set_user("Administrator")
		frappe.db.rollback()   # what the request handler does when the call throws

	after = frappe.db.get_value("Technician Visit Entry", visit, ["kilometers", "charges"], as_dict=True)
	assert (after.kilometers, after.charges) == (before.kilometers, before.charges), (
		"a refused completion still re-priced the visit: %s -> %s" % (before, after)
	)


def test_visit_form_refuses_a_status_that_is_not_the_types(cleanup):
	"""The old function wrote whatever status it was handed. That is how a
	`Technician Assignment For Service` visit ended up `Delivered`."""
	from nhk.custom_script import change_status_sales

	so = _assigned_order(cleanup, "Service")
	visit = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so)

	frappe.set_user(_office_user())
	try:
		for wrong in ("Installation Done", "Delivered"):
			assert _refuses(change_status_sales, visit, wrong), "%s was accepted" % wrong
	finally:
		frappe.set_user("Administrator")
	assert frappe.db.get_value("Technician Visit Entry", visit, "status") == "Assigned"


def test_visit_form_completion_is_not_open_to_the_technician(cleanup):
	"""It had no permission check at all. The technician holds write on their
	own visit through its share, so the order's permission is what stops them
	closing a job here without checking in."""
	from nhk.custom_script import change_status_sales

	so = _assigned_order(cleanup, "Service")
	visit = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so)

	frappe.set_user(PILOT_USER)
	try:
		change_status_sales(visit, "Service Done")
	except frappe.PermissionError as exc:
		# Decided 2026-09-25: technicians close service visits from the app only.
		# A bare "not permitted" leaves them nowhere to go.
		assert "app" in str(exc).lower(), "the refusal should send the technician to the app: %s" % exc
	else:
		raise AssertionError("a technician closed their job through the visit form's endpoint")
	finally:
		frappe.set_user("Administrator")
	assert frappe.db.get_value("Technician Visit Entry", visit, "status") == "Assigned"


def test_visit_form_completion_does_not_commit(cleanup):
	from nhk.custom_script import change_status_sales

	so = _assigned_order(cleanup, "Service")
	visit = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so)
	frappe.db.set_value("Technician Visit Entry", visit, "kilometers", 5)
	frappe.db.commit()

	frappe.set_user(_office_user())
	change_status_sales(visit, "Service Done")
	frappe.set_user("Administrator")
	frappe.db.rollback()

	assert frappe.db.get_value("Technician Visit Entry", visit, "status") == "Assigned", (
		"change_status_sales still commits on its own"
	)


# --------------------------------------------------------------------------
# rental orders: distance at DELIVERED / Submitted To Office (issue 04)
# --------------------------------------------------------------------------
#
# The order's own buttons close Delivery and Pickup visits, through the core
# `validate_technician_visit`. The office enters the distance at the button
# (`set_distance`), which only *holds* it: the order's save applies it, prices
# the visit and stamps the completion time, on the visits it closed. If the
# order never moves -- its own dialog cancelled, `make_delivered` raising --
# nothing on the visit changes. Decided 2026-09-25: the technician's check-in
# is *not* closed by this -- no automatic checkout for technicians.

def _rental_order(cleanup, status):
	so = frappe.db.get_value("Sales Order", {"order_type": "Rental", "docstatus": 1}, "name")
	cleanup.restore("Sales Order", so, "status")
	frappe.db.set_value("Sales Order", so, "status", status, update_modified=False)
	return so


def _held(cleanup, visit, kilometers):
	"""Hold a distance as the office would, and drop it when the test ends."""
	from nhk.api import visits

	frappe.set_user(_office_user())
	try:
		visits.set_distance(visit, kilometers)
	finally:
		frappe.set_user("Administrator")


def _forget(visit):
	from nhk.api import visits

	frappe.cache.delete_value(visits._held_distance_key(visit))


def test_set_distance_changes_nothing_until_the_order_moves(cleanup):
	"""The bug the second review found: the distance used to be saved before the
	order's own dialog. Cancelling that dialog, or `make_delivered` raising,
	left the visit re-priced and still open."""
	visit = _visit(cleanup, sales_order=_rental_order(cleanup, "DISPATCHED"))
	before = frappe.db.get_value("Technician Visit Entry", visit, ["kilometers", "charges"], as_dict=True)

	try:
		_held(cleanup, visit, 25)
		after = frappe.db.get_value("Technician Visit Entry", visit, ["status", "kilometers", "charges"], as_dict=True)
	finally:
		_forget(visit)

	assert after.status == "Assigned"
	assert (after.kilometers, after.charges) == (before.kilometers, before.charges), (
		"holding a distance changed the visit before the order moved: %s -> %s" % (before, after)
	)


def test_the_held_distance_prices_the_visit_when_the_order_closes_it(cleanup):
	so = _rental_order(cleanup, "DISPATCHED")
	visit = _visit(cleanup, sales_order=so)

	try:
		_held(cleanup, visit, 25)
		_order_closes(so, "DISPATCHED", "Active")
	finally:
		_forget(visit)

	doc = _doc(visit)
	assert doc.status == "Delivered"
	assert doc.kilometers == 25, "the held distance was not applied: %s" % doc.kilometers
	# Order / Delivery / 21-40 km is the 200 rupee slab.
	assert doc.charges == 200, "expected the 21-40km delivery slab (200), got %s" % doc.charges
	assert doc.completed_at


def test_a_held_distance_is_used_once(cleanup):
	"""Applied, then gone: a later order save must not re-apply a stale one."""
	from nhk.api import visits

	so = _rental_order(cleanup, "DISPATCHED")
	visit = _visit(cleanup, sales_order=so)
	try:
		_held(cleanup, visit, 25)
		_order_closes(so, "DISPATCHED", "Active")
		assert frappe.cache.get_value(visits._held_distance_key(visit)) is None, (
			"the held distance outlived the close it was for"
		)
	finally:
		_forget(visit)


def test_set_distance_refuses_what_cannot_be_priced_or_is_not_the_offices(cleanup):
	from nhk.api import visits

	so = _rental_order(cleanup, "DISPATCHED")
	visit = _visit(cleanup, sales_order=so)
	closed = _visit(cleanup, sales_order=so, status="Delivered")

	frappe.set_user(_office_user())
	try:
		for bad in (None, 2.5, 0):
			assert _refuses(visits.set_distance, visit, bad), "distance %r was accepted" % (bad,)
		assert _refuses(visits.set_distance, closed, 5), "a closed visit was re-priced"
	finally:
		frappe.set_user("Administrator")
		_forget(visit)
		_forget(closed)

	frappe.set_user(PILOT_USER)
	try:
		visits.set_distance(visit, 5)
	except frappe.PermissionError as exc:
		assert "app" in str(exc).lower(), "the refusal should send the technician to the app: %s" % exc
	else:
		raise AssertionError("a technician set the distance through the office endpoint")
	finally:
		frappe.set_user("Administrator")
		_forget(visit)


def _order_closes(so, before, after):
	"""What the order's save does to its visits, without saving a real order.

	Runs the real core `validate_technician_visit` -- the part that closes the
	visits -- then the nhk hook, handed the order as the save would hand it.
	A full save of a production-snapshot order runs stock, drop-ship and PO
	validation that has nothing to do with this.
	"""
	from nhk.api import visits

	order = frappe.get_doc("Sales Order", so)
	order.status = after
	order.modified = frappe.utils.now_datetime()   # what `_save` stamps before its hooks
	order.validate_technician_visit()
	order.get_doc_before_save = lambda: frappe._dict(status=before)
	visits.stamp_visits_closed_by_the_order(order, "on_update_after_submit")


def test_delivered_on_the_order_records_the_completion_time(cleanup):
	so = _rental_order(cleanup, "DISPATCHED")
	visit = _visit(cleanup, sales_order=so)
	frappe.db.set_value("Technician Visit Entry", visit, "kilometers", 12)
	checkin = _open_checkin(cleanup, visit)

	_order_closes(so, "DISPATCHED", "Active")

	doc = _doc(visit)
	assert doc.status == "Delivered", "the core did not close the visit: %r" % doc.status
	assert doc.completed_at, "the order closed the visit without a completion time"
	assert not frappe.db.get_value("Technician Check In", checkin, "closed_at"), (
		"the technician's check-in was closed -- no automatic checkout (decided 2026-09-25)"
	)


def test_submitted_to_office_records_the_pickup_completion_time(cleanup):
	so = _rental_order(cleanup, "Picked Up")
	visit = _visit(cleanup, type_="Pickup", sales_order=so)
	frappe.db.set_value("Technician Visit Entry", visit, "kilometers", 12)

	_order_closes(so, "Picked Up", "Submitted to Office")

	doc = _doc(visit)
	assert doc.status == "Picked up", "the core did not close the pickup: %r" % doc.status
	assert doc.completed_at, "the order closed the pickup without a completion time"


def test_the_order_stamps_only_the_visits_it_just_closed(cleanup):
	"""1,188 of 1,193 delivered visits have no completion time. An order moving
	to Active must not stamp its old ones with today's date."""
	so = _rental_order(cleanup, "DISPATCHED")
	old = _visit(cleanup, sales_order=so, status="Delivered")
	frappe.db.set_value("Technician Visit Entry", old, "modified",
						frappe.utils.add_to_date(frappe.utils.now_datetime(), days=-30),
						update_modified=False)

	_order_closes(so, "DISPATCHED", "Active")

	assert not frappe.db.get_value("Technician Visit Entry", old, "completed_at"), (
		"an old delivery was stamped with today's completion time"
	)


def test_other_order_changes_stamp_nothing(cleanup):
	so = _rental_order(cleanup, "Active")
	visit = _visit(cleanup, sales_order=so, status="Delivered")

	_order_closes(so, "Active", "Ready for Pickup")

	assert not frappe.db.get_value("Technician Visit Entry", visit, "completed_at")


# --------------------------------------------------------------------------
# the order's visit table: every action, from the row (issue 07)
# --------------------------------------------------------------------------
#
# `for_sales_order` says, per row, what is happening, what comes next and
# which actions the viewer may take; the endpoints below are those actions.
# No per-visit payout actions: pay is settled a month at a time
# (`nhk.api.payouts`, decided 2026-09-28).


def _row(so, visit, user=None):
	from nhk.api import visits

	frappe.set_user(user or _office_user())
	try:
		return next(r for r in visits.for_sales_order(so) if r["name"] == visit)
	finally:
		frappe.set_user("Administrator")


def _as_user(user, fn, *args, **kwargs):
	frappe.set_user(user)
	try:
		return fn(*args, **kwargs)
	finally:
		frappe.set_user("Administrator")


def _refused_permission(user, fn, *args, **kwargs):
	try:
		_as_user(user, fn, *args, **kwargs)
	except frappe.PermissionError:
		return True
	return False


def test_an_open_installation_offers_complete_reassign_and_reschedule(cleanup):
	so = _assigned_order(cleanup, "Sales")
	visit = _visit(cleanup, type_="Technician Assignment For Sales", sales_order=so)

	actions = _row(so, visit)["actions"]
	for expected in ("complete", "reassign", "reschedule", "extra_payment"):
		assert expected in actions, "%s missing from %s" % (expected, actions)


def test_a_delivery_offers_the_orders_own_button_only_when_the_order_is_ready(cleanup):
	so = _rental_order(cleanup, "DISPATCHED")
	visit = _visit(cleanup, sales_order=so)

	actions = _row(so, visit)["actions"]
	assert "mark_delivered" in actions, "a dispatched order's delivery offers no way to close it: %s" % actions
	assert "complete" not in actions, "a delivery was offered the list completion"

	frappe.db.set_value("Sales Order", so, "status", "Ready for Delivery", update_modified=False)
	assert "mark_delivered" not in _row(so, visit)["actions"], (
		"DELIVERED was offered before the order was dispatched"
	)


def test_a_pickup_offers_submitted_to_office_once_picked_up(cleanup):
	so = _rental_order(cleanup, "Picked Up")
	visit = _visit(cleanup, type_="Pickup", sales_order=so)

	assert "submit_to_office" in _row(so, visit)["actions"]


def test_no_visit_is_offered_a_per_visit_payout_action(cleanup):
	"""Decided 2026-09-28: pay is settled on the month, not visit by visit."""
	so = _assigned_order(cleanup, "Service")
	for status in ("Service Done", "Incentive Finalize", "Amount Settled"):
		visit = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so, status=status)
		actions = set(_row(so, visit)["actions"])
		assert not actions & {"finalize_incentive", "revert_incentive", "clear_and_close", "close"}, (
			"%s visit offered %s" % (status, actions)
		)


def test_extra_payment_is_offered_until_the_month_is_processed(cleanup):
	so = _assigned_order(cleanup, "Service")
	done = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so, status="Service Done")
	assert "extra_payment" in _row(so, done)["actions"], "a finished visit's extra cannot be corrected"

	paid = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so, status="Closed")
	frappe.db.set_value("Technician Visit Entry", paid, "payout_month", "2026-08", update_modified=False)
	row = _row(so, paid)
	assert "extra_payment" not in row["actions"], "a paid visit's extra was offered for change"
	assert "2026-08" in row["stage"], "a paid visit does not say which payout paid it: %s" % row["stage"]

def test_every_row_says_what_is_happening_and_what_is_next(cleanup):
	so = _assigned_order(cleanup, "Service")
	pending = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so, response="Pending")
	rejected = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so, response="Rejected")
	frappe.db.set_value("Technician Visit Entry", rejected, "rejection_reason", "Vehicle broke down")
	arrived = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so)
	frappe.db.set_value("Technician Visit Entry", arrived, "started_at", frappe.utils.now_datetime())

	for visit in (pending, rejected, arrived):
		row = _row(so, visit)
		assert row["stage"] and row["next_step"], "row %s says nothing: %s" % (visit, row)

	assert "accept" in _row(so, pending)["next_step"].lower()
	rej = _row(so, rejected)
	assert "Vehicle broke down" in rej["next_step"], "the rejection reason is missing: %s" % rej["next_step"]
	assert "reassign" in rej["actions"]
	assert "arrived" in _row(so, arrived)["stage"].lower()


def test_reschedule_moves_the_visit_and_is_the_offices(cleanup):
	from nhk.api import visits

	so = _assigned_order(cleanup, "Service")
	visit = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so)
	when = frappe.utils.add_to_date(frappe.utils.now_datetime(), days=2).replace(microsecond=0)

	_as_user(_office_user(), visits.reschedule, visit, str(when), "Afternoon")
	doc = _doc(visit)
	assert frappe.utils.get_datetime(doc.scheduled_datetime) == when, doc.scheduled_datetime
	assert doc.slot == "Afternoon"

	assert _refused_permission(PILOT_USER, visits.reschedule, visit, str(when), "Morning"), (
		"a technician rescheduled their own job"
	)
	closed = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so, status="Service Done")
	assert _refuses(_as_user, _office_user(), visits.reschedule, closed, str(when), "Morning")


def test_progress_shows_how_far_the_visit_has_got(cleanup):
	so = _assigned_order(cleanup, "Service")
	pending = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so, response="Pending")
	rejected = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so, response="Rejected")
	arrived = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so)
	frappe.db.set_value("Technician Visit Entry", arrived, "started_at", frappe.utils.now_datetime())
	done = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so, status="Service Done")
	closed = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so, status="Closed")

	reached = {v: _row(so, v)["progress"]["reached"] for v in (pending, arrived, done, closed)}
	assert _row(so, closed)["progress"]["steps"][-1] == "Paid"
	assert reached[pending] < reached[arrived] < reached[done] < reached[closed], reached
	steps = _row(so, closed)["progress"]["steps"]
	assert reached[closed] == len(steps) - 1, "a closed visit is not at the last step"
	assert _row(so, rejected)["progress"]["rejected"], "a rejected visit's progress does not say so"


def test_attachments_for_a_visit_on_the_order(cleanup):
	from nhk.api import visits

	so = _assigned_order(cleanup, "Service")
	visit = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so)
	cleanup.add("File", frappe.get_doc({
		"doctype": "File", "attached_to_doctype": "Technician Visit Entry", "attached_to_name": visit,
		"file_name": "doorstep.txt", "is_private": 1, "content": b"x",
	}).insert(ignore_permissions=True).name)

	files = _as_user(_office_user(), visits.attachments_for_visit, visit)
	assert [f["file_name"] for f in files] == ["doorstep.txt"], files
	assert _refused_permission(PILOT_USER, visits.attachments_for_visit, visit), (
		"a technician read attachments through the order's endpoint"
	)


if __name__ == "__main__":
	import harness
	raise SystemExit(harness.run(sys.modules[__name__]))
