"""Where a visit happens: what to show, and what to open in Google Maps.

Rules (user, 2026-10-01):

* **Show** the order's linked Address (`permanent_address_link`) if it has
  one; otherwise its free-text `permanent_address`.
* **Navigate** with the Google Maps link written in the free-text
  `permanent_address` whenever there is one -- even when the linked Address is
  what is shown. 64 of 5,206 free-text addresses carry a Maps link
  (`maps.app.goo.gl`, mostly), and 58 are nothing but the link: exact for the
  map, useless as text. So the link is lifted out of the text shown, and a
  text that was only a link shows the next thing down instead.

Past those two, the order's `delivery_address` and the visit's `area` still
stand in, and the map falls back to the customer's saved coordinates, then to
a search for the address shown.

Both the job screen (`nhk.api.staff.job`) and the assignment notification
(`nhk.api.notify`) read it from here.
"""

import re
from urllib.parse import urlencode

import frappe
from frappe.utils import cstr, flt, strip_html

#: A Google Maps link as the office pastes them: short links (maps.app.goo.gl,
#: goo.gl/maps, g.co/kgs) and full google.com/maps URLs.
MAPS_URL = re.compile(
	r"https?://(?:maps\.app\.goo\.gl|goo\.gl/maps|g\.co|(?:www\.)?google\.[a-z.]+/maps|maps\.google\.[a-z.]+)\S*",
	re.I,
)


def for_order(sales_order, area=None, customer=None):
	"""`{"address": text to show, "map_url": what to open in Maps}`. Either may be ""."""
	row = frappe._dict()
	if sales_order:
		row = frappe.db.get_value(
			"Sales Order", sales_order,
			["permanent_address_link", "permanent_address", "delivery_address", "customer"],
			as_dict=True,
		) or frappe._dict()

	free_text = cstr(row.permanent_address)
	link = MAPS_URL.search(free_text)
	shown = next(
		(text for text in (
			_plain(_linked(row.permanent_address_link)),
			_plain(MAPS_URL.sub("", free_text)),
			_plain(row.delivery_address),
			_plain(area),
		) if text),
		"",
	)

	map_url = link.group(0).rstrip(".,)") if link else _coordinates_url(customer or row.customer)
	if not map_url and shown:
		map_url = "https://www.google.com/maps/search/?" + urlencode({"api": 1, "query": shown.replace("\n", ", ")})
	return {"address": shown, "map_url": map_url or ""}


def _coordinates_url(customer):
	if not customer:
		return None
	lat, lng = frappe.db.get_value(
		"Customer", customer, ["custom_google_map_latitude", "custom_google_map_longitude"]
	) or (None, None)
	if not (flt(lat) or flt(lng)):
		return None
	return "https://www.google.com/maps/search/?" + urlencode({"api": 1, "query": "%s,%s" % (flt(lat), flt(lng))})


def _linked(name):
	"""An Address record, formatted the way ERPNext prints it, or None.

	Without the permission check: `get_address_display` checks that the session
	user may read the Address, and `NHK Technician` may not, so the technician
	was shown no address at all. Callers have already established the visit is
	theirs (`staff.job` via `owned_visit`), and the free-text address reaches
	them the same way.
	"""
	if not name:
		return None
	from frappe.contacts.doctype.address.address import render_address

	try:
		return render_address(name, check_permissions=False)
	except Exception:
		# A deleted or unreadable Address must not cost the technician the job screen.
		return None


def _plain(text):
	"""HTML line breaks become newlines; other tags and blank lines go."""
	text = re.sub(r"<br\s*/?>", "\n", cstr(text), flags=re.I)
	lines = [re.sub(r"[ \t]+", " ", l).strip(" ,") for l in strip_html(text).splitlines()]
	return "\n".join(l for l in lines if l)
