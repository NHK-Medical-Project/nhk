"""Put the Technician Visits block at the top of the NHK Technician workspace.

Decided 2026-09-30: the office acts on open visits from the workspace --
Rejected, Pending, Accepted, with Reassign and Reschedule on each -- instead of
only counting them in number cards.

The Custom HTML Block record only loads `nhk/public/js/technician_visits_block.js`
and hands it the block's shadow root, so the block's code is versioned here and
this patch never needs rerunning to change it. Safe to run again: it rewrites
the block's script and adds the block to the workspace only once.
"""

import json

import frappe

BLOCK = "Technician Visits"
WORKSPACE = "NHK Technician"

SCRIPT = """frappe.require("/assets/nhk/js/technician_visits_block.js", () =>
	nhk.technician_visits_block.render(root_element)
);"""


def execute():
	exists = frappe.db.exists("Custom HTML Block", BLOCK)
	block = frappe.get_doc("Custom HTML Block", BLOCK) if exists else frappe.new_doc("Custom HTML Block")
	block.update({"html": "<div></div>", "script": SCRIPT, "style": "", "private": 0})
	if exists:
		block.save(ignore_permissions=True)
	else:
		block.insert(ignore_permissions=True, set_name=BLOCK)

	if not frappe.db.exists("Workspace", WORKSPACE):
		return
	workspace = frappe.get_doc("Workspace", WORKSPACE)
	content = json.loads(workspace.content or "[]")
	if any(b.get("type") == "custom_block" and b.get("data", {}).get("custom_block_name") == BLOCK for b in content):
		return

	# First on the page: straight after the workspace's own heading, if it has one.
	at = 1 if content and content[0].get("type") == "header" else 0
	content[at:at] = [
		{"id": frappe.generate_hash(length=10), "type": "custom_block",
		 "data": {"custom_block_name": BLOCK, "col": 12}},
		{"id": frappe.generate_hash(length=10), "type": "spacer", "data": {"col": 12}},
	]
	workspace.content = json.dumps(content)
	if not any(row.custom_block_name == BLOCK for row in workspace.custom_blocks):
		workspace.append("custom_blocks", {"custom_block_name": BLOCK, "label": BLOCK})
	workspace.save(ignore_permissions=True)
