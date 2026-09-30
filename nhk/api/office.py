"""The office's view of open technician visits: the NHK Technician workspace block.

One call answers the three things the office acts on, in the words it already
sees on the visit form and the Sales Order's visit table:

* **Rejected** -- the technician handed the job back. Reassign it.
* **Pending** -- the technician has not accepted it yet. Chase or reassign.
* **Accepted** -- on its way. Reschedule or reassign if plans change.

`Technician Response` values, not new names (decided 2026-09-30). Each row
carries `stage` and `next_step` from `visits._describe`, the same sentences the
Sales Order shows. The block also lists the technicians, on or off duty and
how many open jobs each holds, so the office can see who to give a job to.

Gated on `share` on Technician Visit Entry, the permission that already means
"the office" (`nhk.api.assignment.reassign_visit`).
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, now_datetime

from nhk.api.guards import OPEN_STATUSES, open_duty
from nhk.api.visits import SLOTS, _describe

RESPONSES = ("Rejected", "Pending", "Accepted")

#: Orders past these are finished; a visit still open on one is left over, not work.
FINISHED_ORDER_STATUSES = ("Completed", "Closed", "Cancelled")

#: Rows sent per response. More than this is a cleanup job, not a queue; the
#: block says so and the search narrows it.
MAX_ROWS = 300


@frappe.whitelist()
def technician_visits(days=30):
	"""Open visits by technician response, and the technicians to give them to.

	`days` keeps old visits out: only visits scheduled -- or, when never
	scheduled, created -- in the last `days` days, or later. `0` shows every
	open visit. Rejected ones are always shown: each needs reassigning, however old.
	"""
	frappe.has_permission("Technician Visit Entry", "share", throw=True)

	days = cint(days)
	since = add_days(now_datetime(), -days) if days > 0 else None
	now = now_datetime()
	counts, held, rows, limited = {}, {}, [], False
	for response in RESPONSES:
		found = _open_visits(response, since)
		counts[response] = sum(found["by_technician"].values())
		for technician_id, n in found["by_technician"].items():
			held.setdefault(technician_id, {})[response] = n
		limited = limited or counts[response] > len(found["rows"])
		for row in found["rows"]:
			row["technician_name"] = (row.technician_name or "").strip()
			row["stage"], row["next_step"] = _describe(row)
			row["past_scheduled"] = bool(row.scheduled_datetime and row.scheduled_datetime < now)
			rows.append(row)

	return {
		"counts": counts,
		"rows": rows,
		"technicians": _technicians(held),
		"slots": list(SLOTS),
		"days": days,
		"limited": limited,
	}


def _open_visits(response, since):
	"""One response's open visits, oldest scheduled first, and how many each
	technician holds. Rejected ones ignore `since`: each needs reassigning,
	however old."""
	where = """v.status in %(open)s
		and ifnull(nullif(v.technician_response, ''), 'Pending') = %(response)s
		and ifnull(so.status, '') not in %(finished)s"""
	if since and response != "Rejected":
		where += " and coalesce(v.scheduled_datetime, v.creation) >= %(since)s"
	values = {"open": OPEN_STATUSES, "finished": FINISHED_ORDER_STATUSES,
			  "response": response, "since": since}
	source = """`tabTechnician Visit Entry` v
		left join `tabSales Order` so on so.name = v.sales_order_id"""

	by_technician = dict(frappe.db.sql(
		f"select v.technician_id, count(*) from {source} where {where} group by v.technician_id", values
	))
	rows = frappe.db.sql(
		f"""
		select v.name, v.type, v.status, v.technician_id, v.technician_name,
			v.technician_mobile_no, v.sales_order_id, so.customer_name, v.patient_name,
			v.area, v.item_code, v.scheduled_datetime, v.slot, v.started_at,
			%(response)s as technician_response, v.technician_response_at,
			v.rejection_reason, v.creation
		from {source} where {where}
		order by coalesce(v.scheduled_datetime, v.creation), v.name
		limit {MAX_ROWS}
		""",
		values,
		as_dict=True,
	)
	return {"by_technician": by_technician, "rows": rows}


def _technicians(held):
	"""Every technician: on duty or not, and their Pending and Accepted visits --
	the same visits the tabs count, so a technician's numbers match the rows
	shown when the office picks them."""
	people = frappe.get_all(
		"Technician Details", fields=["name", "name1", "mobile_number"], order_by="name1"
	)
	for person in people:
		jobs = held.get(person.name, {})
		person["name1"] = (person.name1 or "").strip()
		person["on_duty"] = bool(open_duty(person.name))
		person["pending"] = jobs.get("Pending", 0)
		person["accepted"] = jobs.get("Accepted", 0)
	# On duty first; among them, the least loaded first.
	people.sort(key=lambda p: (not p.on_duty, p.pending + p.accepted, p.name1 or ""))
	return people
