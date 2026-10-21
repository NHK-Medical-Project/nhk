"""Sales Person Doctor Monthly: count and order amount of one month's Sales Orders,
split by kind of order, person by person -- each sales person (the order's
`sales_person`) and each doctor (the order's Referrer, `custom_referrer`).

One row per person and role, the kinds of order as columns (count and amount
each), then the person's total count, amount, paid and unpaid. Each role ends
with an "All" row. Choosing a Sales Person or a Doctor narrows the report to
them; otherwise `role` picks sales persons, doctors, or both. Clicking a count
lists its orders (`orders`).

- Amount is the order amount (`rounded_total`, else `grand_total`). It never includes the
  security deposit, which a Rental carries separately (`total_rental_amount` is the two
  together).
- Paid is `advance_paid`, which counts order payments only (the deposit is tracked in
  `paid_security_deposite_amount`), capped at the amount. Unpaid is the rest.
- Submitted orders only, by `transaction_date`. Spec: `.scratch/sales-person-doctor-report`.
"""

import calendar
import json

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

REPORT = "Sales Person Doctor Monthly"

ORDER, RENTAL, SLEEP_STUDY, SERVICE, VISIT, RENEWAL = (
	"Order", "Rental", "Sleep Study", "Service", "Visit", "Renewal",
)
KINDS = (ORDER, RENTAL, SLEEP_STUDY, SERVICE, VISIT, RENEWAL)
TOTAL = "Total"
#: `person` of a role's "All" row: every order, whoever it names.
ALL = "__all__"

SALES_PERSON, DOCTOR = "Sales Person", "Doctor"
BOTH = "Sales Person and Doctor"
#: The order field that names the person, per role.
PERSON_FIELD = {SALES_PERSON: "sales_person", DOCTOR: "custom_referrer"}

#: Rentals of an item under this group are sleep studies.
SLEEP_STUDY_GROUP = "PSG (Sleep Diagnostic Test)"
#: A Service order for this item is a sleep study too.
SLEEP_STUDY_SERVICE_ITEM = "Sleep study/Polysomnography"
#: A Service order with this item is a visit.
VISIT_ITEM = "Visit"

MONTHS = list(calendar.month_name)[1:]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	orders = _classified_orders(filters)

	data = []
	people = _people(filters, orders)
	for role in (SALES_PERSON, DOCTOR):
		mine = [p for p in people if p[0] == role]
		if not mine:
			continue
		for _role, person, title in mine:
			data.append(_row(role, person, title, [o for o in orders if (o.get(PERSON_FIELD[role]) or None) == person]))
		if len(mine) > 1:
			everyone = [o for o in orders if any((o.get(PERSON_FIELD[role]) or None) == p for _r, p, _t in mine)]
			data.append({**_row(role, ALL, _("All ({0})").format(_(role)), everyone), "bold": 1})
	return _columns(), data


@frappe.whitelist()
def orders(filters, role, person=None, kind=TOTAL):
	"""The orders behind one count: `person` in `role`, of `kind` (or all, for Total)."""
	if not frappe.get_doc("Report", REPORT).is_permitted():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	filters = frappe._dict(json.loads(filters) if isinstance(filters, str) else filters)
	if role not in PERSON_FIELD:
		frappe.throw(_("Unknown role {0}.").format(role))
	if kind != TOTAL and kind not in KINDS:
		frappe.throw(_("Unknown kind {0}.").format(kind))
	field = PERSON_FIELD[role]
	rows = [
		o for o in _classified_orders(filters)
		if (person == ALL or (o.get(field) or None) == (person or None)) and kind in (TOTAL, o.kind)
	]
	return sorted(rows, key=lambda o: (o.transaction_date, o.name))


def kind_key(kind):
	"""`Sleep Study` -> `sleep_study`: the prefix of a kind's two columns."""
	return kind.lower().replace(" ", "_")


def _columns():
	columns = [
		{"label": _("Person"), "fieldname": "label", "fieldtype": "Data", "width": 200},
		{"label": _("Role"), "fieldname": "role", "fieldtype": "Data", "width": 100},
	]
	for kind in KINDS:
		key = kind_key(kind)
		columns += [
			{"label": _("{0} Count").format(_(kind)), "fieldname": f"{key}_count", "fieldtype": "Int", "width": 90},
			{"label": _("{0} Amount").format(_(kind)), "fieldname": f"{key}_amount", "fieldtype": "Currency", "width": 120},
		]
	columns += [
		{"label": _("Total Count"), "fieldname": "total_count", "fieldtype": "Int", "width": 90},
		{"label": _("Total Amount"), "fieldname": "total_amount", "fieldtype": "Currency", "width": 130},
		{"label": _("Paid"), "fieldname": "paid", "fieldtype": "Currency", "width": 130},
		{"label": _("Unpaid"), "fieldname": "unpaid", "fieldtype": "Currency", "width": 130},
	]
	return columns


def _people(filters, orders):
	"""(role, person id or None, title) for each block, in order."""
	if filters.sales_person or filters.doctor:
		chosen = []
		if filters.sales_person:
			chosen.append((SALES_PERSON, filters.sales_person))
		if filters.doctor:
			chosen.append((DOCTOR, filters.doctor))
	else:
		roles = (SALES_PERSON, DOCTOR) if (filters.role or BOTH) == BOTH else (filters.role,)
		chosen = []
		for role in roles:
			ids = {o.get(PERSON_FIELD[role]) or None for o in orders}
			chosen.extend((role, p) for p in ids)

	people = []
	for role, person in chosen:
		people.append((role, person, _title(role, person, orders)))
	# Each role's blocks by name, the unassigned last.
	order = {SALES_PERSON: 0, DOCTOR: 1}
	return sorted(people, key=lambda p: (order[p[0]], p[1] is None, (p[2] or "").lower()))


def _title(role, person, orders):
	if not person:
		return _("No Sales Person") if role == SALES_PERSON else _("No Doctor")
	if role == DOCTOR:
		named = next((o.custom_referrer_name for o in orders if o.custom_referrer == person and o.custom_referrer_name), None)
		return named or frappe.db.get_value("Referrer", person, "doctor_name") or person
	return person


def _month(filters):
	if not filters.month or filters.month not in MONTHS:
		frappe.throw(_("Choose a month."))
	year = cint(filters.year) or getdate().year
	month = MONTHS.index(filters.month) + 1
	start = getdate(f"{year}-{month:02d}-01")
	end = getdate(f"{year + (month == 12)}-{month % 12 + 1:02d}-01")
	return start, end


def _classified_orders(filters):
	"""The month's submitted orders for the filters, each with `kind`, `paid` and `unpaid`."""
	start, end = _month(filters)
	conditions = ["so.docstatus = 1", "so.transaction_date >= %(start)s", "so.transaction_date < %(end)s"]
	people = []
	if filters.sales_person:
		people.append("so.sales_person = %(sales_person)s")
	if filters.doctor:
		people.append("so.custom_referrer = %(doctor)s")
	if people:
		conditions.append("(" + " or ".join(people) + ")")
	orders = frappe.db.sql(
		f"""
		select so.name, so.transaction_date, so.customer, so.customer_name, so.order_type, so.status,
			so.previous_order_id, so.sales_person, so.custom_referrer, so.custom_referrer_name,
			coalesce(nullif(so.rounded_total, 0), so.grand_total, 0) as amount,
			coalesce(so.advance_paid, 0) as advance_paid
		from `tabSales Order` so
		where {" and ".join(conditions)}
		""",
		{"start": start, "end": end, "sales_person": filters.sales_person, "doctor": filters.doctor},
		as_dict=True,
	)
	kinds = _kinds(orders)
	for o in orders:
		o.kind = kinds[o.name]
		o.amount = flt(o.amount)
		o.paid = min(max(flt(o.advance_paid), 0), o.amount)
		o.unpaid = o.amount - o.paid
	return orders


def _kinds(orders):
	"""Each order's kind. Renewal first, then sleep study and visit by item, then Order Type."""
	names = [o.name for o in orders]
	sleep_study, visit = set(), set()
	if names:
		bounds = frappe.db.get_value("Item Group", SLEEP_STUDY_GROUP, ["lft", "rgt"], as_dict=True)
		for row in frappe.db.sql(
			"""
			select distinct soi.parent, soi.item_code, ig.lft
			from `tabSales Order Item` soi
			left join `tabItem Group` ig on ig.name = soi.item_group
			where soi.parenttype = 'Sales Order' and soi.parent in %(names)s
			""",
			{"names": names},
			as_dict=True,
		):
			if row.item_code == SLEEP_STUDY_SERVICE_ITEM or (
				bounds and row.lft is not None and bounds.lft <= row.lft < bounds.rgt
			):
				sleep_study.add(row.parent)
			elif row.item_code == VISIT_ITEM:
				visit.add(row.parent)

	kinds = {}
	for o in orders:
		if o.previous_order_id:
			kinds[o.name] = RENEWAL
		elif o.name in sleep_study:
			kinds[o.name] = SLEEP_STUDY
		elif o.order_type == "Service":
			kinds[o.name] = VISIT if o.name in visit else SERVICE
		elif o.order_type == "Rental":
			kinds[o.name] = RENTAL
		else:
			kinds[o.name] = ORDER
	return kinds


def _row(role, person, title, orders):
	"""One person's row. `role_key`/`person` let a count open its orders."""
	row = {"label": title, "role": _(role), "role_key": role, "person": person or "",
		   "total_count": 0, "total_amount": 0.0, "paid": 0.0, "unpaid": 0.0}
	for kind in KINDS:
		row[f"{kind_key(kind)}_count"], row[f"{kind_key(kind)}_amount"] = 0, 0.0
	for o in orders:
		key = kind_key(o.kind)
		row[f"{key}_count"] += 1
		row[f"{key}_amount"] += o.amount
		row["total_count"] += 1
		row["total_amount"] += o.amount
		row["paid"] += o.paid
		row["unpaid"] += o.unpaid
	return row
