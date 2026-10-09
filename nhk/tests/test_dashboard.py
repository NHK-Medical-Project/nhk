"""The technician app's month dashboard (`nhk.api.staff.my_month`).

Run:  cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_dashboard.py

Months are 2019, as in `test_payouts.py`: processing a month settles its
visits, and a real month holds real pay.
"""

import sys

import frappe

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from test_payouts import _done, _drop_month, _only_fixtures_in
from test_staff_api import OTHER_TECH, PILOT_TECH, PILOT_USER, _visit
from test_visits import _office_user


def _on_duty_once(cleanup):
	"""The month is refused off duty (decided 2026-09-29), so go on duty once."""
	from nhk.api.guards import open_duty
	from test_staff_api import _on_duty

	if not open_duty(PILOT_TECH):
		_on_duty(cleanup)
	frappe.set_user("Administrator")


def _my_month(cleanup, month=None):
	from nhk.api import staff

	_on_duty_once(cleanup)
	frappe.set_user(PILOT_USER)
	try:
		return staff.my_month(month)
	finally:
		frappe.set_user("Administrator")


def test_an_open_month_shows_the_payout_building_from_visits_and_extras_only(cleanup):
	"""Decided 2026-10-01: sales and fixed incentives are left out until the
	office has entered them and processed the month."""
	month = "2019-11"
	_done(cleanup, month, charges=100)
	_done(cleanup, month, day=12, charges=150, extra=300, reason="Out of Station")
	_done(cleanup, month, technician=OTHER_TECH, charges=999, extra=999, reason="Waiting")

	result = _my_month(cleanup, month)
	payout = result["payout"]

	assert payout["processed"] is False
	assert (payout["visit_count"], payout["visit_charges"]) == (2, 250), payout
	assert (payout["extra_count"], payout["extra_payments"]) == (1, 300), payout
	assert payout["total"] == 550, "another technician's pay leaked in: %s" % payout
	assert "sales_incentive" not in payout and "fixed_incentive" not in payout, (
		"an open month showed incentives the office has not set: %s" % payout
	)


def test_the_month_counts_the_jobs_completed_in_it_by_type(cleanup):
	month = "2019-11"
	_done(cleanup, month)                                   # Technician Assignment For Service
	_done(cleanup, month, day=15)
	_done(cleanup, "2019-10", day=28)                       # the month before

	completed = _my_month(cleanup, month)["completed"]
	assert completed["services"] == 2 and completed["total"] == 2, completed


def test_a_processed_month_shows_the_whole_breakup(cleanup):
	from nhk.api import payouts

	month = "2019-12"
	a = _done(cleanup, month, charges=100)
	b = _done(cleanup, month, charges=150, extra=300, reason="Waiting")
	_only_fixtures_in(month, [a, b])
	office = _office_user()
	try:
		frappe.set_user(office)
		payouts.save_month(month, [{"technician_id": PILOT_TECH, "sales_incentive": 250, "fixed_incentive": 1000}])
		payouts.process_month(month)
		frappe.set_user("Administrator")

		payout = _my_month(cleanup, month)["payout"]
		assert payout["processed"] is True and payout["processed_on"], payout
		expected = {"visit_charges": 250, "extra_payments": 300, "sales_incentive": 250,
					"fixed_incentive": 1000, "total": 1800}
		assert {k: payout[k] for k in expected} == expected, payout
	finally:
		frappe.set_user("Administrator")
		_drop_month(month)


def test_the_dashboard_opens_on_this_month(cleanup):
	result = _my_month(cleanup)
	assert result["month"] == frappe.utils.nowdate()[:7] and result["is_current"], result


def test_open_jobs_leave_out_the_ones_handed_back(cleanup):
	before = _my_month(cleanup)["open_jobs"]
	_visit(cleanup, response="Pending")
	_visit(cleanup, response="Rejected")

	assert _my_month(cleanup)["open_jobs"] == before + 1, "a rejected job was counted as still to do"


def test_there_is_a_card_for_every_visit_type(cleanup):
	from nhk.api.staff import MONTH_CARD_TYPES

	month = "2019-11"
	_done(cleanup, month)
	_done(cleanup, month, day=15)
	cards = {c["type"]: c for c in _my_month(cleanup, month)["by_type"]}

	assert list(cards) == list(MONTH_CARD_TYPES), "not every visit type has a card: %s" % list(cards)
	service = cards["Service"]
	assert (service["completed"], service["total"]) == (2, 2), service
	assert cards["Delivery"]["total"] == 0


def test_open_jobs_count_in_the_month_they_are_scheduled_for(cleanup):
	visit = _visit(cleanup, response="Pending")
	frappe.db.set_value("Technician Visit Entry", visit, "scheduled_datetime", "2019-11-20 10:00:00")

	cards = {c["type"]: c for c in _my_month(cleanup, "2019-11")["by_type"]}
	assert cards["Delivery"]["open"] == 1, cards["Delivery"]
	assert {c["type"]: c for c in _my_month(cleanup, "2019-10")["by_type"]}["Delivery"]["open"] == 0


def test_the_month_adds_up_the_distance_travelled(cleanup):
	month = "2019-11"
	a = _done(cleanup, month)
	b = _done(cleanup, month, day=16)
	frappe.db.set_value("Technician Visit Entry", a, "kilometers", 12, update_modified=False)
	frappe.db.set_value("Technician Visit Entry", b, "kilometers", 8, update_modified=False)
	assert _my_month(cleanup, month)["kilometers"] == 20


def test_the_dashboard_cards_the_profile_and_the_payout_agree(cleanup):
	"""Reported 2026-09-30: the cards said 37 jobs, the profile 39 and the
	payout 38 for the same month. A rejected visit the order closed, and one the
	office closed without the work, now count nowhere."""
	month = "2019-11"
	kept = [_done(cleanup, month, charges=100), _done(cleanup, month, day=16, charges=100)]
	rejected = _done(cleanup, month, day=17, charges=100)
	frappe.db.set_value("Technician Visit Entry", rejected, "technician_response", "Rejected")
	closed = _done(cleanup, month, day=18, charges=100)
	frappe.db.set_value("Technician Visit Entry", closed, "status", "Closed")
	for name in kept + [rejected, closed]:
		frappe.db.set_value("Technician Visit Entry", name, "kilometers", 5, update_modified=False)
	scheduled = _visit(cleanup, response="Pending")
	frappe.db.set_value("Technician Visit Entry", scheduled, "scheduled_datetime", "2019-11-25 10:00:00")
	_only_fixtures_in(month, kept)

	result = _my_month(cleanup, month)
	cards = result["by_type"]
	done = sum(c["completed"] for c in cards)

	assert done == 2, cards
	assert result["completed"]["total"] == done, result["completed"]
	assert result["open_jobs"] == sum(c["open"] for c in cards) == 1, result["open_jobs"]
	assert result["kilometers"] == 10, result["kilometers"]
	assert result["payout"]["visit_count"] == done, result["payout"]


def test_the_payout_history_is_newest_first_and_matches_the_month(cleanup):
	from nhk.api import staff

	_on_duty_once(cleanup)
	frappe.set_user(PILOT_USER)
	try:
		history = staff.my_payout_history(3)
		this_month = staff.my_month()
	finally:
		frappe.set_user("Administrator")

	assert [h["month"] for h in history] == sorted((h["month"] for h in history), reverse=True), history
	assert len(history) == 3 and history[0]["month"] == frappe.utils.nowdate()[:7], history
	assert history[0]["total"] == this_month["payout"]["total"]


def _my_visits(cleanup, **kwargs):
	from nhk.api import staff

	_on_duty_once(cleanup)
	frappe.set_user(PILOT_USER)
	try:
		return staff.my_visits(**kwargs)
	finally:
		frappe.set_user("Administrator")


def test_a_card_opens_exactly_the_jobs_it_counted(cleanup):
	"""The bug reported 2026-10-01: a card counted the month's jobs of a type,
	done and open, but the list it opened showed open jobs of every month."""
	from test_staff_api import _on_duty

	month = "2019-11"
	done_a = _done(cleanup, month)
	done_b = _done(cleanup, month, day=16)
	_done(cleanup, "2019-10", day=5)                        # another month
	open_one = _visit(cleanup, type_="Technician Assignment For Service", response="Pending")
	frappe.db.set_value("Technician Visit Entry", open_one, "scheduled_datetime", "2019-11-22 09:00:00")
	_visit(cleanup, type_="Delivery", response="Pending")   # another type
	_on_duty(cleanup)
	frappe.set_user("Administrator")

	card = {c["type"]: c for c in _my_month(cleanup, month)["by_type"]}["Service"]
	listed = {v.name for v in _my_visits(cleanup, month=month, type="Service")}

	assert listed == {done_a, done_b, open_one}, listed
	assert len(listed) == card["total"], "the list and the card disagree: %s vs %s" % (len(listed), card)


def test_service_and_service_assignment_are_one_card(cleanup):
	"""Decided 2026-10-01: to the technician they are the same kind of job."""
	from test_staff_api import _on_duty

	month = "2019-11"
	assignment = _done(cleanup, month)                       # Technician Assignment For Service
	plain = _visit(cleanup, type_="Service", status="Service Done")
	frappe.db.set_value("Technician Visit Entry", plain, "completed_at", "2019-11-18 12:00:00", update_modified=False)
	_on_duty(cleanup)
	frappe.set_user("Administrator")

	service = {c["type"]: c for c in _my_month(cleanup, month)["by_type"]}["Service"]
	assert service["completed"] == 2, service
	assert {v.name for v in _my_visits(cleanup, month=month, type="Service")} == {assignment, plain}


def test_the_plain_list_is_unchanged(cleanup):
	from test_staff_api import _on_duty

	_on_duty(cleanup)
	frappe.set_user("Administrator")
	assert len(_my_visits(cleanup)) <= 100


def test_off_duty_there_are_no_numbers_and_no_payout(cleanup):
	"""Decided 2026-09-29: off duty the dashboard and profile show nothing."""
	from nhk.api import staff
	from nhk.api.guards import OffDuty, open_duty

	assert not open_duty(PILOT_TECH), "fixture assumption: the pilot starts off duty"
	frappe.set_user(PILOT_USER)
	try:
		for call in (staff.my_month, staff.my_payout_history, staff.my_stats):
			try:
				call()
			except OffDuty:
				continue
			raise AssertionError("%s answered off duty" % call.__name__)
	finally:
		frappe.set_user("Administrator")


def test_only_technicians_have_a_month(cleanup):
	from nhk.api import staff

	try:
		staff.my_month()
	except frappe.PermissionError:
		return
	raise AssertionError("Administrator, not a technician, got a technician's month")


if __name__ == "__main__":
	import harness
	raise SystemExit(harness.run(sys.modules[__name__]))
