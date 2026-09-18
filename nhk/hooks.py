app_name = "nhk"
app_title = "nhk"
app_publisher = "vishnu"
app_description = "nhk"
app_email = "vishnuram@360ithub.com"
app_license = "mit"
# required_apps = []

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/nhk/css/nhk.css"
# app_include_js = "/assets/nhk/js/nhk.js"

# include js, css files in header of web template
# web_include_css = "/assets/nhk/css/nhk.css"
# web_include_js = "/assets/nhk/js/nhk.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "nhk/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "nhk/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "nhk.utils.jinja_methods",
# 	"filters": "nhk.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "nhk.install.before_install"
# after_install = "nhk.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "nhk.uninstall.before_uninstall"
# after_uninstall = "nhk.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "nhk.utils.before_app_install"
# after_app_install = "nhk.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "nhk.utils.before_app_uninstall"
# after_app_uninstall = "nhk.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "nhk.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# Reassignment. Changing `technician_id` on a Technician Visit Entry has to carry
# the DocShare, the technician's answer and the Sales Order's own technician
# fields with it. None of that used to happen: the only re-share lived in an
# `after_save` in the form script, gated on a visit type that nothing creates.
#
# It hangs off `doc_events` rather than the form so a plain desk edit behaves the
# same as `nhk.api.assignment.reassign_visit`. `validate` is where the guard can
# still refuse a write; `on_update` is where the side effects go.
#
# No other app registers doc_events on this doctype, so nothing else fires on it.
doc_events = {
	"Technician Visit Entry": {
		"validate": "nhk.api.assignment.guard_reassignment",
		"on_update": "nhk.api.assignment.sync_assignment",
	},
}

# Scheduled Tasks
# ---------------
scheduler_events = {
   "cron":{
      #  "0 */2 * * *":
      #      [
      #      "erpnext.selling.doctype.sales_order.sales_order.validate_and_update_payment_status_for_all",
      #      "erpnext.selling.doctype.sales_order.sales_order.validate_and_update_payment_status_for_all_rental"
            
      #      ],
    #    "0 4 * * *": [
    #        "nhk.nhk.doctype.payment_link_log.payment_link_log.sync_all_payment_details"
    #    ]
   },
}
# scheduler_events = {
# 	"all": [
# 		"nhk.tasks.all"
# 	],
# 	"daily": [
# 		"nhk.tasks.daily"
# 	],
# 	"hourly": [
# 		"nhk.tasks.hourly"
# 	],
# 	"weekly": [
# 		"nhk.tasks.weekly"
# 	],
# 	"monthly": [
# 		"nhk.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "nhk.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "nhk.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "nhk.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["nhk.utils.before_request"]
# after_request = ["nhk.utils.after_request"]

# Job Events
# ----------
# before_job = ["nhk.utils.before_job"]
# after_job = ["nhk.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"nhk.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Fixtures
# ---------
# The technician flow's permissions and master data lived only in the database
# until now, which meant a fresh `bench new-site` + `install-app nhk` produced a
# system with no technician permissions and no payout slabs. Exporting them here
# makes a dev site match production.
#
# Admin Settings is a Single and cannot be exported as a fixture; its charge slab
# table is seeded by patches/v1_0/seed_technician_charges.py instead.

fixtures = [
	{
		"dt": "Custom DocPerm",
		"filters": [
			[
				"parent",
				"in",
				[
					"Technician Visit Entry",
					"Technician Details",
					"Technician Category",
					"Technician Visit Payment",
				],
			]
		],
	},
	{
		"dt": "Role",
		"filters": [["name", "in", ["NHK Technician", "NHK Admin", "NHK Super admin", "NHK Sales Person"]]],
	},
	{"dt": "Technician Category"},
]


