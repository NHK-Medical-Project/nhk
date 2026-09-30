"""Technician pay, one month at a time.

Pay used to be worked out in a spreadsheet at the end of each month: per staff
member, the delivery money, sales incentive, fixed incentive and total. This
builds the same table from the visits themselves:

* **Visits** -- the slab charge of every visit the technician completed in the
  month (`TechnicianVisitEntry.validate` prices it from the distance).
* **Extra** -- the extra payments on those visits: out of station, waiting and
  the like, entered by the technician in the app and correctable by the office.
* **Sales** and **Fixed** -- entered by hand on the month.

Processing the month freezes it: the figures are saved on a `Technician Payout
Month`, and each counted visit is set `Closed` / `Cleared` with `payout_month`
pointing at it, after which its pay cannot change (`guard_payout_lock`). The
money itself is paid outside the system (decided 2026-09-28).

Which visits count, and why:

* completed (`Delivered`, `Picked up`, `Installation Done`, `Service Done`) or
  `Incentive Finalize` -- the old per-visit step, still reachable from the visit
  form -- and not yet in a processed month;
* **not** `Amount Settled` / `Closed` without a payout month: those were paid by
  the old per-visit payment run, and counting them would pay them twice;
* dated by `completed_at`, falling back to `technician_update_datetime` for
  visits closed before `completed_at` existed. A visit with neither cannot be
  placed in a month; it is counted and reported, never guessed.

Everything here is `NHK Admin` only, checked on the server, and nothing commits
until the request does.
"""

import json
import re

import frappe
from frappe import _
from frappe.utils import add_months, flt, get_datetime, getdate, now_datetime

from nhk.api.visits import COUNTED_STATUSES, PAYOUT_ROLE, _assert_office_may_change

EXTRA_REASONS = ("Out of Station", "Waiting", "Other")

#: The figures a row is built from; Sales and Fixed are the only hand-entered ones.
ROW_FIGURES = ("visit_count", "visit_charges", "extra_count", "extra_payments")


def _assert_payout_admin():
	if PAYOUT_ROLE not in frappe.get_roles():
		frappe.throw(_("Only an NHK Admin can see or change technician pay."), frappe.PermissionError)


def _validated_month(month):
	month = (month or "").strip()
	if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
		frappe.throw(_("Month must be written as YYYY-MM, for example 2026-08."))
	return month


def _bounds(month):
	start = get_datetime(month + "-01")
	return start, get_datetime(add_months(start, 1))


def _saved(month):
	if frappe.db.exists("Technician Payout Month", month):
		return frappe.get_doc("Technician Payout Month", month)
	return None


def _month_visits(month, technician_id=None):
	"""Unsettled completed visits dated inside `month`, oldest first.

	Not rejected ones: a visit the technician turned down is not their work,
	even when the order closed it as done anyway (DELIVERED closes every open
	Delivery visit on a rental). Same rule as the app's month cards, so the pay
	and the job counts agree (decided 2026-09-30).
	"""
	start, end = _bounds(month)
	conditions = ""
	values = {"start": start, "end": end, "statuses": COUNTED_STATUSES}
	if technician_id:
		conditions = "and technician_id = %(technician_id)s"
		values["technician_id"] = technician_id

	return frappe.db.sql(
		f"""
		select name, technician_id, technician_name, type, status, sales_order_id,
			patient_name, kilometers, charges, extra_payment, extra_payment_reason,
			extra_payment_note, coalesce(completed_at, technician_update_datetime) as completed_on
		from `tabTechnician Visit Entry`
		where status in %(statuses)s
			and ifnull(payout_month, '') = ''
			and ifnull(technician_response, '') != 'Rejected'
			and coalesce(completed_at, technician_update_datetime) >= %(start)s
			and coalesce(completed_at, technician_update_datetime) < %(end)s
			{conditions}
		order by completed_on, name
		""",
		values,
		as_dict=True,
	)


def _undated_count():
	return frappe.db.sql(
		"""
		select count(*) from `tabTechnician Visit Entry`
		where status in %(statuses)s and ifnull(payout_month, '') = ''
			and ifnull(technician_response, '') != 'Rejected'
			and completed_at is null and technician_update_datetime is null
		""",
		{"statuses": COUNTED_STATUSES},
	)[0][0]


def _live_rows(month, saved=None):
	"""Per-technician figures from the visits, with the saved Sales / Fixed kept."""
	rows = {}

	def row_for(technician_id, technician_name=None):
		if technician_id not in rows:
			rows[technician_id] = frappe._dict(
				technician_id=technician_id,
				technician_name=technician_name
				or frappe.db.get_value("Technician Details", technician_id, "name1"),
				visit_count=0, visit_charges=0.0, extra_count=0, extra_payments=0.0,
				sales_incentive=0.0, fixed_incentive=0.0,
			)
		return rows[technician_id]

	for visit in _month_visits(month):
		if not visit.technician_id:
			continue
		row = row_for(visit.technician_id, visit.technician_name)
		row.visit_count += 1
		row.visit_charges += flt(visit.charges)
		if flt(visit.extra_payment):
			row.extra_count += 1
			row.extra_payments += flt(visit.extra_payment)

	for kept in (saved.rows if saved else []):
		row = row_for(kept.technician_id, kept.technician_name)
		row.sales_incentive = flt(kept.sales_incentive)
		row.fixed_incentive = flt(kept.fixed_incentive)

	for row in rows.values():
		row.total = row.visit_charges + row.extra_payments + row.sales_incentive + row.fixed_incentive

	return sorted(rows.values(), key=lambda r: (r.technician_name or r.technician_id or "").lower())


def _summary(month, rows, saved):
	totals = {
		key: sum(flt(r[key]) for r in rows)
		for key in ("visit_count", "visit_charges", "extra_count", "extra_payments",
					"sales_incentive", "fixed_incentive", "total")
	}
	processed = bool(saved and saved.status == "Processed")
	return {
		"month": month,
		"status": saved.status if saved else "Draft",
		"processed": processed,
		"processed_on": saved.processed_on if saved else None,
		"processed_by": saved.processed_by if saved else None,
		"can_process": not processed and getdate(_bounds(month)[1]) <= getdate(),
		"rows": rows,
		"totals": totals,
		"undated_visits": 0 if processed else _undated_count(),
	}


@frappe.whitelist()
def month_summary(month):
	"""The month's table: live figures for a draft, the frozen ones once processed."""
	_assert_payout_admin()
	month = _validated_month(month)
	saved = _saved(month)

	if saved and saved.status == "Processed":
		rows = [
			frappe._dict({f: r.get(f) for f in ("technician_id", "technician_name", *ROW_FIGURES,
												 "sales_incentive", "fixed_incentive", "total")})
			for r in saved.rows
		]
	else:
		rows = _live_rows(month, saved)
	return _summary(month, rows, saved)


@frappe.whitelist()
def technician_month(month, technician_id):
	"""The visits behind one row: what the Visits and Extra figures are made of."""
	_assert_payout_admin()
	month = _validated_month(month)
	saved = _saved(month)

	if saved and saved.status == "Processed":
		return frappe.get_all(
			"Technician Visit Entry",
			filters={"payout_month": month, "technician_id": technician_id},
			fields=["name", "technician_id", "type", "status", "sales_order_id", "patient_name",
					"kilometers", "charges", "extra_payment", "extra_payment_reason",
					"extra_payment_note", "completed_at as completed_on"],
			order_by="completed_at, name",
		)
	return _month_visits(month, technician_id)


@frappe.whitelist()
def save_month(month, rows):
	"""Save the hand-entered Sales and Fixed for a draft month.

	`rows` is a list of `{technician_id, sales_incentive, fixed_incentive}`. A
	technician with no visits that month can be included -- staff paid only a
	sales or fixed incentive -- and must exist as Technician Details.
	"""
	_assert_payout_admin()
	month = _validated_month(month)
	if isinstance(rows, str):
		rows = json.loads(rows)

	doc = _saved(month) or frappe.new_doc("Technician Payout Month")
	if doc.get("status") == "Processed":
		frappe.throw(_("{0} has been processed and can no longer change.").format(month))
	doc.month = month

	entered = {}
	for row in rows or []:
		technician_id = row.get("technician_id")
		if not technician_id or not frappe.db.exists("Technician Details", technician_id):
			frappe.throw(_("{0} is not a technician.").format(technician_id or _("A row")))
		for field in ("sales_incentive", "fixed_incentive"):
			if flt(row.get(field)) < 0:
				frappe.throw(_("{0} cannot be negative.").format(_(field.replace("_", " ").title())))
		entered[technician_id] = row

	_fill(doc, month, entered)
	doc.save()
	return month_summary(month)


@frappe.whitelist()
def process_month(month):
	"""Freeze the month: save its figures and settle its visits. Cannot be undone here.

	Only a month that has ended can be processed -- visits are still being
	completed during it.
	"""
	_assert_payout_admin()
	month = _validated_month(month)
	if getdate(_bounds(month)[1]) > getdate():
		frappe.throw(_("{0} has not ended yet. It can be processed from {1}.").format(
			month, frappe.utils.formatdate(_bounds(month)[1])
		))

	doc = _saved(month) or frappe.new_doc("Technician Payout Month")
	if doc.get("status") == "Processed":
		frappe.throw(_("{0} has already been processed.").format(month))
	doc.month = month

	kept = {r.technician_id: r.as_dict() for r in doc.get("rows") or []}
	_fill(doc, month, kept)

	visits = _month_visits(month)
	doc.status = "Processed"
	doc.processed_on = now_datetime()
	doc.processed_by = frappe.session.user
	doc.flags.processing = True
	doc.save()

	# `db.set_value`, not a save per visit: a month can hold a thousand visits,
	# and only these three fields change. `guard_payout_lock` protects them from
	# here on.
	for visit in visits:
		frappe.db.set_value("Technician Visit Entry", visit.name, {
			"status": "Closed",
			"payment_status": "Cleared",
			"payout_month": month,
		})

	return month_summary(month)


def _fill(doc, month, entered):
	"""Rebuild `doc.rows` from the live figures plus the hand-entered Sales / Fixed."""
	rows = {r.technician_id: r for r in _live_rows(month)}
	for technician_id in entered:
		if technician_id not in rows:
			rows[technician_id] = frappe._dict(
				technician_id=technician_id, visit_count=0, visit_charges=0,
				extra_count=0, extra_payments=0,
			)

	doc.set("rows", [])
	for technician_id, row in rows.items():
		hand = entered.get(technician_id, {})
		doc.append("rows", {
			"technician_id": technician_id,
			**{f: row.get(f) for f in ROW_FIGURES},
			"sales_incentive": flt(hand.get("sales_incentive")),
			"fixed_incentive": flt(hand.get("fixed_incentive")),
		})


@frappe.whitelist()
def set_extra_payment(visit_id, amount, reason=None, note=None):
	"""The office correcting a visit's extra payment, until its month is processed."""
	visit = frappe.get_doc("Technician Visit Entry", visit_id)
	if visit.payout_month:
		frappe.throw(_("{0} was paid in the {1} payout; its extra payment can no longer change.").format(
			visit.name, visit.payout_month
		))
	if visit.status in ("Amount Settled", "Closed"):
		frappe.throw(_("{0} is already {1}.").format(visit.name, visit.status))
	if reason and reason not in EXTRA_REASONS:
		frappe.throw(_("Reason must be one of {0}.").format(", ".join(EXTRA_REASONS)))

	_assert_office_may_change(visit)

	visit.extra_payment = flt(amount)
	visit.extra_payment_reason = reason if flt(amount) else None
	visit.extra_payment_note = (note or "").strip() if flt(amount) else None
	visit.save()
	return {
		"name": visit.name,
		"extra_payment": visit.extra_payment,
		"extra_payment_reason": visit.extra_payment_reason,
		"extra_payment_note": visit.extra_payment_note,
	}
