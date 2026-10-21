"""The sales person's public order form, `/order-form?token=<token>`.

No login: the token in the link says whose form it is (`nhk.api.order_form`).
Each submission becomes a draft Sales Order. Drawn inside the public website's
own header and footer (`templates/web_base.html`).
"""

import frappe
from frappe.sessions import get_csrf_token

from nhk.api.order_form import FORMS, BadFormLink, choices, form_sales_person

no_cache = 1


def get_context(context):
	context.token = frappe.form_dict.get("token")
	context.choices = choices()
	# `?form=sleep-study`: the same form, opened on that one request.
	context.form = frappe.form_dict.get("form") if frappe.form_dict.get("form") in FORMS else ""
	# Guests post without a CSRF token; a desk user opening a sales person's link must send one.
	context.csrf_token = get_csrf_token() if frappe.session.user != "Guest" else ""
	try:
		context.sales_person = form_sales_person(context.token)
		context.link_error = None
	except BadFormLink as exc:
		frappe.clear_messages()
		context.sales_person = None
		context.link_error = str(exc)
	return context
