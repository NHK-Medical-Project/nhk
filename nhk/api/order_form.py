"""The sales person's public order form (`nhk.api.order_form`).

One form replaces two Google Forms the sales people used (user, 2026-10-19):
*Patient Registration Form* (Rent / Purchase / Titration-CPAP Trial / Diagnostic
Study / Nursing) and *Patient Registration Form For Sleep Study*. The sleep study
form is the Diagnostic Study → Sleep Study branch of this one.

A submission is a **draft Sales Order** (docstatus 0) with `sales_person` set,
so the Sales Order list is the one common sheet every form feeds. Every answer
is stored on the order, in the *Order Form* tab (`custom_of_*` fields, patch
`add_order_form_fields`). The patient is a Customer, matched by mobile.

**Items without amounts.** NHK's Items are mostly single serial-numbered
devices that the office assigns later, so the form offers the Google Forms'
product names, never an Item or a price. Each requested product becomes a row
of the placeholder Item `ORDER FORM REQUEST` at rate 0, described with the
product. The office replaces those rows with real Items; `before_submit`
refuses an order that still has one.

**The referring doctor is typed, never looked up**: the Referrer list is
confidential. The text goes in `custom_of_doctor`; the office links the
Referrer (mandatory on submit, skipped for the draft).

**The token says whom it is from** (user, 2026-10-19). Each Sales Person stores
a random token in `custom_order_form_token`; the office copies the link,
`/order-form?token=<token>`, from the Sales Person form and can replace the
token when a link leaks. No login.

The sales person app (to come) follows their orders logged in: `my_orders`,
`order` and `comment`. There, identity is the NHK User → User → Employee →
Sales Person chain that `NHKUser.on_submit` builds for the `NHK Sales` role
profile; never roles.
"""

import secrets

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, cstr, get_url, getdate, today

ORDER = "Sales Order"
TOKEN_FIELD = "custom_order_form_token"

#: The Item every requested product is booked against until the office picks the real one.
PLACEHOLDER_ITEM = "ORDER FORM REQUEST"

PRICE_LIST = "Standard Selling"
CUSTOMER_GROUP = "Individual"
TERRITORY = "India"

#: Who may copy or replace a sales person's form link.
LINK_ROLES = ("NHK Admin", "System Manager", "Sales Manager")

# ---------------------------------------------------------------------------
# the form's choices, as the Google Forms had them
# ---------------------------------------------------------------------------

RENT, PURCHASE, TITRATION, DIAGNOSTIC, NURSING = (
	"Rent", "Purchase", "Titration / CPAP Trial", "Diagnostic Study", "Nursing / Caretaker",
)

#: Kind of request → Sales Order `order_type`. Recent orders book devices,
#: studies and nursing as Rental, and purchases as Sales.
KINDS = {RENT: "Rental", PURCHASE: "Sales", TITRATION: "Rental", DIAGNOSTIC: "Rental", NURSING: "Rental"}

RENT_PRODUCTS = (
	"Auto CPAP with new mask tubing", "Auto CPAP without mask tubing", "Oxygen Concentrator", "Oxygen Cylinder",
	"BIPAP with new mask tubing", "BIPAP without mask tubing",
)
RENT_DURATIONS = ("1 day trial", "7 days", "15 days", "30 days")
PURCHASE_PRODUCTS = ("Auto CPAP", "Oxygen Concentrator", "Oxygen Cylinder", "Bipap", "NIV/CPAP Mask & Tubing")
TITRATION_DAYS = ("1 Day", "2 Days", "3 Days")
SLEEP_STUDY = "Sleep Study Test"
#: `?form=sleep-study` opens the form on Diagnostic Study → Sleep Study Test
#: with only the sleep study Google Form's questions, for links sent per request.
SLEEP_STUDY_FORM = "sleep-study"
FORMS = (SLEEP_STUDY_FORM,)
TESTS = ("ABPM Test (24 hrs)", "Holter Test", SLEEP_STUDY)
GENDERS = ("Male", "Female", "Other")
LANGUAGES = ("Hindi", "English", "Kannada", "Tamil", "Bengali")
SYMPTOMS = (
	"Smoking", "Alcoholic More than 2 Times a week", "Not Refreshing Sleep", "Day Naps", "Diabetes",
	"High blood pressure", "Heart problem", "Insomnia", "Snoring", "Tired during day time", "Choking in the Night",
	"Day Time Sleepiness", "Low on Energy", "Reduced Sex Drive", "Lack Of Focus", "Stroke", "Headache",
	"None of the Above",
)

#: A typing guard, not a policy.
MAX_TEXT = 140
MAX_LONG_TEXT = 1000
MAX_OTHER_PRODUCTS = 5

SUBMITS_PER_HOUR = 30

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_COMMENT = 2000


def choices():
	"""Every choice the form offers, for the page to draw."""
	return {
		"kinds": list(KINDS), "rent_products": RENT_PRODUCTS, "rent_durations": RENT_DURATIONS,
		"purchase_products": PURCHASE_PRODUCTS, "titration_days": TITRATION_DAYS, "tests": TESTS,
		"sleep_study": SLEEP_STUDY, "genders": GENDERS, "languages": LANGUAGES, "symptoms": SYMPTOMS,
		"kind_names": {"rent": RENT, "purchase": PURCHASE, "titration": TITRATION, "diagnostic": DIAGNOSTIC,
			"nursing": NURSING},
	}


class NotASalesPerson(frappe.PermissionError):
	"""The session user has no enabled Sales Person record."""


class BadFormLink(frappe.PermissionError):
	"""The form link's token matches no enabled Sales Person."""


# ---------------------------------------------------------------------------
# the token and the link
# ---------------------------------------------------------------------------

def new_token() -> str:
	return secrets.token_urlsafe(18)


def set_token(doc, method=None):
	"""`before_insert` on Sales Person: every new one gets a token."""
	if not doc.get(TOKEN_FIELD):
		doc.set(TOKEN_FIELD, new_token())


def form_sales_person(token) -> str:
	"""The Sales Person a form link's token belongs to, or throw BadFormLink."""
	token = cstr(token).strip()
	row = token and frappe.db.get_value("Sales Person", {TOKEN_FIELD: token, "is_group": 0}, ["name", "enabled"],
		as_dict=True)
	if not row:
		frappe.throw(_("This order form link is not valid. Ask the office for yours."), BadFormLink)
	if not row.enabled:
		frappe.throw(_("This order form is closed. Ask the office."), BadFormLink)
	return row.name


def _link(token, form=None):
	return get_url(f"/order-form?token={token}" + (f"&form={form}" if form else ""))


@frappe.whitelist()
def form_link(sales_person, form=None):
	"""`sales_person`'s public form link, making their token first if they have none.

	`form` (one of FORMS) opens the link on that request alone; the token is the same.
	"""
	frappe.only_for(LINK_ROLES)
	form = _pick(form, FORMS, _("Form"), required=False) or None
	if not frappe.db.get_value("Sales Person", sales_person, TOKEN_FIELD):
		new_form_link(sales_person)
	return _link(frappe.db.get_value("Sales Person", sales_person, TOKEN_FIELD), form)


@frappe.whitelist(methods=["POST"])
def new_form_link(sales_person):
	"""Replace `sales_person`'s token, so their old link stops working, and return the new link."""
	frappe.only_for(LINK_ROLES)
	if not frappe.db.exists("Sales Person", sales_person):
		frappe.throw(_("Sales Person {0} not found.").format(sales_person), frappe.DoesNotExistError)
	token = new_token()
	frappe.db.set_value("Sales Person", sales_person, TOKEN_FIELD, token)
	frappe.get_doc("Sales Person", sales_person).add_comment(
		"Info", _("New order form link made; the old one no longer works."))
	return _link(token)


# ---------------------------------------------------------------------------
# the form (public)
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=SUBMITS_PER_HOUR, seconds=60 * 60)
def submit(token, form):
	"""Create a draft Sales Order from one form submission and return its name.

	`token` is the form link's; `form` (a dict or JSON) holds the answers under
	the keys the page sends (see `_read`).
	"""
	sales_person = form_sales_person(token)
	answers = _read(frappe.parse_json(form) if isinstance(form, str) else form)
	requested = _requested(answers)

	order = frappe.new_doc(ORDER)
	order.update({
		"customer": _customer_for(answers),
		"order_type": KINDS[answers.kind],
		"transaction_date": today(),
		"delivery_date": answers.study_date or getdate(today()),
		"selling_price_list": PRICE_LIST,
		"sales_person": sales_person,
		"custom_from_order_form": 1,
		**{f"custom_of_{key}": value for key, value in _stored(answers, requested).items()},
	})
	for line in requested:
		order.append("items", {"item_code": PLACEHOLDER_ITEM, "qty": 1, "rate": 0, "description": line,
			"delivery_date": order.delivery_date})

	# The token is checked above; whoever fills the form holds no rights on
	# Sales Order. The Referrer is mandatory but confidential to the form: the
	# office links it from `custom_of_doctor` before submitting, where Frappe
	# checks mandatory fields again.
	order.flags.ignore_permissions = True
	order.flags.ignore_mandatory = True
	order.insert()
	order.add_comment("Comment", _("Raised from the order form of {0}.").format(sales_person))
	return {"name": order.name}


def _read(form):
	"""The answers, cleaned and checked as the Google Forms checked them, or a ValidationError."""
	form = frappe._dict(form or {})
	a = frappe._dict(
		kind=_pick(form.kind, KINDS, _("Type")),
		patient_name=_text(form.patient_name, _("Name"), required=True),
		age=_text(form.age, _("Age"), required=True, limit=20),
		gender=_gender(form.gender, form.gender_other),
		mobile=_mobile(form.mobile, _("Mobile number"), required=True),
		whatsapp=_mobile(form.whatsapp, _("WhatsApp number")),
		alternate_mobile=_mobile(form.alternate_mobile, _("Alternative mobile number")),
		email=_email(form.email),  # both Google Forms required it
		delivery_address=_text(form.delivery_address, _("Address"), required=True, limit=MAX_LONG_TEXT),
		gps_location=_text(form.gps_location, _("GPS location"), limit=MAX_LONG_TEXT),
		permanent_address=_text(form.permanent_address, _("Permanent address"), limit=MAX_LONG_TEXT),
		doctor=_text(form.doctor, _("Dr name & hospital name"), required=True),
		diagnosis=_text(form.diagnosis, _("Diagnosis"), limit=MAX_LONG_TEXT),
		height=_text(form.height, _("Height"), limit=20),
		weight=_text(form.weight, _("Weight"), limit=20),
		delivery_time=_text(form.delivery_time, _("Delivery time")),
		delivery_remarks=_text(form.delivery_remarks, _("Delivery remarks"), limit=MAX_LONG_TEXT),
		rent=[],
		purchase=[],
		titration_days=None,
		test=None,
		profession=None,
		languages=[],
		symptoms=[],
		sleep_time=None,
		wake_time=None,
		study_date=None,
	)

	if not a.email:
		frappe.throw(_("Email is required."))

	if a.kind == RENT:
		# The Google Form's grid: one row per period, at most one product in each.
		for row in form.rent or []:
			row = frappe._dict(row)
			a.rent.append((_pick(row.product, RENT_PRODUCTS, _("Rental product")),
				_pick(row.duration, RENT_DURATIONS, _("Rental period"))))
		if not a.rent:
			frappe.throw(_("Choose at least one product in the rental grid."))
		if len({duration for _product, duration in a.rent}) < len(a.rent):
			frappe.throw(_("Choose one product per rental period."))
	elif a.kind == PURCHASE:
		for product in form.purchase or []:
			a.purchase.append(_pick(product, PURCHASE_PRODUCTS, _("Product")))
		others = [_text(o, _("Other product")) for o in (form.purchase_other or []) if cstr(o).strip()]
		a.purchase += others[:MAX_OTHER_PRODUCTS]
		if not a.purchase:
			frappe.throw(_("Choose at least one product to buy."))
	elif a.kind == TITRATION:
		a.titration_days = _pick(form.titration_days, TITRATION_DAYS, _("Number of days"))
	elif a.kind == DIAGNOSTIC:
		a.test = _pick(form.test, TESTS, _("Test"))
		if not (a.height and a.weight):
			frappe.throw(_("Height and weight are required for a diagnostic study."))

	if a.test == SLEEP_STUDY:
		# The sleep study form's own questions.
		if not a.gender:
			frappe.throw(_("Gender is required."))
		a.profession = _text(form.profession, _("Profession"), required=True)
		a.languages = [_pick(x, LANGUAGES, _("Preferred language")) for x in (form.languages or [])]
		other_language = _text(form.language_other, _("Other language"))
		if other_language:
			a.languages.append(other_language)
		a.symptoms = [_pick(x, SYMPTOMS, _("Symptom")) for x in (form.symptoms or [])]
		if not a.symptoms:
			frappe.throw(_("Tick at least one of the listed conditions, or None of the Above."))
		a.sleep_time = _time(form.sleep_time, _("Sleep time"))
		a.wake_time = _time(form.wake_time, _("Wake up time"))
		a.study_date = getdate(form.study_date) if form.study_date else None
		if a.study_date and a.study_date < getdate(today()):
			frappe.throw(_("The sleep study cannot be scheduled in the past."))
	elif not a.diagnosis:
		# The patient registration form asked for it; the sleep study form did not.
		frappe.throw(_("Diagnosis / problems faced by the patient is required."))
	return a


def _requested(a):
	"""One line per product or service asked for: the description of its placeholder row."""
	if a.kind == RENT:
		return [_("Rent: {0}, {1}").format(product, duration) for product, duration in a.rent]
	if a.kind == PURCHASE:
		return [_("Purchase: {0}").format(product) for product in a.purchase]
	if a.kind == TITRATION:
		return [_("Titration / CPAP trial: {0}").format(a.titration_days)]
	if a.kind == DIAGNOSTIC:
		return [_("Diagnostic study: {0}").format(a.test)]
	return [_("Nursing / Caretaker")]


def _stored(a, requested):
	"""The `custom_of_*` values: every answer, as the office reads it on the order."""
	return {
		"kind": a.kind, "patient_name": a.patient_name, "age": a.age, "gender": a.gender or None,
		"mobile": a.mobile, "whatsapp": a.whatsapp, "alternate_mobile": a.alternate_mobile, "email": a.email,
		"delivery_address": a.delivery_address, "gps_location": a.gps_location,
		"permanent_address": a.permanent_address, "doctor": a.doctor, "diagnosis": a.diagnosis,
		"height": a.height, "weight": a.weight, "products": "\n".join(requested),
		"titration_days": a.titration_days, "test": a.test, "profession": a.profession,
		"languages": ", ".join(a.languages), "symptoms": ", ".join(a.symptoms), "sleep_time": a.sleep_time,
		"wake_time": a.wake_time, "study_date": a.study_date, "delivery_time": a.delivery_time,
		"delivery_remarks": a.delivery_remarks,
	}


def _text(value, label, required=False, limit=MAX_TEXT):
	# Short answers collapse to one line; addresses and remarks keep theirs.
	value = cstr(value).strip() if limit > MAX_TEXT else " ".join(cstr(value).split())
	if required and not value:
		frappe.throw(_("{0} is required.").format(label))
	if len(value) > limit:
		frappe.throw(_("{0} is at most {1} characters.").format(label, limit))
	return value


def _pick(value, allowed, label, required=True):
	value = cstr(value).strip()
	if not value and not required:
		return ""
	if value not in allowed:
		frappe.throw(_("Choose a {0}.").format(label.lower()) if not value else
			_("{0} is not a choice for {1}.").format(value, label))
	return value


def _gender(value, other):
	"""Male, Female, or what was typed beside Other, as the sleep study form allowed."""
	value = _pick(value, GENDERS, _("Gender"), required=False)
	if value == "Other":
		return _text(other, _("Gender")) or value
	return value


def _mobile(value, label, required=False):
	digits = "".join(c for c in cstr(value) if c.isdigit())
	if not digits:
		if required:
			frappe.throw(_("{0} is required.").format(label))
		return ""
	if len(digits) == 12 and digits.startswith("91"):
		digits = digits[2:]
	if len(digits) != 10:
		frappe.throw(_("{0}: enter a 10-digit mobile number.").format(label))
	return digits


def _email(value):
	value = cstr(value).strip()
	if value and not frappe.utils.validate_email_address(value):
		frappe.throw(_("Enter a valid email address."))
	return value


def _time(value, label):
	value = cstr(value).strip()
	if not value:
		return None
	try:
		return frappe.utils.get_time(value).strftime("%H:%M:%S")
	except Exception:
		frappe.throw(_("{0} is not a time.").format(label))


def _customer_for(a):
	"""The Customer for this patient: the one with this mobile, or a new one.

	A Sales Order fetches `customer_mobile_no`, `delivery_address` and
	`permanent_address` from the Customer on every save, so a new patient's are
	set there; an existing patient's blank ones are filled in. What the form
	said is on the order in `custom_of_*` either way.
	"""
	existing = frappe.db.sql(
		"""
		select name, delivery_address, permanent_address, alternate_mobile_no from `tabCustomer`
		where disabled = 0 and replace(replace(mobile_number, ' ', ''), '+91', '') = %s
		order by modified desc limit 1
		""",
		a.mobile,
		as_dict=True,
	)
	details = {"delivery_address": a.delivery_address, "permanent_address": a.permanent_address,
		"alternate_mobile_no": a.alternate_mobile or a.whatsapp}
	if existing:
		blank = {k: v for k, v in details.items() if v and not cstr(existing[0].get(k)).strip()}
		if blank:
			frappe.db.set_value("Customer", existing[0].name, blank)
		return existing[0].name

	customer = frappe.get_doc({
		"doctype": "Customer",
		"customer_name": a.patient_name,
		"customer_type": "Individual",
		"customer_group": CUSTOMER_GROUP,
		"territory": TERRITORY,
		"gst_category": "Unregistered",
		"mobile_number": a.mobile,
		**details,
	})
	customer.flags.ignore_permissions = True
	customer.insert()
	return customer.name


def refuse_placeholder_on_submit(doc, method=None):
	"""`before_submit` on Sales Order: a form request must be swapped for a real Item first."""
	rows = [row.idx for row in doc.items if row.item_code == PLACEHOLDER_ITEM]
	if rows:
		frappe.throw(_("Replace the order form request in row {0} with the actual item before submitting.").format(
			", ".join(str(i) for i in rows)))


# ---------------------------------------------------------------------------
# following an order (logged in, for the sales person app)
# ---------------------------------------------------------------------------

def current_sales_person(user: str | None = None) -> str:
	"""Return the `Sales Person` name for the calling user, or throw NotASalesPerson."""
	user = user or frappe.session.user
	if user in ("Guest", "Administrator"):
		frappe.throw(_("No sales person is linked to {0}.").format(user), NotASalesPerson)

	names = frappe.db.sql(
		"""
		select sp.name from `tabSales Person` sp
		join `tabEmployee` e on e.name = sp.employee
		where e.user_id = %s and sp.enabled = 1 and sp.is_group = 0
		limit 2
		""",
		user,
		pluck=True,
	)
	if not names:
		frappe.throw(_("No sales person is linked to {0}.").format(user), NotASalesPerson)
	if len(names) > 1:
		# Two Sales Person records on one login would make "whose order is this"
		# ambiguous. Fail loudly rather than pick one.
		frappe.throw(_("More than one sales person is linked to {0}. Ask the office to fix it.").format(user),
			NotASalesPerson)
	return names[0]


def _own_order(name):
	"""The Sales Order `name`, if it belongs to the caller; else a PermissionError."""
	sales_person = current_sales_person()
	order = frappe.db.get_value(ORDER, cstr(name), ["name", "sales_person", "docstatus"], as_dict=True)
	if not order or order.sales_person != sales_person:
		frappe.throw(_("Sales Order {0} is not one of yours.").format(name), frappe.PermissionError)
	return order


@frappe.whitelist()
def my_orders(status=None, drafts_only=0, limit=DEFAULT_LIMIT):
	"""The caller's Sales Orders, newest first. `drafts_only` keeps those the office has not submitted."""
	filters = {"sales_person": current_sales_person(), "docstatus": ["<", 2]}
	if cint(drafts_only):
		filters["docstatus"] = 0
	if status:
		filters["status"] = status
	return frappe.get_all(
		ORDER,
		filters=filters,
		fields=["name", "customer", "customer_name", "customer_mobile_no", "order_type", "status", "docstatus",
			"transaction_date", "delivery_date", "custom_of_kind", "custom_of_products", "custom_of_doctor",
			"modified"],
		order_by="creation desc",
		limit=min(cint(limit) or DEFAULT_LIMIT, MAX_LIMIT),
		ignore_permissions=True,
	)


@frappe.whitelist()
def order(name):
	"""One of the caller's Sales Orders: what the form said, its items (no amounts), and its timeline."""
	_own_order(name)
	doc = frappe.get_doc(ORDER, name)
	return {
		"name": doc.name,
		"customer": doc.customer,
		"customer_name": doc.customer_name,
		"customer_mobile_no": doc.customer_mobile_no,
		"order_type": doc.order_type,
		"status": doc.status,
		"is_draft": doc.docstatus == 0,
		"transaction_date": doc.transaction_date,
		"delivery_date": doc.delivery_date,
		"form": {f.fieldname[len("custom_of_"):]: doc.get(f.fieldname) for f in doc.meta.fields
			if f.fieldname.startswith("custom_of_") and f.fieldtype not in ("Section Break", "Column Break", "Tab Break")},
		"items": [{"item_code": i.item_code, "item_name": i.item_name, "description": i.description, "qty": i.qty}
			for i in doc.items],
		"timeline": _timeline(doc.name),
	}


@frappe.whitelist(methods=["POST"])
def comment(name, text):
	"""Add the caller's comment to one of their Sales Orders; it shows on the desk timeline."""
	_own_order(name)
	text = cstr(text).strip()
	if not text:
		frappe.throw(_("Write a comment first."))
	if len(text) > MAX_COMMENT:
		frappe.throw(_("A comment is at most {0} characters.").format(MAX_COMMENT))

	added = frappe.get_doc(ORDER, name).add_comment("Comment", frappe.utils.escape_html(text))
	return {"name": added.name, "creation": added.creation}


def _timeline(name):
	"""Comments and status changes on the order, oldest first."""
	entries = [
		{"kind": "comment", "at": c.creation, "by": frappe.utils.get_fullname(c.owner), "text": c.content}
		for c in frappe.get_all(
			"Comment",
			filters={"reference_doctype": ORDER, "reference_name": name, "comment_type": "Comment"},
			fields=["creation", "owner", "content"],
			ignore_permissions=True,
		)
	]
	for v in frappe.get_all(
		"Version",
		filters={"ref_doctype": ORDER, "docname": name},
		fields=["creation", "owner", "data"],
		ignore_permissions=True,
	):
		for field, old, new in (frappe.parse_json(v.data) or {}).get("changed", []):
			if field in ("status", "docstatus"):
				entries.append({"kind": "status", "at": v.creation, "by": frappe.utils.get_fullname(v.owner),
					"field": field, "from": old, "to": new})
	entries.sort(key=lambda e: e["at"])
	return entries
