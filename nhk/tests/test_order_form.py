"""The sales person's public order form (`nhk.api.order_form`): a submission
through a sales person's token link is a draft Sales Order under their name
holding every answer, and only that sales person can follow it when logged in.

Run:  cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_order_form.py

Needs the patches `add_sales_person_order_form_token` and
`add_order_form_fields`. The sales people are real (Sales Person →
Employee → User on the snapshot); every order and customer a test makes is
deleted afterwards, and every token it changes is put back.
"""

import sys
import uuid

import frappe

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from nhk.api.order_form import TOKEN_FIELD


def _sales_users(n=2):
	"""Logins that resolve to exactly one enabled Sales Person."""
	rows = frappe.db.sql(
		"""
		select e.user_id from `tabSales Person` sp join `tabEmployee` e on e.name = sp.employee
		where sp.enabled = 1 and sp.is_group = 0 and coalesce(e.user_id, '') != ''
		group by e.user_id having count(*) = 1 order by e.user_id limit %s
		""",
		n,
		pluck=True,
	)
	assert len(rows) == n, "the snapshot needs %s sales people with a login" % n
	return rows


def _priced_item():
	return frappe.db.sql(
		"""
		select ip.item_code, ip.price_list_rate from `tabItem Price` ip join `tabItem` i on i.name = ip.item_code
		where ip.price_list = 'Standard Selling' and ip.selling = 1 and ip.price_list_rate > 0
			and i.disabled = 0 and i.is_sales_item = 1 and i.has_variants = 0
		limit 1
		""",
		as_dict=True,
	)[0]


def _mobile():
	return "9" + str(uuid.uuid4().int)[:9]


def _as(user, fn, *args, **kwargs):
	frappe.set_user(user)
	try:
		return fn(*args, **kwargs)
	finally:
		frappe.set_user("Administrator")


def _token(user):
	"""The sales person behind `user`, and their stored token."""
	from nhk.api import order_form

	sp = order_form.current_sales_person(user)
	token = frappe.db.get_value("Sales Person", sp, TOKEN_FIELD)
	assert token, "%s has no order form token: run the patch" % sp
	return sp, token


def _answers(**overrides):
	"""A complete Rent request, as the page sends it."""
	answers = {
		"kind": "Rent", "patient_name": "Order Form Test", "age": "64", "mobile": _mobile(),
		"email": "patient@example.com", "delivery_address": "1 Test Street", "doctor": "Dr Test, Test Hospital",
		"diagnosis": "Sleep apnoea", "rent": [{"product": "Oxygen Concentrator", "duration": "7 days"}],
	}
	answers.update(overrides)
	return answers


def _sleep_study(**overrides):
	return _answers(**{"kind": "Diagnostic Study", "test": "Sleep Study Test", "rent": [], "diagnosis": "",
		"gender": "Male", "height": "170 cm", "weight": "80 kg", "profession": "Teacher",
		"symptoms": ["Snoring", "Day Naps"], "languages": ["Kannada"], "language_other": "Tulu",
		"sleep_time": "23:00", "wake_time": "06:30", **overrides})


def _submit(cleanup, user, **overrides):
	"""Fill `user`'s public form as a guest would."""
	from nhk.api import order_form

	answers = _answers(**overrides)
	result = _as("Guest", order_form.submit, _token(user)[1], answers)
	customer = frappe.db.get_value("Sales Order", result["name"], "customer")
	if frappe.db.get_value("Customer", customer, "customer_name") == answers["patient_name"]:
		cleanup.add("Customer", customer)
	cleanup.add("Sales Order", result["name"])
	return result["name"]


def _office_outsider():
	"""An enabled login with none of the roles that may copy links."""
	from nhk.api import order_form

	return frappe.db.sql(
		"""
		select u.name from `tabUser` u where u.enabled = 1 and u.user_type = 'System User'
			and u.name not in ('Administrator', 'Guest')
			and u.name not in (select parent from `tabHas Role` where parenttype = 'User' and role in %s)
		limit 1
		""",
		[order_form.LINK_ROLES],
		pluck=True,
	)[0]


# --------------------------------------------------------------------------
# the token and the link
# --------------------------------------------------------------------------

def test_every_enabled_sales_person_has_a_distinct_token(cleanup):
	rows = frappe.get_all("Sales Person", filters={"is_group": 0}, fields=["name", TOKEN_FIELD])
	tokens = [r[TOKEN_FIELD] for r in rows]
	assert all(tokens), [r.name for r in rows if not r[TOKEN_FIELD]]
	assert len(set(tokens)) == len(tokens), "two sales people share a token"


def test_a_new_sales_person_gets_a_token(cleanup):
	parent = frappe.db.get_value("Sales Person", {"is_group": 1}, "name")
	sp = frappe.get_doc({"doctype": "Sales Person", "sales_person_name": "Order Form Test " + uuid.uuid4().hex[:6],
						 "parent_sales_person": parent, "is_group": 0}).insert(ignore_permissions=True)
	cleanup.add("Sales Person", sp.name)
	assert sp.get(TOKEN_FIELD), "no token on insert"


def test_the_office_copies_the_link_and_can_replace_it(cleanup):
	from nhk.api import order_form

	sp, token = _token(_sales_users(1)[0])
	cleanup.restore("Sales Person", sp, TOKEN_FIELD)

	assert order_form.form_link(sp).endswith("/order-form?token=" + token)  # as Administrator
	new = order_form.new_form_link(sp)
	fresh = frappe.db.get_value("Sales Person", sp, TOKEN_FIELD)
	assert fresh != token and new.endswith("token=" + fresh), new
	try:
		order_form.form_sales_person(token)
	except order_form.BadFormLink:
		pass
	else:
		raise AssertionError("the replaced link still works")
	assert order_form.form_sales_person(fresh) == sp

	for user in ("Guest", _office_outsider()):
		for fn in (order_form.form_link, order_form.new_form_link):
			try:
				_as(user, fn, sp)
			except frappe.PermissionError:
				continue
			raise AssertionError("%s reached %s" % (user, fn.__name__))


def test_the_sleep_study_link_opens_the_same_form_on_the_sleep_study(cleanup):
	from nhk.api import order_form

	sp, token = _token(_sales_users(1)[0])
	link = order_form.form_link(sp, form=order_form.SLEEP_STUDY_FORM)
	assert link.endswith("/order-form?token=%s&form=sleep-study" % token), link
	try:
		order_form.form_link(sp, form="nursing")
	except frappe.ValidationError:
		pass
	else:
		raise AssertionError("an unknown form name made a link")


# --------------------------------------------------------------------------
# the public form
# --------------------------------------------------------------------------

def test_a_rent_request_is_a_draft_sales_order_holding_every_answer(cleanup):
	from nhk.api import order_form

	user = _sales_users(1)[0]
	mobile = _mobile()
	name = _submit(cleanup, user, mobile=mobile, alternate_mobile="9000000001", permanent_address="2 Home Road",
		rent=[{"product": "Auto CPAP with new mask tubing", "duration": "1 day trial"},
			  {"product": "Oxygen Concentrator", "duration": "15 days"},
			  {"product": "Oxygen Concentrator", "duration": "30 days"}],
		delivery_time="After 5 pm", delivery_remarks="Call first")

	so = frappe.get_doc("Sales Order", name)
	assert (so.docstatus, so.order_type, so.custom_from_order_form) == (0, "Rental", 1), (so.docstatus, so.order_type)
	assert so.sales_person == order_form.current_sales_person(user), so.sales_person
	assert not so.custom_referrer, "the referrer is confidential to the form"
	assert so.custom_of_doctor == "Dr Test, Test Hospital", so.custom_of_doctor
	assert (so.customer_mobile_no, so.delivery_address, so.permanent_address) == (mobile, "1 Test Street", "2 Home Road")
	assert (so.custom_of_age, so.custom_of_email, so.custom_of_delivery_time, so.custom_of_delivery_remarks) == (
		"64", "patient@example.com", "After 5 pm", "Call first")
	# A Rental order refuses the same Item twice (ERPNext fork, `prevent_duplicate_items`),
	# so every rental line shares one placeholder row; Requested keeps them one per line.
	lines = ["Rent: Auto CPAP with new mask tubing, 1 day trial", "Rent: Oxygen Concentrator, 15 days",
		"Rent: Oxygen Concentrator, 30 days"]
	assert [(i.item_code, i.description, i.qty, i.rate) for i in so.items] == [
		(order_form.PLACEHOLDER_ITEM, "<br>".join(lines), 1, 0),
	], [(i.item_code, i.description, i.qty, i.rate) for i in so.items]
	assert so.custom_of_products.splitlines() == lines, so.custom_of_products

	# Requested outlives the item table: the office swaps the placeholder for the real devices.
	so.items[0].item_code = _priced_item().item_code
	so.flags.ignore_mandatory = True
	so.save(ignore_permissions=True)
	assert frappe.db.get_value("Sales Order", name, "custom_of_products").splitlines() == lines


def test_a_sleep_study_request_stores_the_sleep_study_answers(cleanup):
	user = _sales_users(1)[0]
	from nhk.api import order_form

	answers = _sleep_study(study_date=frappe.utils.add_days(frappe.utils.today(), 2))
	name = _as("Guest", order_form.submit, _token(user)[1], answers)["name"]
	cleanup.add("Sales Order", name)
	so = frappe.get_doc("Sales Order", name)
	cleanup.add("Customer", so.customer)

	assert (so.custom_of_kind, so.custom_of_test, so.order_type) == ("Diagnostic Study", "Sleep Study Test", "Rental")
	assert (so.custom_of_gender, so.custom_of_profession, so.custom_of_height, so.custom_of_weight) == (
		"Male", "Teacher", "170 cm", "80 kg")
	assert so.custom_of_languages == "Kannada, Tulu" and so.custom_of_symptoms == "Snoring, Day Naps", so.custom_of_symptoms
	assert (str(so.custom_of_sleep_time), str(so.custom_of_wake_time)) == ("23:00:00", "6:30:00"), (so.custom_of_sleep_time, so.custom_of_wake_time)
	assert str(so.delivery_date) == answers["study_date"] == str(so.custom_of_study_date)
	assert [i.description for i in so.items] == ["Diagnostic study: Sleep Study Test"]

	# "Other" on gender takes the typed text, as the sleep study form did.
	other = _as("Guest", order_form.submit, _token(user)[1], _sleep_study(gender="Other", gender_other="Transgender"))
	cleanup.add("Sales Order", other["name"])
	assert frappe.db.get_value("Sales Order", other["name"], "custom_of_gender") == "Transgender"


def test_purchase_titration_and_nursing_each_book_their_request(cleanup):
	user = _sales_users(1)[0]
	cases = {
		"Purchase": ({"purchase": ["Auto CPAP", "Bipap"], "purchase_other": ["Humidifier"]},
					 "Sales", ["Purchase: Auto CPAP", "Purchase: Bipap", "Purchase: Humidifier"]),
		"Titration / CPAP Trial": ({"titration_days": "2 Days"}, "Rental", ["Titration / CPAP trial: 2 Days"]),
		"Nursing / Caretaker": ({}, "Rental", ["Nursing / Caretaker"]),
	}
	for kind, (extra, order_type, lines) in cases.items():
		name = _submit(cleanup, user, kind=kind, rent=[], **extra)
		so = frappe.get_doc("Sales Order", name)
		assert so.order_type == order_type and [i.description for i in so.items] == lines, (kind, so.order_type,
			[i.description for i in so.items])
		assert so.custom_of_products.splitlines() == lines, (kind, so.custom_of_products)


def test_the_same_mobile_reuses_the_patient(cleanup):
	user = _sales_users(1)[0]
	mobile = _mobile()
	first = _submit(cleanup, user, mobile=mobile)
	second = _submit(cleanup, user, mobile="+91 " + mobile, patient_name="Someone Else")
	customers = {frappe.db.get_value("Sales Order", n, "customer") for n in (first, second)}
	assert len(customers) == 1, customers


def test_the_form_refuses_what_the_google_forms_refused(cleanup):
	from nhk.api import order_form

	token = _token(_sales_users(1)[0])[1]
	bad_answers = [
		_answers(patient_name=""), _answers(age=""), _answers(mobile="12345"), _answers(doctor=""),
		_answers(delivery_address=""), _answers(diagnosis=""), _answers(email=""), _answers(email="not-an-email"),
		_answers(kind="Shopping Cart"), _answers(rent=[]), _answers(rent=[{"product": "Oxygen Concentrator"}]),
		_answers(rent=[{"product": "Rocket", "duration": "7 days"}]),
		_answers(rent=[{"product": "Oxygen Concentrator", "duration": "7 days"},       # one product per period
					   {"product": "Oxygen Cylinder", "duration": "7 days"}]),
		_answers(kind="Purchase", rent=[], purchase=[]), _answers(kind="Titration / CPAP Trial", rent=[]),
		_answers(kind="Diagnostic Study", rent=[], test="ABPM Test (24 hrs)"),          # no height / weight
		_sleep_study(symptoms=[]), _sleep_study(gender=""), _sleep_study(profession=""), _sleep_study(email=""),
		_sleep_study(study_date="2020-01-01"), _sleep_study(sleep_time="25:99"),
	]
	for answers in bad_answers:
		try:
			_as("Guest", order_form.submit, token, answers)
		except frappe.ValidationError:
			continue
		raise AssertionError("accepted %s" % answers)
	for bad_token in ("nope", ""):
		try:
			_as("Guest", order_form.submit, bad_token, _answers())
		except order_form.BadFormLink:
			continue
		raise AssertionError("accepted token %r" % bad_token)


def test_a_draft_with_a_form_request_cannot_be_submitted(cleanup):
	from nhk.api import order_form

	so = frappe.get_doc("Sales Order", _submit(cleanup, _sales_users(1)[0]))
	try:
		order_form.refuse_placeholder_on_submit(so)
	except frappe.ValidationError:
		pass
	else:
		raise AssertionError("a placeholder row was let through to submit")
	so.items[0].item_code = _priced_item().item_code
	so.items = so.items[:1]
	order_form.refuse_placeholder_on_submit(so)  # nothing left to swap: allowed


def test_a_disabled_sales_person_has_no_form(cleanup):
	from nhk.api import order_form

	sp, token = _token(_sales_users(1)[0])
	cleanup.restore("Sales Person", sp, "enabled")
	frappe.db.set_value("Sales Person", sp, "enabled", 0, update_modified=False)
	try:
		_as("Guest", order_form.submit, token, _answers())
	except order_form.BadFormLink:
		return
	raise AssertionError("a disabled sales person's form stayed open")


# --------------------------------------------------------------------------
# following an order (logged in)
# --------------------------------------------------------------------------

def test_a_sales_person_sees_and_comments_on_their_own_drafts_only(cleanup):
	from nhk.api import order_form

	mine, theirs = _sales_users(2)
	name = _submit(cleanup, mine)

	assert name in [o.name for o in _as(mine, order_form.my_orders, drafts_only=1)]
	assert name not in [o.name for o in _as(theirs, order_form.my_orders)]

	_as(mine, order_form.comment, name, "<b>Patient prefers morning</b>")
	last = _as(mine, order_form.order, name)["timeline"][-1]
	assert last["text"] == "&lt;b&gt;Patient prefers morning&lt;/b&gt;", last

	for fn, args in ((order_form.order, (name,)), (order_form.comment, (name, "hello"))):
		try:
			_as(theirs, fn, *args)
		except frappe.PermissionError:
			continue
		raise AssertionError("another sales person reached %s" % fn.__name__)

	for user in ("Guest", "Administrator"):
		try:
			_as(user, order_form.my_orders)
		except order_form.NotASalesPerson:
			continue
		raise AssertionError("%s followed a sales person's orders" % user)


if __name__ == "__main__":
	import harness
	raise SystemExit(harness.run(sys.modules[__name__]))
