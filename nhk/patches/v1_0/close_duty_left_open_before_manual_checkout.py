"""Close duty check-ins left open while duty still expired at midnight.

Until 2026-09-29 a duty started on an earlier day simply stopped counting at
midnight, so nobody closed it: on nhk.local ten were still open, going back to
2026-09-16. From that date duty lasts until the technician checks out
(`nhk.api.guards.open_duty`), and those old ones would suddenly count as
current duty. Each is closed at the end of the day it started -- when the old
rule had already ended it. Duty started today is left alone.
"""

import frappe
from frappe.utils import get_datetime, getdate, today


def execute():
	for row in frappe.get_all(
		"Technician Check In",
		filters={"kind": "Duty", "closed_at": ("is", "not set"), "checked_in_at": ("<", today())},
		fields=["name", "checked_in_at"],
	):
		day_end = get_datetime("%s 23:59:59" % getdate(row.checked_in_at))
		frappe.db.set_value(
			"Technician Check In", row.name,
			{"closed_at": day_end, "close_reason": "Day ended"},
			update_modified=False,
		)
