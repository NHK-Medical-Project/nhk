"""The technician's calendar (`nhk.api.staff.my_calendar`).

Run:  cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_my_calendar.py
"""

import sys
from datetime import timedelta

import frappe

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from test_staff_api import OTHER_TECH, OTHER_USER, PILOT_USER, _as, _on_duty, _visit


def _calendar(start, end):
	from nhk.api import staff

	return staff.my_calendar(str(start), str(end))


def test_every_status_of_mine_on_its_scheduled_day(cleanup):
	today = frappe.utils.getdate()
	open_ = _visit(cleanup)
	done = _visit(cleanup, status="Delivered", age_days=3)
	theirs = _visit(cleanup, technician=OTHER_TECH, user=OTHER_USER)
	rejected = _visit(cleanup, response="Rejected")
	frappe.db.set_value("Technician Visit Entry", open_, "scheduled_datetime", f"{today} 10:00:00")

	_on_duty(cleanup)
	try:
		rows = {r.name: r for r in _calendar(today - timedelta(days=7), today)}
	finally:
		_as("Administrator")
	assert open_ in rows and rows[open_].calendar_date == today, rows.get(open_)
	assert done in rows and rows[done].calendar_date == today - timedelta(days=3), rows.get(done)
	assert rows[done].status == "Delivered", "a finished visit is on the calendar too"
	assert theirs not in rows, "another technician's visit"
	assert rejected not in rows, "a rejected job is the office's"


def test_a_day_outside_the_range_is_not_shown(cleanup):
	today = frappe.utils.getdate()
	later = _visit(cleanup)
	frappe.db.set_value("Technician Visit Entry", later, "scheduled_datetime", f"{today + timedelta(days=5)} 09:00:00")
	_on_duty(cleanup)
	try:
		assert later not in [r.name for r in _calendar(today - timedelta(days=2), today)]
		assert later in [r.name for r in _calendar(today, today + timedelta(days=5))]
	finally:
		_as("Administrator")


def test_off_duty_and_long_ranges_are_refused(cleanup):
	from nhk.api.guards import OffDuty

	today = frappe.utils.getdate()
	_as(PILOT_USER)
	try:
		_calendar(today, today)
	except OffDuty:
		pass
	else:
		raise AssertionError("the calendar answered off duty")
	finally:
		_as("Administrator")

	_on_duty(cleanup)
	try:
		for start, end in ((today, today - timedelta(days=1)), (today, today + timedelta(days=62))):
			try:
				_calendar(start, end)
			except frappe.ValidationError:
				continue
			raise AssertionError("accepted %s .. %s" % (start, end))
	finally:
		_as("Administrator")


if __name__ == "__main__":
	import harness
	raise SystemExit(harness.run(sys.modules[__name__]))
