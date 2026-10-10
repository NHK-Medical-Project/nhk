"""The office's day of technician visits: the NHK Technician workspace block.

One call answers, for one day (today by default), every visit and where it
stands -- in the words the office already sees on the visit form and the Sales
Order's visit table:

* **Pending** -- the technician has not accepted it yet. Chase or reassign.
* **Accepted** -- on its way. Reschedule or reassign if plans change.
* **Rejected** -- the technician handed it back. Reassign it.
* **Completed** -- done that day.

A visit belongs to a day as it belongs to a month on the technician's
dashboard (`nhk.api.staff._OPEN_FOR_MONTH` / `_DONE_IN_MONTH`): an open one on
the day it is scheduled for, or was given out on if never scheduled; a
completed one on the day it was completed. So the office and the technician
count the same visits (decided 2026-09-30).

Each row carries `stage` and `next_step` from `visits._describe` -- the Sales
Order's sentences -- and the patient's payment: **Payment Status** on the order
(Pending or Paid, as the app shows it) with its Reason For Payment Pending, and
the **Mode Of Payment** of whatever the technician collected on that visit.

Gated on `share` on Technician Visit Entry, the permission that already means
"the office" (`nhk.api.assignment.reassign_visit`).
"""

import frappe
from frappe.utils import add_days, flt, getdate, today

from nhk.api.staff import _DONE_IN_MONTH, _OPEN_FOR_MONTH
from nhk.api.visits import _describe

#: The block's tabs, after Total.
GROUPS = ("Pending", "Accepted", "Rejected", "Completed")

#: Orders past these are finished; a visit still open on one is left over, not
#: work. NHK's own end states first: the device is back at the office, or the
#: rental carried on in its renewal order. 339 of the 432 open visits on
#: nhk.local (2026-09-30) sat on one of these two.
FINISHED_ORDER_STATUSES = (
	"Submitted to Office", "RENEWED", "Rental SO Completed", "SO Completed",
	"Completed", "Closed", "Cancelled",
)

_FIELDS = """name, type, status, technician_id, technician_name, technician_mobile_no,
	sales_order_id, patient_name, area, item_code, scheduled_datetime, slot, started_at,
	completed_at, technician_update_datetime, payout_month,
	ifnull(nullif(technician_response, ''), 'Pending') as technician_response,
	technician_response_at, rejection_reason, creation"""

#: Open and handed back on the day: `_OPEN_FOR_MONTH`, for the rejected ones.
_REJECTED_FOR_DAY = """status = 'Assigned'
	and technician_response = 'Rejected'
	and coalesce(scheduled_datetime, creation) >= %(start)s
	and coalesce(scheduled_datetime, creation) < %(end)s"""


@frappe.whitelist()
def technician_visits(date=None):
	"""Every visit of one day, by where it stands, with the patient's payment."""
	frappe.has_permission("Technician Visit Entry", "share", throw=True)

	day = getdate(date or today())
	window = {"start": day, "end": add_days(day, 1)}
	rows = []
	for group, where in (("open", _OPEN_FOR_MONTH), ("Rejected", _REJECTED_FOR_DAY), ("Completed", _DONE_IN_MONTH)):
		for row in frappe.db.sql(
			f"select {_FIELDS} from `tabTechnician Visit Entry` where {where}", window, as_dict=True
		):
			row["group"] = row.technician_response if group == "open" else group
			rows.append(row)

	orders = _orders({r.sales_order_id for r in rows if r.sales_order_id})
	collected = _collected([r.name for r in rows])
	shown = []
	for row in rows:
		order = orders.get(row.sales_order_id) or {}
		if row.group != "Completed" and order.get("status") in FINISHED_ORDER_STATUSES:
			continue
		row["technician_name"] = (row.technician_name or "").strip()
		row["customer_name"] = (order.get("customer_name") or "").strip()
		row["stage"], row["next_step"] = _describe(row)
		row["payment_status"] = order.get("payment_status")
		row["reason_for_payment_pending"] = order.get("reason_for_payment_pending")
		row["payments"] = collected.get(row.name, [])
		shown.append(row)

	position = {group: i for i, group in enumerate(GROUPS)}
	shown.sort(key=lambda r: (position[r["group"]], r.scheduled_datetime or r.creation, r.name))
	counts = {group: sum(1 for r in shown if r["group"] == group) for group in GROUPS}
	return {"date": str(day), "counts": {"Total": len(shown), **counts}, "rows": shown}


def _orders(names):
	"""Customer, status and the patient's Payment Status for each order.

	Pending or Paid, from `get_sales_order_details` -- the figures the job
	screen and the desk's "Enter Payment Details" use, Draft entries counted
	as paid."""
	from nhk.custom_script import get_sales_order_details

	if not names:
		return {}
	orders = {
		o.name: o for o in frappe.get_all(
			"Sales Order", filters={"name": ("in", list(names))},
			fields=["name", "status", "customer_name", "reason_for_payment_pending"],
		)
	}
	owed = ("Unpaid", "Partially Paid")
	for name, order in orders.items():
		d = get_sales_order_details(name)
		pending = d["rental_payment_status"] in owed or d["security_deposit_payment_status"] in owed
		order["payment_status"] = "Pending" if pending else "Paid"
	return orders


def _collected(visit_names):
	"""What each visit's technician collected: mode, amount, Draft or Submitted."""
	if not visit_names:
		return {}
	status = {0: "Draft", 1: "Submitted"}
	collected = {}
	for visit, mode, amount, docstatus in frappe.db.sql(
		"""select custom_technician_visit_id, mode_of_payment, paid_amount, docstatus
		from `tabPayment Entry` where custom_technician_visit_id in %(v)s and docstatus < 2
		union all
		select custom_technician_visit_entry_id, mode_of__payment, total_debit, docstatus
		from `tabJournal Entry` where custom_technician_visit_entry_id in %(v)s and docstatus < 2""",
		{"v": visit_names},
	):
		collected.setdefault(visit, []).append(
			{"mode_of_payment": mode, "amount": flt(amount), "status": status.get(docstatus, "")}
		)
	return collected


# ---------------------------------------------------------------------------
# sleep study pickups: the Technician Visits block's sleep study tabs
# ---------------------------------------------------------------------------

#: The block's tabs, in the order a sleep study moves through them.
#:
#: * **With Patient** -- delivered, the order `Active`, no pickup arranged yet.
#: * **To Assign** -- the order is `Ready for Pickup` but nobody has the pickup:
#:   the technician left it to the office (`nhk.api.pickup.ready_for_pickup`),
#:   or the pickup technician rejected it.
#: * **Assigned** -- a technician has the pickup and has not done it yet.
PICKUP_GROUPS = ("With Patient", "To Assign", "Assigned")


@frappe.whitelist()
def sleep_study_pickups():
	"""Every sleep study still out with a patient, by where its pickup stands.

	Not limited to a day, unlike `technician_visits`: a study is out for a
	night or two, and the office needs to see all of them until they are back.
	Gated as `technician_visits` is.
	"""
	frappe.has_permission("Technician Visit Entry", "share", throw=True)

	from nhk.api.pickup import DELIVERED_ORDER_STATUS, READY_FOR_PICKUP, SLEEP_STUDY_PREFIX

	# The latest sleep study delivery on each order still out.
	orders = frappe.db.sql(
		"""select so.name as sales_order_id, so.status as order_status, so.customer_name,
			so.pickup_date, d.name as delivery_visit, d.technician_category,
			d.technician_id as delivery_technician_id, d.technician_name as delivery_technician_name,
			d.area, coalesce(d.completed_at, d.technician_update_datetime, d.modified) as delivered_at
		from `tabSales Order` so
		join `tabTechnician Visit Entry` d on d.name = (
			select d2.name from `tabTechnician Visit Entry` d2
			where d2.sales_order_id = so.name and d2.type = 'Delivery'
				and d2.technician_category like %(prefix)s and d2.status != 'Assigned'
			order by d2.creation desc limit 1)
		where so.docstatus = 1 and so.status in %(statuses)s""",
		{"prefix": SLEEP_STUDY_PREFIX + "%", "statuses": (DELIVERED_ORDER_STATUS, READY_FOR_PICKUP)},
		as_dict=True,
	)
	pickups = _open_pickups([o.sales_order_id for o in orders])

	rows = []
	for order in orders:
		pickup = pickups.get(order.sales_order_id)
		if order.order_status == DELIVERED_ORDER_STATUS and not pickup:
			group = "With Patient"
		elif not pickup or pickup.technician_response == "Rejected":
			group = "To Assign"
		else:
			group = "Assigned"
		order["group"] = group
		order["customer_name"] = (order.customer_name or "").strip()
		order["delivery_technician_name"] = (order.delivery_technician_name or "").strip()
		order["pickup"] = pickup
		rows.append(order)

	position = {group: i for i, group in enumerate(PICKUP_GROUPS)}
	rows.sort(key=lambda r: (position[r["group"]], r.delivered_at or "", r.sales_order_id))
	counts = {group: sum(1 for r in rows if r["group"] == group) for group in PICKUP_GROUPS}
	return {"counts": counts, "rows": rows}


def _open_pickups(orders):
	"""The open Pickup visit on each order, the latest if there are several.

	Shaped for `nhk.visit_dialogs`: name, technician, schedule and slot.
	"""
	if not orders:
		return {}
	found = {}
	for row in frappe.db.sql(
		"""select name, sales_order_id, technician_id, technician_name, technician_mobile_no,
			scheduled_datetime, slot, pickup_arranged_by, rejection_reason,
			ifnull(nullif(technician_response, ''), 'Pending') as technician_response
		from `tabTechnician Visit Entry`
		where sales_order_id in %(orders)s and type = 'Pickup' and status = 'Assigned'
		order by creation asc""",
		{"orders": orders}, as_dict=True,
	):
		row["technician_name"] = (row.technician_name or "").strip()
		found[row.sales_order_id] = row
	return found
