"""Seed the technician payout slabs on Admin Settings.

Admin Settings is a Single, so its child table cannot travel as a fixture. Without
this patch a fresh site installs the nhk app with an empty
`technician_charges_table`, and `update_technician_charge` silently leaves every
visit's payout at zero.

The patch is idempotent and never overwrites: if the table already has rows, it
leaves them alone. Production keeps whatever Finance has configured there.
"""

import frappe

SLABS = [
	{"category": 'Sleep Study Level 2', "from_distance": 0, "to_distance": 3, "delivery": 0.0, "pickup": 150.0},
	{"category": 'Sleep Study Level 2', "from_distance": 4, "to_distance": 10, "delivery": 0.0, "pickup": 200.0},
	{"category": 'Sleep Study Level 2', "from_distance": 11, "to_distance": 20, "delivery": 150.0, "pickup": 100.0},
	{"category": 'Sleep Study Level 2', "from_distance": 21, "to_distance": 40, "delivery": 200.0, "pickup": 150.0},
	{"category": 'Sleep Study Level 2', "from_distance": 41, "to_distance": 60, "delivery": 300.0, "pickup": 200.0},
	{"category": 'Sleep Study Level 2', "from_distance": 61, "to_distance": 80, "delivery": 400.0, "pickup": 400.0},
	{"category": 'Sleep Study Level 2', "from_distance": 81, "to_distance": 9999, "delivery": 500.0, "pickup": 500.0},
	{"category": 'Sleep Study Split night', "from_distance": 0, "to_distance": 3, "delivery": 0.0, "pickup": 250.0},
	{"category": 'Sleep Study Split night', "from_distance": 4, "to_distance": 20, "delivery": 0.0, "pickup": 300.0},
	{"category": 'Sleep Study Split night', "from_distance": 21, "to_distance": 40, "delivery": 0.0, "pickup": 400.0},
	{"category": 'Sleep Study Level 3', "from_distance": 0, "to_distance": 3, "delivery": 100.0, "pickup": 50.0},
	{"category": 'Sleep Study Level 3', "from_distance": 4, "to_distance": 20, "delivery": 100.0, "pickup": 100.0},
	{"category": 'Sleep Study Level 3', "from_distance": 21, "to_distance": 40, "delivery": 150.0, "pickup": 100.0},
	{"category": 'Sleep Study Level 3', "from_distance": 41, "to_distance": 9999, "delivery": 300.0, "pickup": 200.0},
	{"category": 'Order', "from_distance": 0, "to_distance": 5, "delivery": 100.0, "pickup": 50.0},
	{"category": 'Order', "from_distance": 6, "to_distance": 20, "delivery": 150.0, "pickup": 100.0},
	{"category": 'Order', "from_distance": 21, "to_distance": 40, "delivery": 200.0, "pickup": 150.0},
	{"category": 'Order', "from_distance": 41, "to_distance": 50, "delivery": 300.0, "pickup": 200.0},
	{"category": 'Order', "from_distance": 51, "to_distance": 80, "delivery": 400.0, "pickup": 300.0},
	{"category": 'Order', "from_distance": 81, "to_distance": 9999, "delivery": 500.0, "pickup": 400.0},
	{"category": 'Visit', "from_distance": 0, "to_distance": 5, "delivery": 100.0, "pickup": 50.0},
	{"category": 'Visit', "from_distance": 6, "to_distance": 20, "delivery": 150.0, "pickup": 100.0},
	{"category": 'Visit', "from_distance": 21, "to_distance": 40, "delivery": 200.0, "pickup": 150.0},
	{"category": 'Visit', "from_distance": 41, "to_distance": 50, "delivery": 300.0, "pickup": 200.0},
	{"category": 'Visit', "from_distance": 51, "to_distance": 80, "delivery": 400.0, "pickup": 300.0},
	{"category": 'Visit', "from_distance": 81, "to_distance": 9999, "delivery": 500.0, "pickup": 400.0},
]


def execute():
	settings = frappe.get_single("Admin Settings")

	if settings.technician_charges_table:
		# Already configured on this site — never clobber live payout rates.
		return

	for slab in SLABS:
		settings.append("technician_charges_table", slab)

	settings.save(ignore_permissions=True)
