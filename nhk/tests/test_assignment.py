"""Behaviour of reassignment (`nhk.api.assignment`).

Every test here fails against the code as it was before `nhk/api/assignment.py`
existed: reassignment was a bare edit to `technician_id`, and nothing carried the
share, the answer or the Sales Order with it.

Run:  cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_assignment.py
"""

import sys

import frappe

sys.path.insert(0, __file__.rsplit("/", 1)[0])

PILOT_TECH = "NHK-TEC-002"  # Basawaraj
PILOT_USER = "basawaraja.nhkmedical@gmail.com"
OTHER_TECH = "NHK-TEC-003"
OTHER_USER = "suvam.nirmalhealthcare@gmail.com"


def _visit(cleanup, technician=PILOT_TECH, user=PILOT_USER, type_="Delivery",
		   status="Assigned", response="Pending", reason=None):
	"""A visit assigned to `technician`, shared the way the office's own flow shares it."""
	so = frappe.db.get_value("Technician Visit Entry", {"sales_order_id": ("is", "set")}, "sales_order_id")

	# Reassignment writes the technician back onto the Sales Order, and this one is
	# real. Snapshot every field the sync touches so the test hands it back unchanged.
	if so:
		for field in ("custom_technician_id_before_delivered", "custom_technician_id_pickup"):
			cleanup.restore("Sales Order", so, field)
		for item in frappe.get_all("Sales Order Item", filters={"parent": so}, pluck="name"):
			for field in ("technician_id_before_deliverd", "technician_id_after_delivered"):
				cleanup.restore("Sales Order Item", item, field)

	doc = frappe.get_doc({
		"doctype": "Technician Visit Entry",
		"technician_id": technician,
		"sales_order_id": so,
		"type": type_,
		"status": status,
		"technician_category": "Order",
		"kilometers": 5,
		"technician_response": response,
		"rejection_reason": reason,
	}).insert(ignore_permissions=True)
	cleanup.add("Technician Visit Entry", doc.name)

	frappe.share.add_docshare("Technician Visit Entry", doc.name, user, read=1, write=1,
							  flags={"ignore_share_permission": True})
	return doc


def _shares(visit_name):
	"""{user: write} for one visit."""
	rows = frappe.get_all(
		"DocShare",
		filters={"share_doctype": "Technician Visit Entry", "share_name": visit_name},
		fields=["user", "write"],
	)
	return {r.user: r.write for r in rows}


# --------------------------------------------------------------------------
# the share moves
# --------------------------------------------------------------------------


def test_reassignment_gives_the_new_technician_write(cleanup):
	"""The share is a technician's only access -- if_owner never matches them."""
	visit = _visit(cleanup)

	visit.technician_id = OTHER_TECH
	visit.save()

	shares = _shares(visit.name)
	assert OTHER_USER in shares, "the new technician was left with no share at all"
	assert shares[OTHER_USER] == 1, "the new technician cannot update the visit"


def test_reassignment_downgrades_the_previous_technician_to_read(cleanup):
	"""They keep read -- they may still have the patient on the phone -- not write."""
	visit = _visit(cleanup)

	visit.technician_id = OTHER_TECH
	visit.save()

	shares = _shares(visit.name)
	assert PILOT_USER in shares, "the previous technician should keep read access"
	assert shares[PILOT_USER] == 0, "the previous technician still holds write"


def test_reassignment_moves_the_share_for_every_visit_type(cleanup):
	"""The old gate only fired for type 'Service', which nothing creates."""
	for type_ in ("Delivery", "Pickup", "Technician Assignment For Sales",
				  "Technician Assignment For Service"):
		visit = _visit(cleanup, type_=type_)
		visit.technician_id = OTHER_TECH
		visit.save()

		shares = _shares(visit.name)
		assert shares.get(OTHER_USER) == 1, "%s visit did not move its share" % type_


# --------------------------------------------------------------------------
# the answer resets
# --------------------------------------------------------------------------


def test_reassignment_clears_a_rejection(cleanup):
	"""Rejection is the commonest reason to reassign, so this is the normal path.

	A carried-over `Rejected` is filtered out of `my_jobs` and refused by
	`accept_job`, so without this the reassignment changes nothing.
	"""
	visit = _visit(cleanup, response="Rejected", reason="No time")
	frappe.db.set_value("Technician Visit Entry", visit.name, {
		"technician_response": "Rejected", "rejection_reason": "No time",
	})
	visit.reload()

	visit.technician_id = OTHER_TECH
	visit.save()

	row = frappe.db.get_value("Technician Visit Entry", visit.name,
							  ["technician_response", "rejection_reason", "technician_response_at"],
							  as_dict=True)
	assert row.technician_response == "Pending", "the new technician inherited a rejection"
	assert not row.rejection_reason, "the previous technician's reason is still on the visit"
	assert not row.technician_response_at


def test_the_previous_answer_survives_as_a_comment(cleanup):
	"""`reject_job` writes with db.set_value, so the change log never held it."""
	visit = _visit(cleanup, response="Rejected", reason="Patient not reachable")
	frappe.db.set_value("Technician Visit Entry", visit.name, {
		"technician_response": "Rejected", "rejection_reason": "Patient not reachable",
	})
	visit.reload()

	visit.technician_id = OTHER_TECH
	visit.save()

	comments = frappe.get_all("Comment", filters={
		"reference_doctype": "Technician Visit Entry", "reference_name": visit.name,
	}, pluck="content")
	assert any("Patient not reachable" in (c or "") for c in comments), \
		"the rejection reason was destroyed by the reset"


def test_a_reassigned_job_can_be_accepted_by_the_new_technician(cleanup):
	"""End to end: the whole point of the flow."""
	from nhk.api import staff

	visit = _visit(cleanup, response="Rejected", reason="No time")
	frappe.db.set_value("Technician Visit Entry", visit.name, "technician_response", "Rejected")
	visit.reload()

	visit.technician_id = OTHER_TECH
	visit.save()

	frappe.set_user(OTHER_USER)
	cleanup.add("Technician Check In", staff.start_duty()["name"])
	result = staff.accept_job(visit.name)
	frappe.set_user("Administrator")

	assert result["technician_response"] == "Accepted"


def test_a_reassigned_job_appears_for_the_new_technician_and_not_the_old(cleanup):
	"""`my_jobs` reads through permissions, so this is the share and the reset together."""
	from nhk.api import staff

	visit = _visit(cleanup)
	visit.technician_id = OTHER_TECH
	visit.save()

	frappe.set_user(OTHER_USER)
	cleanup.add("Technician Check In", staff.start_duty()["name"])
	new_names = [j["name"] for j in staff.my_jobs(include_backlog=1)]
	frappe.set_user("Administrator")

	frappe.set_user(PILOT_USER)
	cleanup.add("Technician Check In", staff.start_duty()["name"])
	old_names = [j["name"] for j in staff.my_jobs(include_backlog=1)]
	frappe.set_user("Administrator")

	assert visit.name in new_names, "the new technician cannot see the job"
	assert visit.name not in old_names, "the previous technician still has the job"


# --------------------------------------------------------------------------
# the Sales Order follows
# --------------------------------------------------------------------------


def test_the_sales_order_names_the_new_technician(cleanup):
	"""The payout queries read these fields, so a stale one misattributes the work."""
	visit = _visit(cleanup, type_="Delivery")
	if not visit.sales_order_id:
		return

	visit.technician_id = OTHER_TECH
	visit.save()

	assert frappe.db.get_value("Sales Order", visit.sales_order_id,
							   "custom_technician_id_before_delivered") == OTHER_TECH


def test_a_pickup_updates_the_pickup_field_not_the_delivery_one(cleanup):
	visit = _visit(cleanup, type_="Pickup")
	if not visit.sales_order_id:
		return

	visit.technician_id = OTHER_TECH
	visit.save()

	assert frappe.db.get_value("Sales Order", visit.sales_order_id,
							   "custom_technician_id_pickup") == OTHER_TECH


# --------------------------------------------------------------------------
# guards
# --------------------------------------------------------------------------


def test_a_closed_visit_cannot_be_reassigned(cleanup):
	"""Past `Assigned` the payout run owns the row."""
	visit = _visit(cleanup, status="Delivered")

	visit.technician_id = OTHER_TECH
	try:
		visit.save()
	except frappe.ValidationError:
		return
	raise AssertionError("a Delivered visit was reassigned")


def test_reassignment_is_refused_once_the_technician_has_arrived(cleanup):
	"""`reject_job` refuses after arrival; this is the office side of that rule."""
	from nhk.api import staff
	from nhk.api.assignment import VisitInProgress

	visit = _visit(cleanup, response="Accepted")
	frappe.db.set_value("Technician Visit Entry", visit.name, "technician_response", "Accepted")

	frappe.set_user(PILOT_USER)
	cleanup.add("Technician Check In", staff.start_duty()["name"])
	cleanup.add("Technician Check In", staff.check_in(visit.name, latitude=12.9, longitude=77.5)["name"])
	frappe.set_user("Administrator")

	visit.reload()
	visit.technician_id = OTHER_TECH
	try:
		visit.save()
	except VisitInProgress:
		return
	raise AssertionError("a visit was moved out from under a technician already on site")


def test_force_reassign_closes_the_arrival(cleanup):
	"""The deliberate version of what the form used to do silently."""
	from nhk.api import assignment, staff

	visit = _visit(cleanup, response="Accepted")
	frappe.db.set_value("Technician Visit Entry", visit.name, "technician_response", "Accepted")

	frappe.set_user(PILOT_USER)
	cleanup.add("Technician Check In", staff.start_duty()["name"])
	checkin = staff.check_in(visit.name, latitude=12.9, longitude=77.5)["name"]
	cleanup.add("Technician Check In", checkin)
	frappe.set_user("Administrator")

	assignment.reassign_visit(visit.name, OTHER_TECH, force=1)

	assert frappe.db.get_value("Technician Check In", checkin, "closed_at"), \
		"the previous technician was left checked in to someone else's job"
	assert not frappe.db.get_value("Technician Visit Entry", visit.name, "started_at"), \
		"the new technician inherited an arrival stamp"


# --------------------------------------------------------------------------
# the withdrawn endpoint
# --------------------------------------------------------------------------


def test_a_technician_cannot_reassign_their_own_job(cleanup):
	"""They hold write through the share; reassignment is still the office's call."""
	from nhk.api import assignment

	visit = _visit(cleanup)

	frappe.set_user(PILOT_USER)
	try:
		assignment.reassign_visit(visit.name, OTHER_TECH)
	except frappe.PermissionError:
		return
	finally:
		frappe.set_user("Administrator")
	raise AssertionError("a technician handed their own job to someone else")


def test_an_office_user_can_reassign(cleanup):
	"""What the `Reassign Technician` button on the form actually calls.

	Administrator passes every gate, so it proves nothing about the office. This
	runs as a real `NHK Admin` holder: they hold `share` on the visit, which is the
	permission `reassign_visit` checks, and they can read Technician Details, which
	is what fills the dialog's link field.
	"""
	from nhk.api import assignment

	office = frappe.db.get_value("Has Role", {"role": "NHK Admin", "parenttype": "User"}, "parent")
	if not office:
		return

	visit = _visit(cleanup)

	frappe.set_user(office)
	try:
		result = assignment.reassign_visit(visit.name, OTHER_TECH)
	finally:
		frappe.set_user("Administrator")

	assert result["moved"] is True
	assert _shares(visit.name).get(OTHER_USER) == 1, "the office user's reassignment moved no share"


def test_update_shares_refuses(cleanup):
	"""It took any doctype and docname from any logged-in session."""
	from nhk.custom_script import update_shares

	visit = _visit(cleanup)
	try:
		update_shares("Technician Visit Entry", visit.name, OTHER_USER)
	except frappe.PermissionError:
		return
	raise AssertionError("update_shares still rewrites shares on demand")


# --------------------------------------------------------------------------
# repricing
# --------------------------------------------------------------------------


def test_changing_the_category_reprices_the_visit(cleanup):
	"""Category selects the slab table; it used to be ignored once charges was set.

	A 5km Pickup pays 50 under `Order` and 200 under `Sleep Study Level 2`. Most
	category pairs are useless for this -- `Order` and `Visit`, for instance, carry
	identical rates in every distance band, so swapping them proves nothing.
	"""
	visit = _visit(cleanup, type_="Pickup")
	before = frappe.db.get_value("Technician Visit Entry", visit.name, "charges")
	assert before == 50.0, "expected the Order pickup rate at 5km, got %s" % before

	visit.reload()
	visit.technician_category = "Sleep Study Level 2"
	visit.save()

	after = frappe.db.get_value("Technician Visit Entry", visit.name, "charges")
	assert after == 200.0, "the visit kept the previous category's rate (%s)" % after


def test_reassignment_leaves_the_category_alone(cleanup):
	"""It describes the work, not the worker -- and the work has not changed."""
	visit = _visit(cleanup)

	visit.technician_id = OTHER_TECH
	visit.save()

	assert frappe.db.get_value("Technician Visit Entry", visit.name,
							   "technician_category") == "Order"


if __name__ == "__main__":
	import harness
	raise SystemExit(harness.run(sys.modules[__name__]))
