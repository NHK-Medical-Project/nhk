"""Minimal runner for tests that need a real site.

Frappe's own runner wants a disposable test site; this app is developed against a
restored production snapshot, so instead each test creates the records it needs
and the harness deletes them afterwards. Rollback is not enough on its own --
`change_status` commits mid-call.
"""

import traceback

import frappe


class Cleanup:
	"""Records to remove once a test finishes, newest first."""

	def __init__(self):
		self._records: list[tuple[str, str]] = []
		self._values: list[tuple[str, str, str, object]] = []
		self._values_after: list[tuple[str, str, str, object]] = []
		self._rows: list[tuple[str, str]] = []

	def add(self, doctype: str, name: str) -> str:
		self._records.append((doctype, name))
		return name

	def restore(self, doctype: str, name: str, fieldname: str) -> None:
		"""Snapshot a field on a record this test is about to change.

		Deleting what a test created is not enough once a test can also *edit*
		something that was already here. Reassignment writes the technician back
		onto the Sales Order the visit belongs to, and that order is real: it was
		in the snapshot this site was restored from. Take its value now and put
		it back afterwards.
		"""
		self._values.append((doctype, name, fieldname, frappe.db.get_value(doctype, name, fieldname)))

	def add_row(self, doctype: str, name: str) -> str:
		"""A child row this test wrote directly, to be deleted directly.

		`delete_doc` works on documents, not on child rows, and deleting through
		the parent would mean saving it -- which for NHK User resets passwords
		(`nhk.api.devices`).
		"""
		self._rows.append((doctype, name))
		return name

	def set_aside_real_checkins(self, technicians) -> None:
		"""Close the technicians' real open check-ins for the test, and reopen
		them afterwards.

		Fixtures put the pilot technicians on and off duty. When a real
		technician was on duty, `start_duty` handed the fixture *his* check-in,
		and the clean-up deleted it: on 2026-09-29 the pilot's duty for the day
		vanished mid-afternoon while he was working. Now a test never sees a real
		check-in at all -- they are closed here, restored in `run()`, and every
		check-in a test touches is one it made.
		"""
		now = frappe.utils.now_datetime()
		for name in frappe.get_all(
			"Technician Check In",
			filters={"technician_id": ("in", list(technicians)), "closed_at": ("is", "not set")},
			pluck="name",
		):
			self.restore("Technician Check In", name, "closed_at")
			self.restore("Technician Check In", name, "close_reason")
			frappe.db.set_value("Technician Check In", name,
								{"closed_at": now, "close_reason": "Auto closed"},
								update_modified=False)
		frappe.db.commit()

	def restore_after_delete(self, doctype: str, name: str, fieldname: str) -> None:
		"""Snapshot a field that *deleting* this test's records changes, and put it
		back after the deletes.

		`TechnicianVisitEntry.on_trash` subtracts a visit's charge from its
		technician's `Technician Details.total_amount_settled`. Every fixture visit
		is priced when it is created, so every clean-up quietly lowered a real
		technician's total: by 2026-09-28 the pilot technician stood at -227,040
		from 2,483 deleted fixtures. A snapshot restored *before* the deletes
		cannot undo that; this one runs after them.
		"""
		key = (doctype, name, fieldname)
		if any(v[:3] == key for v in self._values_after):
			return
		self._values_after.append((*key, frappe.db.get_value(doctype, name, fieldname)))

	def run(self) -> list[str]:
		"""Put edited fields back, delete created records, report what would not go.

		Failures are reported rather than swallowed: a test that leaves rows
		behind pollutes a site holding real data, and a silent leak is how you
		end up debugging a fixture three weeks later.
		"""
		leaked = []
		for doctype, name, fieldname, value in reversed(self._values):
			try:
				frappe.db.set_value(doctype, name, fieldname, value, update_modified=False)
			except Exception as exc:
				leaked.append("%s %s.%s (%s)" % (doctype, name, fieldname, type(exc).__name__))

		for doctype, name in reversed(self._records):
			try:
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True, delete_permanently=True)
			except Exception as exc:
				leaked.append("%s %s (%s)" % (doctype, name, type(exc).__name__))

		for doctype, name in self._rows:
			try:
				frappe.db.delete(doctype, {"name": name})
			except Exception as exc:
				leaked.append("%s %s (%s)" % (doctype, name, type(exc).__name__))

		for doctype, name, fieldname, value in self._values_after:
			try:
				frappe.db.set_value(doctype, name, fieldname, value, update_modified=False)
			except Exception as exc:
				leaked.append("%s %s.%s (%s)" % (doctype, name, fieldname, type(exc).__name__))
		frappe.db.commit()
		return leaked


#: The technicians the fixtures use. They are real people with real phones; see
#: `Cleanup.set_aside_real_checkins`.
REAL_TECHNICIANS = ("NHK-TEC-002", "NHK-TEC-003")


def run(module, site="nhk.local"):
	frappe.init(site=site)
	frappe.connect()
	# Fixture visits are assigned to real technicians. Without this, every run
	# would push "New job assigned" to their phones (`nhk.api.notify`); the
	# notification tests switch it off themselves, with the sender replaced.
	frappe.flags.nhk_mute_notifications = True

	tests = sorted((n, f) for n, f in vars(module).items() if n.startswith("test_"))
	passed = failed = 0

	for name, fn in tests:
		cleanup = Cleanup()
		try:
			cleanup.set_aside_real_checkins(REAL_TECHNICIANS)
			fn(cleanup)
		except Exception as exc:
			failed += 1
			print("FAIL %s\n     %s: %s" % (name, type(exc).__name__, exc))
			if not isinstance(exc, AssertionError):
				print("".join("     " + l for l in traceback.format_exc(limit=4).splitlines(True)[-6:]))
		else:
			passed += 1
			print("pass %s" % name)
		finally:
			frappe.set_user("Administrator")
			leaked = cleanup.run()
			if leaked:
				failed += 1
				print("LEAK %s left records behind: %s" % (name, ", ".join(leaked)))

	print("\n%d passed, %d failed" % (passed, failed))
	return 1 if failed else 0
