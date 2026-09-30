"""Behaviour of the monthly technician payout (`nhk.api.payouts`) and the
extra-payment and payout-lock rules on Technician Visit Entry.

Run:  cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_payouts.py

**These tests only ever use months in 2019.** `process_month` settles every
counted visit in the month, so a test run against a real month would lock real
technicians' real pay. Every test that processes asserts first that the month
holds nothing but its own fixtures.
"""

import sys

import frappe

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from test_staff_api import OTHER_TECH, PILOT_TECH, PILOT_USER, _assigned_order, _on_duty, _visit
from test_visits import _office_user

#: Office, and a System Manager, but not `NHK Admin`: the visit form hides the
#: payout buttons from this account, and the payout endpoints refuse it.
NOT_A_PAYOUT_ADMIN = "pankaj@360ithub.com"


def _done(cleanup, month, day=10, technician=PILOT_TECH, charges=100, extra=0, reason=None,
		  status="Service Done", sales_order=None):
	"""A completed visit dated `month`-`day`, with the given pay, written directly."""
	name = _visit(cleanup, technician=technician, type_="Technician Assignment For Service",
				  status=status, sales_order=sales_order)
	frappe.db.set_value("Technician Visit Entry", name, {
		"completed_at": "%s-%02d 11:00:00" % (month, day),
		"charges": charges,
		"extra_payment": extra,
		"extra_payment_reason": reason,
	}, update_modified=False)
	return name


def _drop_month(month):
	"""A processed month refuses deletion by design; tests remove theirs directly."""
	frappe.db.delete("Technician Payout Row", {"parent": month})
	frappe.db.delete("Technician Payout Month", {"name": month})


def _as(user, fn, *args, **kwargs):
	frappe.set_user(user)
	try:
		return fn(*args, **kwargs)
	finally:
		frappe.set_user("Administrator")


def _refused(exc_type, user, fn, *args, **kwargs):
	try:
		_as(user, fn, *args, **kwargs)
	except exc_type:
		return True
	return False


def _only_fixtures_in(month, fixtures):
	from nhk.api import payouts

	real = {v.name for v in payouts._month_visits(month)} - set(fixtures)
	assert not real, "%s holds real visits %s -- refusing to process it" % (month, sorted(real))


def _row(summary, technician):
	return next((r for r in summary["rows"] if r["technician_id"] == technician), None)


# --------------------------------------------------------------------------
# the visit: extra payment and the payout lock
# --------------------------------------------------------------------------

def test_an_extra_payment_needs_a_reason_and_other_needs_a_note(cleanup):
	doc = frappe.get_doc("Technician Visit Entry", _visit(cleanup))

	for amount, reason, note in ((-50, "Waiting", None), (200, None, None), (200, "Other", " ")):
		doc.reload()
		doc.extra_payment, doc.extra_payment_reason, doc.extra_payment_note = amount, reason, note
		try:
			doc.save(ignore_permissions=True)
		except frappe.ValidationError:
			continue
		raise AssertionError("extra %s / %r / %r was accepted" % (amount, reason, note))

	doc.reload()
	doc.extra_payment, doc.extra_payment_reason, doc.extra_payment_note = 200, "Other", "Toll gate"
	doc.save(ignore_permissions=True)
	assert doc.extra_payment == 200


def test_a_paid_visit_refuses_changes_to_its_pay(cleanup):
	name = _done(cleanup, "2019-01")
	frappe.db.set_value("Technician Visit Entry", name, {"status": "Closed", "payout_month": "2019-01"},
						update_modified=False)
	doc = frappe.get_doc("Technician Visit Entry", name)

	for field, value in (("charges", 999), ("kilometers", 40), ("extra_payment", 50), ("status", "Service Done")):
		doc.reload()
		doc.set(field, value)
		if field == "extra_payment":
			doc.extra_payment_reason = "Waiting"
		try:
			doc.save(ignore_permissions=True)
		except frappe.ValidationError as exc:
			assert "2019-01" in str(exc), "the refusal should name the payout: %s" % exc
			continue
		raise AssertionError("a paid visit's %s changed" % field)


# --------------------------------------------------------------------------
# the month's table
# --------------------------------------------------------------------------

def test_the_month_adds_up_visits_and_extras_separately(cleanup):
	from nhk.api import payouts

	month = "2019-02"
	_done(cleanup, month, charges=100)
	_done(cleanup, month, charges=150, extra=300, reason="Out of Station")
	_done(cleanup, month, technician=OTHER_TECH, charges=200, extra=50, reason="Waiting")
	_done(cleanup, "2019-03", charges=999)                       # another month
	_done(cleanup, month, charges=777, status="Amount Settled")  # paid by the old per-visit run

	summary = _as(_office_user(), payouts.month_summary, month)
	mine, theirs = _row(summary, PILOT_TECH), _row(summary, OTHER_TECH)

	assert (mine.visit_count, mine.visit_charges) == (2, 250), mine
	assert (mine.extra_count, mine.extra_payments) == (1, 300), mine
	assert mine.total == 550, mine
	assert (theirs.visit_charges, theirs.extra_payments, theirs.total) == (200, 50, 250), theirs
	assert summary["totals"]["total"] == 800, summary["totals"]
	assert summary["status"] == "Draft" and not summary["processed"]


def test_sales_and_fixed_are_saved_and_count_in_the_total(cleanup):
	from nhk.api import payouts

	month = "2019-04"
	_done(cleanup, month, charges=100)
	try:
		_as(_office_user(), payouts.save_month, month, [
			{"technician_id": PILOT_TECH, "sales_incentive": 250, "fixed_incentive": 1000},
			# someone paid only an incentive this month, with no visits at all
			{"technician_id": OTHER_TECH, "sales_incentive": 0, "fixed_incentive": 5000},
		])
		summary = _as(_office_user(), payouts.month_summary, month)
		mine, theirs = _row(summary, PILOT_TECH), _row(summary, OTHER_TECH)
		assert (mine.sales_incentive, mine.fixed_incentive, mine.total) == (250, 1000, 1350), mine
		assert theirs and theirs.visit_count == 0 and theirs.total == 5000, (
			"staff with only a fixed incentive dropped off the month: %s" % theirs
		)
	finally:
		_drop_month(month)


def test_the_drill_down_lists_the_visits_behind_a_row(cleanup):
	from nhk.api import payouts

	month = "2019-05"
	a = _done(cleanup, month, charges=100)
	b = _done(cleanup, month, day=20, charges=150, extra=300, reason="Waiting")
	_done(cleanup, month, technician=OTHER_TECH)

	visits = _as(_office_user(), payouts.technician_month, month, PILOT_TECH)
	assert [v.name for v in visits] == [a, b], visits
	assert visits[1].extra_payment_reason == "Waiting"


def test_only_nhk_admin_can_see_or_change_pay(cleanup):
	from nhk.api import payouts

	for user in (NOT_A_PAYOUT_ADMIN, PILOT_USER):
		for fn, args in ((payouts.month_summary, ("2019-06",)),
						 (payouts.save_month, ("2019-06", [])),
						 (payouts.process_month, ("2019-06",))):
			assert _refused(frappe.PermissionError, user, fn, *args), (
				"%s reached %s" % (user, fn.__name__)
			)
	assert not frappe.db.exists("Technician Payout Month", "2019-06")


# --------------------------------------------------------------------------
# processing: the month is frozen and its visits settled
# --------------------------------------------------------------------------

def test_processing_freezes_the_month_and_settles_its_visits(cleanup):
	from nhk.api import payouts

	month = "2019-07"
	a = _done(cleanup, month, charges=100)
	b = _done(cleanup, month, charges=150, extra=300, reason="Waiting")
	_only_fixtures_in(month, [a, b])
	try:
		_as(_office_user(), payouts.save_month, month,
			[{"technician_id": PILOT_TECH, "sales_incentive": 250, "fixed_incentive": 0}])
		result = _as(_office_user(), payouts.process_month, month)

		assert result["processed"] and result["status"] == "Processed", result
		assert _row(result, PILOT_TECH).total == 800, _row(result, PILOT_TECH)
		for name in (a, b):
			v = frappe.db.get_value("Technician Visit Entry", name,
									["status", "payment_status", "payout_month"], as_dict=True)
			assert (v.status, v.payment_status, v.payout_month) == ("Closed", "Cleared", month), v

		# Frozen: the saved figures stand even if a visit's charge is forced afterwards.
		frappe.db.set_value("Technician Visit Entry", a, "charges", 5000, update_modified=False)
		again = _as(_office_user(), payouts.month_summary, month)
		assert _row(again, PILOT_TECH).total == 800, "a processed month's figures moved"

		assert _refused(frappe.ValidationError, _office_user(), payouts.process_month, month), (
			"a month was processed twice"
		)
		assert _refused(frappe.ValidationError, _office_user(), payouts.save_month, month, []), (
			"a processed month's incentives were changed"
		)
	finally:
		_drop_month(month)


def test_a_month_that_has_not_ended_cannot_be_processed(cleanup):
	from nhk.api import payouts

	this_month = frappe.utils.nowdate()[:7]
	assert _refused(frappe.ValidationError, _office_user(), payouts.process_month, this_month)
	assert frappe.db.get_value("Technician Payout Month", this_month, "status") != "Processed"


def test_processing_does_not_commit_on_its_own(cleanup):
	from nhk.api import payouts

	month = "2019-08"
	a = _done(cleanup, month)
	_only_fixtures_in(month, [a])
	frappe.db.commit()
	try:
		_as(_office_user(), payouts.process_month, month)
		frappe.db.rollback()
		assert not frappe.db.exists("Technician Payout Month", month), "process_month committed"
		assert frappe.db.get_value("Technician Visit Entry", a, "status") == "Service Done"
	finally:
		_drop_month(month)


# --------------------------------------------------------------------------
# the office correcting an extra payment
# --------------------------------------------------------------------------

def test_the_office_corrects_an_extra_payment_until_the_month_is_paid(cleanup):
	from nhk.api import payouts

	so = _assigned_order(cleanup, "Service")
	name = _done(cleanup, "2019-09", sales_order=so, extra=100, reason="Waiting")

	result = _as(_office_user(), payouts.set_extra_payment, name, 250, "Out of Station")
	assert (result["extra_payment"], result["extra_payment_reason"]) == (250, "Out of Station"), result

	cleared = _as(_office_user(), payouts.set_extra_payment, name, 0)
	assert not cleared["extra_payment"] and not cleared["extra_payment_reason"], cleared

	assert _refused(frappe.ValidationError, _office_user(), payouts.set_extra_payment, name, 50, "Bribe")

	frappe.db.set_value("Technician Visit Entry", name, {"status": "Closed", "payout_month": "2019-09"},
						update_modified=False)
	assert _refused(frappe.ValidationError, _office_user(), payouts.set_extra_payment, name, 50, "Waiting"), (
		"a paid visit's extra was changed"
	)


def test_a_technician_cannot_correct_an_extra_through_the_office_endpoint(cleanup):
	from nhk.api import payouts

	so = _assigned_order(cleanup, "Service")
	name = _done(cleanup, "2019-10", sales_order=so)
	assert _refused(frappe.PermissionError, PILOT_USER, payouts.set_extra_payment, name, 500, "Waiting")


# --------------------------------------------------------------------------
# the app: the technician adds the extra when completing
# --------------------------------------------------------------------------

def test_the_technician_adds_an_extra_payment_when_completing(cleanup):
	from nhk.api import staff

	so = _assigned_order(cleanup, "Service")
	visit = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so)
	_on_duty(cleanup)
	cleanup.add("Technician Check In", staff.check_in(visit)["name"])

	result = staff.complete_job(visit, kilometers=12, extra_payment=300,
								extra_payment_reason="Out of Station")
	frappe.set_user("Administrator")

	assert (result["extra_payment"], result["extra_payment_reason"]) == (300, "Out of Station"), result
	doc = frappe.get_doc("Technician Visit Entry", visit)
	assert doc.status == "Service Done" and doc.extra_payment == 300


def test_an_app_completion_with_a_bad_extra_changes_nothing(cleanup):
	from nhk.api import staff

	so = _assigned_order(cleanup, "Service")
	visit = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so)
	_on_duty(cleanup)
	cleanup.add("Technician Check In", staff.check_in(visit)["name"])
	frappe.db.commit()

	try:
		staff.complete_job(visit, kilometers=12, extra_payment=300, extra_payment_reason="Other")
	except frappe.ValidationError:
		pass
	else:
		raise AssertionError("an 'Other' extra with no note was accepted")
	finally:
		frappe.set_user("Administrator")
		frappe.db.rollback()

	assert frappe.db.get_value("Technician Visit Entry", visit, "status") == "Assigned"


if __name__ == "__main__":
	import harness
	raise SystemExit(harness.run(sys.modules[__name__]))
