"""The distance a technician travelled: office to arrival (`nhk.api.distance`).

Run:  cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_distance.py

Nothing here calls Google: `distance._call_routes` is replaced wherever a road
distance is wanted, and `distance._server_key` everywhere else. The office
location, the fallback factor and a customer's saved coordinates are changed by
these tests and put back afterwards (`cleanup.restore`).
"""

import sys
from contextlib import contextmanager

import frappe

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from test_staff_api import _assigned_order, _on_duty, _visit

#: Two points in Bengaluru, MG Road and Whitefield: 13.58 km apart in a
#: straight line (checked independently), so 14 km once rounded.
MG_ROAD = (12.9755, 77.6068)
WHITEFIELD = (12.9855, 77.7317)


def _office_at(cleanup, place, factor=1.0):
	for field in ("office_latitude", "office_longitude", "road_distance_factor"):
		cleanup.restore("Admin Settings", "Admin Settings", field)
	frappe.db.set_single_value("Admin Settings", {
		"office_latitude": place[0], "office_longitude": place[1], "road_distance_factor": factor,
	})


@contextmanager
def _google(answer=None, error=None, key="test-server-key"):
	"""Stand in for Google: `answer` km, or raise `error`; `key=None` means no key set."""
	from nhk.api import distance

	calls = []

	def fake(key_, body):
		calls.append({"key": key_, "body": body})
		if error:
			raise error
		return answer

	originals = distance._server_key, distance._call_routes
	distance._server_key = lambda: key
	distance._call_routes = fake
	try:
		yield calls
	finally:
		distance._server_key, distance._call_routes = originals


def _customer_of(visit):
	return frappe.db.get_value("Technician Visit Entry", visit, "patient_id")


def _customer_at(cleanup, customer, place):
	for field in ("custom_google_map_latitude", "custom_google_map_longitude"):
		cleanup.restore("Customer", customer, field)
	frappe.db.set_value("Customer", customer, {
		"custom_google_map_latitude": str(place[0]) if place else "",
		"custom_google_map_longitude": str(place[1]) if place else "",
	}, update_modified=False)


def _check_in(cleanup, visit, place=WHITEFIELD):
	from nhk.api import staff

	_on_duty(cleanup)
	kwargs = {"latitude": place[0], "longitude": place[1]} if place else {}
	result = staff.check_in(visit, **kwargs)
	cleanup.add("Technician Check In", result["name"])
	return result


# --------------------------------------------------------------------------
# the measurement
# --------------------------------------------------------------------------

def test_the_straight_line_between_two_known_places(cleanup):
	from nhk.api import distance

	km = distance.straight_line_km(MG_ROAD, WHITEFIELD)
	assert 13.5 < km < 13.7, "MG Road to Whitefield came out at %.2f km" % km
	assert distance.straight_line_km(MG_ROAD, MG_ROAD) == 0


def test_the_road_distance_is_used_when_google_answers(cleanup):
	from nhk.api import distance

	_office_at(cleanup, MG_ROAD)
	with _google(answer=18.4) as calls:
		measured = distance.measure(*WHITEFIELD)

	assert measured == {"km": 18, "method": "Road (Google)", "straight_line_km": 13.6}, measured
	assert calls and calls[0]["key"] == "test-server-key"


def test_without_a_key_the_straight_line_times_the_factor_stands_in(cleanup):
	from nhk.api import distance

	_office_at(cleanup, MG_ROAD, factor=1.3)
	with _google(answer=99, key=None) as calls:
		measured = distance.measure(*WHITEFIELD)

	assert not calls, "Google was called with no key set"
	# 13.58 x 1.3 = 17.65
	assert (measured["km"], measured["method"]) == (18, "Straight line x factor"), measured


def test_when_google_fails_check_in_falls_back_and_the_failure_is_logged(cleanup):
	from nhk.api import distance

	_office_at(cleanup, MG_ROAD, factor=1.3)
	with _google(error=RuntimeError("Routes API 403: API key not valid")):
		measured = distance.measure(*WHITEFIELD)

	assert (measured["km"], measured["method"]) == (18, "Straight line x factor"), measured
	logged = frappe.get_all("Error Log", filters={"method": "Road distance failed",
												  "error": ("like", "%API key not valid%")}, pluck="name")
	for name in logged:
		cleanup.add("Error Log", name)
	assert logged, "a failed road distance was not logged"


def test_google_finding_no_route_falls_back(cleanup):
	from nhk.api import distance

	_office_at(cleanup, MG_ROAD, factor=1.3)
	with _google(answer=None):
		assert distance.measure(*WHITEFIELD)["method"] == "Straight line x factor"


def test_the_request_asks_google_for_distance_only_in_the_cheapest_tier(cleanup):
	from nhk.api import distance

	body = distance.routes_request(MG_ROAD, WHITEFIELD, "TWO_WHEELER")
	assert body["origin"]["location"]["latLng"] == {"latitude": MG_ROAD[0], "longitude": MG_ROAD[1]}
	assert body["destination"]["location"]["latLng"] == {"latitude": WHITEFIELD[0], "longitude": WHITEFIELD[1]}
	assert body["travelMode"] == "TWO_WHEELER"
	assert body["routingPreference"] == "TRAFFIC_UNAWARE", "traffic-aware routing is billed at a higher tier"
	assert distance.routes_request(MG_ROAD, WHITEFIELD, None)["travelMode"] == "DRIVE"


def test_distances_are_whole_km_and_at_least_one(cleanup):
	from nhk.api import distance

	_office_at(cleanup, MG_ROAD)
	with _google(key=None):
		assert distance.from_office(*WHITEFIELD) == 14
		# Next door still pays the first slab.
		assert distance.from_office(MG_ROAD[0] + 0.0005, MG_ROAD[1]) == 1


def test_nothing_is_calculated_without_an_office_location(cleanup):
	from nhk.api import distance

	_office_at(cleanup, (0, 0))
	with _google(answer=18.4) as calls:
		assert distance.office_location() is None
		assert distance.measure(*WHITEFIELD) is None
	assert not calls, "Google was asked about a trip with no starting point"


# --------------------------------------------------------------------------
# at check-in
# --------------------------------------------------------------------------

def test_checking_in_records_the_road_distance_from_the_office(cleanup):
	_office_at(cleanup, MG_ROAD)
	visit = _visit(cleanup)
	with _google(answer=18.4):
		checkin = _check_in(cleanup, visit)
	frappe.set_user("Administrator")

	assert (checkin["calculated_kilometers"], checkin["distance_source"], checkin["distance_method"]) == (
		18, "Check-in GPS", "Road (Google)"), checkin
	row = frappe.db.get_value("Technician Visit Entry", visit,
							  ["calculated_kilometers", "distance_source", "distance_method", "straight_line_kilometers"],
							  as_dict=True)
	assert (row.calculated_kilometers, row.distance_method, row.straight_line_kilometers) == (18, "Road (Google)", 13.6), row


def test_a_check_in_without_gps_falls_back_to_the_customers_location(cleanup):
	_office_at(cleanup, MG_ROAD)
	visit = _visit(cleanup)
	_customer_at(cleanup, _customer_of(visit), WHITEFIELD)
	with _google(key=None):
		checkin = _check_in(cleanup, visit, place=None)
	frappe.set_user("Administrator")

	assert (checkin["calculated_kilometers"], checkin["distance_source"]) == (14, "Customer location"), checkin


def test_with_neither_place_known_nothing_is_filled_in(cleanup):
	_office_at(cleanup, MG_ROAD)
	visit = _visit(cleanup)
	_customer_at(cleanup, _customer_of(visit), None)
	with _google(answer=18.4):
		checkin = _check_in(cleanup, visit, place=None)
	frappe.set_user("Administrator")

	assert checkin["calculated_kilometers"] is None and checkin["distance_method"] is None, checkin


def test_the_job_carries_the_distance_for_the_app_to_pre_fill(cleanup):
	from nhk.api import staff

	_office_at(cleanup, MG_ROAD)
	visit = _visit(cleanup)
	with _google(answer=18.4):
		_check_in(cleanup, visit)
	job = staff.job(visit)
	frappe.set_user("Administrator")

	assert (job["visit"]["calculated_kilometers"], job["visit"]["distance_method"]) == (18, "Road (Google)"), job["visit"]


def test_undoing_the_arrival_forgets_its_distance(cleanup):
	from nhk.api import staff

	_office_at(cleanup, MG_ROAD)
	visit = _visit(cleanup)
	with _google(answer=18.4):
		checkin = _check_in(cleanup, visit)
	staff.undo_check_in(checkin["name"])
	frappe.set_user("Administrator")

	row = frappe.db.get_value("Technician Visit Entry", visit,
							  ["calculated_kilometers", "distance_source", "distance_method", "straight_line_kilometers"],
							  as_dict=True)
	assert not any(row.values()), row


def test_the_technician_can_still_enter_a_different_distance(cleanup):
	"""Decided 2026-09-30: pre-filled, editable; the calculated one is kept.

	A service visit, so completing it does not move stock -- a delivery on an
	arbitrary snapshot order is refused with "Item Is Not Reserved"."""
	from nhk.api import staff

	_office_at(cleanup, MG_ROAD)
	so = _assigned_order(cleanup, "Service")
	visit = _visit(cleanup, type_="Technician Assignment For Service", sales_order=so)
	with _google(answer=18.4):
		_check_in(cleanup, visit)
	staff.complete_job(visit, kilometers=22)
	frappe.set_user("Administrator")

	row = frappe.db.get_value("Technician Visit Entry", visit, ["kilometers", "calculated_kilometers"], as_dict=True)
	assert (row.kilometers, row.calculated_kilometers) == (22, 18), row


if __name__ == "__main__":
	import harness
	raise SystemExit(harness.run(sys.modules[__name__]))
