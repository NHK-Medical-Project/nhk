"""Push notifications on assignment (`nhk.api.notify`), the devices behind them
on NHK User (`nhk.api.devices`), and the office alert when the technician
answers.

Run:  cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_notify.py

Nothing here reaches Firebase: `notify._send_one` and `notify._office_alert`
are replaced for every test that lets something through, and the harness
mutes both hooks otherwise.
"""

import sys
import uuid

import frappe

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from test_staff_api import OTHER_TECH, OTHER_USER, PILOT_TECH, PILOT_USER, _visit


def _token():
	"""As long as a real Firebase token (about 160 characters).

	Short fakes hid a real failure once: a real 142-character token overflowed a
	140-character name column while every 43-character test token fitted.
	"""
	return ("test-token-" + uuid.uuid4().hex * 5)[:160]


def _register(cleanup, user, token=None, platform="Android"):
	from nhk.api import devices

	frappe.set_user(user)
	try:
		result = devices.register_device(token or _token(), platform=platform, device_name="Test phone")
	finally:
		frappe.set_user("Administrator")
	cleanup.add_row("NHK User Device", result["name"])
	return frappe.db.get_value("NHK User Device", result["name"], "token")


class _Captured:
	"""Unmute the hooks, replace both senders, and collect what would have gone out."""

	def __init__(self):
		self.sent = []
		self.office = []

	def __enter__(self):
		from nhk.api import notify

		self._send, self._alert = notify._send_one, notify._office_alert
		notify._send_one = lambda **kwargs: self.sent.append(kwargs)
		notify._office_alert = lambda to, subject, visit, response, reason: self.office.append(
			{"to": to, "subject": subject, "visit": visit.name, "response": response, "reason": reason}
		)
		frappe.flags.nhk_mute_notifications = False
		return self

	def __exit__(self, *exc):
		from nhk.api import notify

		notify._send_one, notify._office_alert = self._send, self._alert
		frappe.flags.nhk_mute_notifications = True
		return False

	def to(self, user):
		return [s for s in self.sent if s["user"] == user]


# --------------------------------------------------------------------------
# devices, on NHK User
# --------------------------------------------------------------------------

def test_a_device_is_stored_on_the_users_nhk_user(cleanup):
	from nhk.api import devices

	token = _register(cleanup, PILOT_USER)
	row = frappe.db.get_value("NHK User Device", {"token": token}, ["parent", "parenttype", "parentfield"], as_dict=True)
	assert (row.parenttype, row.parentfield) == ("NHK User", "devices"), row
	assert row.parent == devices.nhk_user_of(PILOT_USER), row


def test_registering_never_saves_the_nhk_user(cleanup):
	"""Saving a submitted NHK User resets the login's password to the plain-text
	one on the record, rebuilds roles and logs the password. Registering a phone
	must not come near it."""
	from nhk.nhk.doctype.nhk_user.nhk_user import NHKUser

	nhk_user = frappe.db.get_value("NHK User", PILOT_USER, "name")
	modified = frappe.db.get_value("NHK User", nhk_user, "modified")
	original = NHKUser.before_update_after_submit

	def tripwire(self):
		raise AssertionError("registering a device saved the NHK User")

	NHKUser.before_update_after_submit = tripwire
	try:
		_register(cleanup, PILOT_USER)
	finally:
		NHKUser.before_update_after_submit = original

	assert frappe.db.get_value("NHK User", nhk_user, "modified") == modified, "the NHK User was touched"


def test_registering_is_idempotent_and_refreshes_last_seen(cleanup):
	from nhk.api import devices

	token = _register(cleanup, PILOT_USER)
	first = frappe.db.get_value("NHK User Device", {"token": token}, ["name", "last_seen"], as_dict=True)
	frappe.db.set_value("NHK User Device", first.name, "enabled", 0, update_modified=False)

	frappe.set_user(PILOT_USER)
	try:
		again = devices.register_device(token, platform="Android")
	finally:
		frappe.set_user("Administrator")

	assert again["name"] == first.name, "registering twice created a second row"
	row = frappe.db.get_value("NHK User Device", first.name, ["enabled", "last_seen"], as_dict=True)
	assert row.enabled and row.last_seen >= first.last_seen


def test_a_token_follows_the_user_who_registered_it_last(cleanup):
	"""A phone handed to someone else must stop getting the first user's jobs."""
	from nhk.api import devices

	token = _register(cleanup, PILOT_USER)
	_register(cleanup, OTHER_USER, token=token)

	rows = frappe.get_all("NHK User Device", filters={"token": token}, pluck="parent")
	assert rows == [devices.nhk_user_of(OTHER_USER)], rows


def test_a_user_can_have_several_devices(cleanup):
	from nhk.api import devices

	a, b = _register(cleanup, PILOT_USER), _register(cleanup, PILOT_USER, platform="iOS")
	assert {a, b} <= set(devices.tokens_for(PILOT_USER))


def test_a_login_with_no_nhk_user_cannot_register(cleanup):
	from nhk.api import devices

	assert not devices.nhk_user_of("Administrator"), "fixture assumption: Administrator has no NHK User"
	try:
		devices.register_device(_token())
	except frappe.ValidationError as exc:
		assert "NHK User" in str(exc), exc
	else:
		raise AssertionError("a device was registered with nowhere to store it")


def test_guests_cannot_register_and_nobody_removes_anothers_device(cleanup):
	from nhk.api import devices

	frappe.set_user("Guest")
	try:
		devices.register_device(_token())
	except frappe.PermissionError:
		pass
	else:
		raise AssertionError("a guest registered a device")
	finally:
		frappe.set_user("Administrator")

	token = _register(cleanup, PILOT_USER)
	frappe.set_user(OTHER_USER)
	try:
		devices.unregister_device(token)
	except frappe.PermissionError:
		pass
	else:
		raise AssertionError("one user removed another's device")
	finally:
		frappe.set_user("Administrator")
	assert frappe.db.exists("NHK User Device", {"token": token})

	frappe.set_user(PILOT_USER)
	try:
		assert devices.unregister_device(token)["removed"]
	finally:
		frappe.set_user("Administrator")
	assert not frappe.db.exists("NHK User Device", {"token": token})


def test_a_disabled_device_gets_nothing(cleanup):
	from nhk.api import devices

	token = _register(cleanup, PILOT_USER)
	frappe.db.set_value("NHK User Device", {"token": token}, "enabled", 0)
	assert token not in devices.tokens_for(PILOT_USER)


# --------------------------------------------------------------------------
# the push to the technician
# --------------------------------------------------------------------------

def test_a_new_assignment_notifies_every_device_of_the_technician_after_commit(cleanup):
	phone, tablet = _register(cleanup, PILOT_USER), _register(cleanup, PILOT_USER, platform="iOS")

	with _Captured() as captured:
		visit = _visit(cleanup, response="Pending")
		assert not captured.sent, "a notification went out before the assignment was committed"
		frappe.db.commit()

	sent = captured.to(PILOT_USER)
	assert {s["token"] for s in sent} >= {phone, tablet}, "not every device was notified: %s" % sent
	for s in sent:
		assert s["visit_name"] == visit and s["data"]["visit_id"] == visit, s


def test_the_notification_says_when_who_where_and_what(cleanup):
	"""Decided 2026-09-29: enough to accept or reject from the notification."""
	_register(cleanup, PILOT_USER)

	with _Captured() as captured:
		visit = _visit(cleanup, response="Pending")
		frappe.db.set_value("Technician Visit Entry", visit, {
			"patient_name": "Asha Rao",
			"scheduled_datetime": "2026-10-02 10:30:00",
			"slot": "Morning",
		})
		frappe.db.commit()

	s = captured.to(PILOT_USER)[0]
	text = "%s\n%s" % (s["title"], s["body"])
	assert "Asha Rao" in text, text
	assert "02 Oct" in text and "Morning" in text, "the schedule is missing: %s" % text
	assert "Address:" in text and "Item:" in text, text
	assert s["data"]["event"] == "assigned" and s["data"]["customer"] == "Asha Rao", s["data"]
	assert all(isinstance(v, str) for v in s["data"].values()), "FCM data values must all be strings"


def test_the_order_fills_in_what_the_visit_does_not_say(cleanup):
	"""Almost no visit has its own schedule or address; the order's delivery
	date and first item stand in."""
	from nhk.api import notify

	visit = _visit(cleanup, response="Pending")
	so = frappe.db.get_value("Technician Visit Entry", visit, "sales_order_id")
	frappe.db.set_value("Technician Visit Entry", visit, {"scheduled_datetime": None, "item_code": None})

	title, body, data = notify.assignment_message(visit)
	if frappe.db.get_value("Sales Order", so, "delivery_date"):
		assert "due" in title, title
	first_item = frappe.get_all("Sales Order Item", filters={"parent": so}, pluck="item_name", order_by="idx")[:1]
	if first_item:
		assert first_item[0] in data["item"], data["item"]


def test_a_rolled_back_assignment_notifies_nobody(cleanup):
	_register(cleanup, PILOT_USER)
	frappe.db.commit()

	with _Captured() as captured:
		_visit(cleanup, response="Pending")
		frappe.db.rollback()
		frappe.db.commit()

	assert not captured.to(PILOT_USER), "an assignment that never happened was notified"


def test_a_reassignment_notifies_the_new_technician_only(cleanup):
	_register(cleanup, PILOT_USER)
	theirs = _register(cleanup, OTHER_USER)

	visit = _visit(cleanup, response="Pending")   # muted: the first assignment is not under test
	frappe.db.commit()

	with _Captured() as captured:
		doc = frappe.get_doc("Technician Visit Entry", visit)
		doc.technician_id = OTHER_TECH
		doc.save(ignore_permissions=True)
		frappe.db.commit()

	assert [s["token"] for s in captured.to(OTHER_USER)] == [theirs], captured.sent
	assert not captured.to(PILOT_USER), "the previous technician was told as well"


def test_other_saves_notify_nobody(cleanup):
	_register(cleanup, PILOT_USER)
	visit = _visit(cleanup, response="Pending")
	frappe.db.commit()

	with _Captured() as captured:
		doc = frappe.get_doc("Technician Visit Entry", visit)
		doc.notes = "Called the patient"
		doc.kilometers = 12
		doc.save(ignore_permissions=True)
		frappe.db.commit()

	assert not captured.sent, "an ordinary edit sent a notification: %s" % captured.sent


def test_a_technician_with_no_device_is_skipped_quietly(cleanup):
	from nhk.api import devices

	assert not devices.tokens_for(OTHER_USER), "fixture assumption broken: %s already has a device" % OTHER_USER

	with _Captured() as captured:
		_visit(cleanup, technician=OTHER_TECH, user=OTHER_USER, response="Pending")
		frappe.db.commit()

	assert not captured.to(OTHER_USER)


def test_a_failing_send_does_not_fail_the_assignment(cleanup):
	from nhk.api import notify

	_register(cleanup, PILOT_USER)
	original = notify._send_one

	def broken(**kwargs):
		raise RuntimeError("Firebase is down")

	notify._send_one = broken
	frappe.flags.nhk_mute_notifications = False
	try:
		visit = _visit(cleanup, response="Pending")
		frappe.db.commit()
	finally:
		notify._send_one = original
		frappe.flags.nhk_mute_notifications = True

	logged = frappe.get_all("Error Log", filters={"method": "Assignment notification failed",
												  "error": ("like", "%Firebase is down%")}, pluck="name")
	for name in logged:
		cleanup.add("Error Log", name)

	assert frappe.db.exists("Technician Visit Entry", visit), "the assignment was lost with the notification"
	assert logged, "the failed send was not logged"


# --------------------------------------------------------------------------
# answering from the notification, and the office alert
# --------------------------------------------------------------------------

def test_the_visit_remembers_who_assigned_it_and_who_reassigned_it(cleanup):
	visit = _visit(cleanup, response="Pending")   # inserted as Administrator
	assert frappe.db.get_value("Technician Visit Entry", visit, "assigned_by") == "Administrator"

	from test_visits import _office_user

	office = _office_user()
	frappe.set_user(office)
	try:
		doc = frappe.get_doc("Technician Visit Entry", visit)
		doc.technician_id = OTHER_TECH
		doc.save()
	finally:
		frappe.set_user("Administrator")
	assert frappe.db.get_value("Technician Visit Entry", visit, "assigned_by") == office


def test_accepting_off_duty_works_and_tells_whoever_assigned_it(cleanup):
	"""Decided 2026-09-29: Accept on the notification works off duty."""
	from nhk.api import staff
	from nhk.api.guards import open_duty

	visit = _visit(cleanup, response="Pending")
	with _Captured() as captured:
		frappe.set_user(PILOT_USER)
		try:
			assert not open_duty(PILOT_TECH), "fixture assumption: the pilot is off duty"
			result = staff.accept_job(visit)
		finally:
			frappe.set_user("Administrator")
		frappe.db.commit()

	assert result["technician_response"] == "Accepted"
	assert len(captured.office) == 1, captured.office
	alert = captured.office[0]
	assert (alert["to"], alert["visit"], alert["response"]) == ("Administrator", visit, "Accepted"), alert
	assert "accepted" in alert["subject"].lower(), alert["subject"]


def test_rejecting_off_duty_works_and_the_office_hears_why(cleanup):
	from nhk.api import staff

	visit = _visit(cleanup, response="Pending")
	with _Captured() as captured:
		frappe.set_user(PILOT_USER)
		try:
			staff.reject_job(visit, reason="Patient Postponed")
		finally:
			frappe.set_user("Administrator")
		frappe.db.commit()

	alert = captured.office[0]
	assert alert["response"] == "Rejected" and alert["reason"] == "Patient Postponed", alert
	assert "Patient Postponed" in alert["subject"], alert["subject"]


def test_accepting_twice_tells_the_office_once(cleanup):
	from nhk.api import staff

	visit = _visit(cleanup, response="Pending")
	with _Captured() as captured:
		frappe.set_user(PILOT_USER)
		try:
			staff.accept_job(visit)
			staff.accept_job(visit)
		finally:
			frappe.set_user("Administrator")
		frappe.db.commit()

	assert len(captured.office) == 1, captured.office


def test_checking_in_still_needs_duty(cleanup):
	"""Answering moved off duty; arriving did not."""
	from nhk.api import staff

	visit = _visit(cleanup)
	frappe.set_user(PILOT_USER)
	try:
		staff.check_in(visit)
	except frappe.ValidationError:
		pass
	else:
		raise AssertionError("a technician checked in off duty")
	finally:
		frappe.set_user("Administrator")


# --------------------------------------------------------------------------
# the address, however the order holds it (`nhk.api.addresses`)
# --------------------------------------------------------------------------

def _order_with_address(cleanup, delivery=None, linked=False, text=None):
	"""A real order with its three address fields set as asked, put back afterwards."""
	visit = _visit(cleanup, response="Pending")
	so = frappe.db.get_value("Technician Visit Entry", visit, "sales_order_id")
	for field in ("delivery_address", "permanent_address_link", "permanent_address"):
		cleanup.restore("Sales Order", so, field)

	link = None
	if linked:
		customer = frappe.db.get_value("Sales Order", so, "customer")
		link = cleanup.add("Address", frappe.get_doc({
			"doctype": "Address", "address_title": "Test home", "address_type": "Shipping",
			"address_line1": "14 Linked Lane", "city": "Bengaluru", "country": "India",
			# India Compliance refuses an Indian address without a state.
			"state": "Karnataka", "pincode": "560066",
			"links": [{"link_doctype": "Customer", "link_name": customer}],
		}).insert(ignore_permissions=True).name)

	frappe.db.set_value("Sales Order", so, {
		"delivery_address": delivery, "permanent_address_link": link, "permanent_address": text,
	}, update_modified=False)
	return visit, so


MAPS_LINK = "https://maps.app.goo.gl/AbCdEf123"


def test_a_linked_address_reaches_the_job_screen(cleanup):
	"""The bug reported 2026-10-01: the app showed only the free-text address."""
	from nhk.api import staff
	from test_staff_api import _on_duty

	visit, _so = _order_with_address(cleanup, linked=True)
	_on_duty(cleanup)
	job = staff.job(visit)
	frappe.set_user("Administrator")

	assert "14 Linked Lane" in job["order"]["address"], job["order"]["address"]
	assert job["order"]["map_url"], "the job screen got nothing to open in Maps"


def test_both_addresses_show_the_link_and_navigate_by_the_maps_link(cleanup):
	"""User, 2026-10-01: show the linked Address, but open the Google Maps link
	written in the free-text address."""
	from nhk.api import addresses

	_v, so = _order_with_address(cleanup, linked=True, text="Near the temple " + MAPS_LINK)
	where = addresses.for_order(so)
	assert "14 Linked Lane" in where["address"], where
	assert where["map_url"] == MAPS_LINK, where


def test_a_free_text_address_is_shown_without_its_link(cleanup):
	from nhk.api import addresses

	_v, so = _order_with_address(cleanup, text="3 Text Street, Bengaluru " + MAPS_LINK)
	where = addresses.for_order(so)
	assert where["address"] == "3 Text Street, Bengaluru", where
	assert where["map_url"] == MAPS_LINK, where


def test_a_link_only_address_shows_the_next_thing_down(cleanup):
	"""58 orders hold nothing but a Maps link: useless as text, exact for the map."""
	from nhk.api import addresses

	_v, so = _order_with_address(cleanup, delivery="1 Delivery Road", text=MAPS_LINK)
	where = addresses.for_order(so)
	assert where["address"] == "1 Delivery Road" and where["map_url"] == MAPS_LINK, where

	frappe.db.set_value("Sales Order", so, "delivery_address", None, update_modified=False)
	where = addresses.for_order(so, area="Whitefield")
	assert where["address"] == "Whitefield" and where["map_url"] == MAPS_LINK, where


def test_without_a_maps_link_the_map_uses_the_customers_location_then_a_search(cleanup):
	from nhk.api import addresses

	visit, so = _order_with_address(cleanup, text="3 Text Street")
	customer = frappe.db.get_value("Sales Order", so, "customer")
	for field in ("custom_google_map_latitude", "custom_google_map_longitude"):
		cleanup.restore("Customer", customer, field)

	frappe.db.set_value("Customer", customer, {"custom_google_map_latitude": "12.9855",
											   "custom_google_map_longitude": "77.7317"}, update_modified=False)
	assert "12.9855%2C77.7317" in addresses.for_order(so)["map_url"]

	frappe.db.set_value("Customer", customer, {"custom_google_map_latitude": "",
											   "custom_google_map_longitude": ""}, update_modified=False)
	assert "3+Text+Street" in addresses.for_order(so)["map_url"]


def test_the_notification_uses_the_linked_address_too(cleanup):
	from nhk.api import notify

	visit, _so = _order_with_address(cleanup, linked=True, text=MAPS_LINK)
	_title, _body, data = notify.assignment_message(visit)
	assert "14 Linked Lane" in data["address"], data["address"]
	assert "\n" not in data["address"], "the lock-screen address should be one line"
	assert data["map_url"] == MAPS_LINK


if __name__ == "__main__":
	import harness
	raise SystemExit(harness.run(sys.modules[__name__]))
