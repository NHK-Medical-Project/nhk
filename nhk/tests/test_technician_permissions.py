"""Pin the row-level containment model for Technician Visit Entry.

Read-only. Run against a real site:

    cd ~/bench-nhk/sites && ../env/bin/python ../apps/nhk/nhk/tests/test_technician_permissions.py

Why this exists
---------------
A technician sees only their own visits, but *not* for the reason it looks like.
The `NHK Technician` DocPerm row with `read=1, if_owner=0` is at `permlevel=2`,
which governs field access, not rows. At `permlevel=0` the only technician row is
`read=1, write=1, if_owner=1`, so Frappe applies an owner constraint and ORs in
shared documents (`db_query.py:build_match_conditions`).

That is a load-bearing subtlety. Anyone "fixing" the permlevel-2 row by setting
if_owner on it, or adding a blanket read row, silently exposes all visit entries.
These assertions fail loudly if that happens.
"""

import sys

import frappe

DOCTYPE = "Technician Visit Entry"


def _a_real_technician():
	"""A technician user that holds no blanket-read role."""
	blanket = _blanket_read_roles()
	for row in frappe.get_all("Technician Details", fields=["name", "user_mail_id"]):
		user = row.user_mail_id
		if not user or not frappe.db.exists("User", user):
			continue
		if blanket & set(frappe.get_roles(user)):
			continue
		return row.name, user
	raise AssertionError("no technician user without a blanket-read role")


def _blanket_read_roles():
	meta = frappe.get_meta(DOCTYPE)
	return {p.role for p in meta.permissions if p.permlevel == 0 and p.read and not p.if_owner}


def test_permlevel_zero_has_no_blanket_technician_read():
	assert "NHK Technician" not in _blanket_read_roles(), (
		"NHK Technician gained blanket row-read on %s -- every technician can now "
		"read every visit entry" % DOCTYPE
	)


def test_technician_row_still_uses_if_owner():
	meta = frappe.get_meta(DOCTYPE)
	rows = [p for p in meta.permissions if p.role == "NHK Technician" and p.permlevel == 0]
	assert len(rows) == 1, "expected exactly one permlevel-0 NHK Technician row, got %d" % len(rows)
	assert rows[0].if_owner, "the permlevel-0 NHK Technician row lost if_owner -- containment is gone"


def test_technician_lists_their_own_visits_and_only_read_ones_they_handed_over():
	"""Everything they can see is theirs, or a visit that used to be.

	This asserted `visible == theirs` until reassignment landed. A reassignment now
	downgrades the previous technician's DocShare to read rather than deleting it --
	a deliberate decision, recorded in
	`.scratch/technician-assignment/spec.md`: they may still have the patient on the
	phone and should be able to see what they were asked to do.

	So a handed-over visit stays *readable* by whoever held it before. What must
	still hold is that they cannot change it, and that it does not come back in the
	app: `my_jobs` and `my_visits` filter on `technician_id` + `technician_user_id`,
	not on the share.
	"""
	_, user = _a_real_technician()
	frappe.set_user(user)
	try:
		visible = {r.name for r in frappe.get_list(DOCTYPE, fields=["name"], limit_page_length=0)}
		theirs = {
			r.name
			for r in frappe.get_list(
				DOCTYPE, fields=["name"], filters={"technician_user_id": user}, limit_page_length=0
			)
		}
		assert visible, "technician %s can see no visits at all -- shares may be broken" % user
		assert theirs <= visible, "technician %s cannot see %d of their own visits" % (
			user,
			len(theirs - visible),
		)

		for name in visible - theirs:
			write = frappe.db.get_value(
				"DocShare",
				{"share_doctype": DOCTYPE, "share_name": name, "user": user},
				"write",
			)
			assert write == 0, (
				"technician %s can still write visit %s, which is no longer theirs" % (user, name)
			)
	finally:
		frappe.set_user("Administrator")


def test_a_handed_over_visit_does_not_come_back_in_the_app():
	"""The read share must not put a reassigned job back on someone's phone."""
	from nhk.api import staff

	_, user = _a_real_technician()
	frappe.set_user(user)
	try:
		visible = {r.name for r in frappe.get_list(DOCTYPE, fields=["name"], limit_page_length=0)}
		theirs = {
			r.name
			for r in frappe.get_list(
				DOCTYPE, fields=["name"], filters={"technician_user_id": user}, limit_page_length=0
			)
		}
		handed_over = visible - theirs
		if not handed_over:
			return

		duty = staff.start_duty()
		try:
			listed = {j["name"] for j in staff.my_visits(limit=0)}
		finally:
			staff.end_duty()
			frappe.delete_doc("Technician Check In", duty["name"], force=True, ignore_permissions=True)

		leaked = handed_over & listed
		assert not leaked, "reassigned visits are still in this technician's app list: %s" % (
			", ".join(sorted(leaked))
		)
	finally:
		frappe.set_user("Administrator")


def test_technician_cannot_read_a_foreign_visit():
	_, user = _a_real_technician()
	foreign = frappe.db.sql(
		"""select name from `tabTechnician Visit Entry`
		   where ifnull(technician_user_id, '') not in ('', %s) limit 1""",
		user,
	)
	assert foreign, "no foreign visit to test against"
	foreign = foreign[0][0]

	frappe.set_user(user)
	try:
		assert not frappe.has_permission(DOCTYPE, "read", doc=foreign)
		assert not frappe.has_permission(DOCTYPE, "write", doc=foreign)
	finally:
		frappe.set_user("Administrator")


def test_guards_reject_non_technicians():
	from nhk.api.guards import NotATechnician, current_technician

	for user in ("Administrator", "Guest"):
		try:
			current_technician(user)
		except NotATechnician:
			pass
		else:
			raise AssertionError("current_technician(%r) should have been rejected" % user)


def main():
	frappe.init(site=sys.argv[1] if len(sys.argv) > 1 else "nhk.local")
	frappe.connect()

	failures = 0
	for name, fn in sorted(globals().items()):
		if not name.startswith("test_"):
			continue
		try:
			fn()
		except AssertionError as exc:
			failures += 1
			print("FAIL %s\n     %s" % (name, exc))
		else:
			print("pass %s" % name)

	print("\n%s" % ("all passed" if not failures else "%d FAILED" % failures))
	return 1 if failures else 0


if __name__ == "__main__":
	raise SystemExit(main())
