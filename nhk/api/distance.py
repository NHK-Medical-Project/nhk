"""How far a technician travelled for a visit: office to where they arrived.

Decided 2026-09-30: every distance is measured from the office, whose latitude
and longitude are set in Admin Settings, one way, to where the technician
arrived. The app pre-fills it and the technician may change it; what was
calculated stays on the visit as `calculated_kilometers`, beside what they
entered in `kilometers`, for the office to compare.

**By road** (decided 2026-09-30, after the straight line proved 20-40% short):
Google's Routes API gives the driving distance from the office to the arrival
point. It needs a server-side key in Admin Settings. Without one, or when Google
cannot be reached in time, the straight line multiplied by Admin Settings'
factor stands in, so check-in never waits on Google. Which of the two was used
is recorded as `distance_method`, and the straight line itself as
`straight_line_kilometers`.

The route is the one Google would take, not the one the technician took; that
is the point -- it matches the rule "from the office" and cannot be inflated.

Where they arrived is the phone's GPS at check-in. A check-in without a fix
falls back to the customer's saved location; with neither there is nothing to
measure and the technician types the distance, as before.
"""

import math

import frappe
import requests
from frappe.utils import flt
from frappe.utils.password import get_decrypted_password

EARTH_RADIUS_KM = 6371.0088

SOURCE_CHECKIN = "Check-in GPS"
SOURCE_CUSTOMER = "Customer location"

METHOD_ROAD = "Road (Google)"
METHOD_FACTOR = "Straight line x factor"

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

#: Check-in waits this long for Google at most, then falls back.
ROUTES_TIMEOUT_SECONDS = 6

DEFAULT_ROAD_FACTOR = 1.3


def office_location():
	"""(latitude, longitude) of the office, or None while Admin Settings has none."""
	lat = flt(frappe.db.get_single_value("Admin Settings", "office_latitude"))
	lng = flt(frappe.db.get_single_value("Admin Settings", "office_longitude"))
	return (lat, lng) if _is_place(lat, lng) else None


def _is_place(lat, lng):
	"""A real coordinate pair. 0, 0 is how an empty Float column reads, not a
	place anyone drives to."""
	return bool(lat or lng) and -90 <= lat <= 90 and -180 <= lng <= 180


def straight_line_km(a, b):
	"""Great-circle distance in km between two (latitude, longitude) pairs."""
	lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
	h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
	return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def measure(lat, lng):
	"""The distance from the office to (lat, lng), or None if either end is unknown.

	Returns `{"km", "method", "straight_line_km"}`. `km` is whole, at least 1:
	the pay slabs are whole kilometres and the completion refuses anything else
	(`nhk.api.visits._validated_distance`).
	"""
	office = office_location()
	lat, lng = flt(lat), flt(lng)
	if not office or not _is_place(lat, lng):
		return None

	straight = straight_line_km(office, (lat, lng))
	road = _road_km(office, (lat, lng))
	if road is None:
		factor = flt(frappe.db.get_single_value("Admin Settings", "road_distance_factor")) or DEFAULT_ROAD_FACTOR
		road, method = straight * factor, METHOD_FACTOR
	else:
		method = METHOD_ROAD

	return {"km": max(1, int(round(road))), "method": method, "straight_line_km": round(straight, 1)}


def from_office(lat, lng):
	"""Whole km from the office to (lat, lng); None if either end is unknown."""
	measured = measure(lat, lng)
	return measured["km"] if measured else None


def for_visit(visit):
	"""The distance for a visit, from its check-in point or its customer, or None.

	Returns `measure()`'s dict plus `source`: where the far end came from.
	"""
	measured = measure(visit.get("start_latitude"), visit.get("start_longitude"))
	if measured:
		return {**measured, "source": SOURCE_CHECKIN}

	customer = visit.get("patient_id")
	if customer:
		lat, lng = frappe.db.get_value(
			"Customer", customer, ["custom_google_map_latitude", "custom_google_map_longitude"]
		) or (None, None)
		measured = measure(lat, lng)
		if measured:
			return {**measured, "source": SOURCE_CUSTOMER}
	return None


# ---------------------------------------------------------------------------
# Google Routes API
# ---------------------------------------------------------------------------


def _server_key():
	return get_decrypted_password(
		"Admin Settings", "Admin Settings", "google_maps_server_key", raise_exception=False
	)


def routes_request(origin, destination, travel_mode):
	"""The Routes API body for one office-to-arrival distance.

	`TRAFFIC_UNAWARE` and a field mask of `routes.distanceMeters` alone keep the
	call in Google's cheapest (Essentials) tier: distance is all that is used.
	"""
	point = lambda p: {"location": {"latLng": {"latitude": p[0], "longitude": p[1]}}}
	return {
		"origin": point(origin),
		"destination": point(destination),
		"travelMode": travel_mode or "DRIVE",
		"routingPreference": "TRAFFIC_UNAWARE",
		"units": "METRIC",
	}


def _road_km(origin, destination):
	"""Road km from Google, or None -- no key, no route, or no answer in time.

	Never raises: check-in must go through whatever Google does. Failures are
	logged without the key, which travels in a header rather than the URL.
	"""
	key = _server_key()
	if not key:
		return None
	try:
		return _call_routes(key, routes_request(
			origin, destination, frappe.db.get_single_value("Admin Settings", "road_travel_mode")
		))
	except Exception:
		frappe.log_error(title="Road distance failed", message=frappe.get_traceback())
		return None


def _call_routes(key, body):
	"""POST to the Routes API; km of the first route, or None if there is none.
	The one place this module reaches Google; tests replace it."""
	response = requests.post(
		ROUTES_URL,
		json=body,
		headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": "routes.distanceMeters"},
		timeout=ROUTES_TIMEOUT_SECONDS,
	)
	if response.status_code != 200:
		message = (response.json().get("error") or {}).get("message") if response.content else ""
		raise RuntimeError("Routes API %s: %s" % (response.status_code, message))
	routes = response.json().get("routes") or []
	meters = routes[0].get("distanceMeters") if routes else None
	return meters / 1000 if meters else None
