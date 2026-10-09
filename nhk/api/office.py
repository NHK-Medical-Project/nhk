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
GROUPS = ("Pending", "Accepted", "Rejected", "Completed", "Active SO", "Ready for Pickup SO")

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

	shown.extend(_active_and_pickup_orders())

	position = {group: i for i, group in enumerate(GROUPS)}
	shown.sort(key=lambda r: (position.get(r["group"], 99), str(r.get("scheduled_datetime") or r.get("creation") or ""), r.get("name") or ""))
	counts = {group: sum(1 for r in shown if r["group"] == group) for group in GROUPS}
	total_visits = sum(1 for r in shown if r["group"] in ("Pending", "Accepted", "Rejected", "Completed"))
	return {"date": str(day), "counts": {"Total": total_visits, **counts}, "rows": shown}


def _active_and_pickup_orders():
	"""Active and Ready for Pickup rental Sales Orders for the workspace block."""
	sos = frappe.db.sql("""
		select so.name, so.customer, so.customer_name, so.status, so.delivery_date, so.pickup_date,
		       so.custom_technician_id_pickup, so.territory, so.reason_for_payment_pending,
		       so.payment_status, so.contact_mobile, so.customer_mobile_no,
		       group_concat(distinct soi.item_code separator ', ') as item_code,
		       group_concat(distinct soi.item_name separator ', ') as item_name
		from `tabSales Order` so
		left join `tabSales Order Item` soi on soi.parent = so.name
		where so.status in ('Active', 'Ready for Pickup') and so.docstatus = 1
		group by so.name
		order by so.modified desc
	""", as_dict=True)

	if not sos:
		return []

	so_names = [s.name for s in sos]
	visits = frappe.db.sql("""
		select name, sales_order_id, technician_id, technician_name, technician_mobile_no, status
		from `tabTechnician Visit Entry`
		where sales_order_id in %(so_names)s and type = 'Pickup'
		order by creation desc
	""", {"so_names": so_names}, as_dict=True)
	pickup_visits = {}
	for v in visits:
		if v.sales_order_id not in pickup_visits:
			pickup_visits[v.sales_order_id] = v

	rows = []
	for so in sos:
		v = pickup_visits.get(so.name)
		is_active = so.status == "Active"
		group = "Active SO" if is_active else "Ready for Pickup SO"
		row = {
			"name": v.name if v else so.name,
			"group": group,
			"sales_order_id": so.name,
			"customer_name": so.customer_name,
			"patient_name": so.customer_name,
			"customer": so.customer,
			"area": so.territory or "",
			"item_code": so.item_code or "",
			"item_name": so.item_name or "",
			"technician_name": (v.technician_name if v else (so.custom_technician_id_pickup or "")).strip(),
			"technician_id": (v.technician_id if v else (so.custom_technician_id_pickup or "")).strip(),
			"technician_mobile_no": (v.technician_mobile_no if v else "").strip(),
			"customer_mobile_no": so.customer_mobile_no or so.contact_mobile or "",
			"stage": so.status,
			"next_step": "Ready for Pickup" if is_active else "Picked Up",
			"payment_status": so.payment_status or "Paid",
			"reason_for_payment_pending": so.reason_for_payment_pending,
			"payments": [],
			"is_so": True,
		}
		rows.append(row)
	return rows


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
