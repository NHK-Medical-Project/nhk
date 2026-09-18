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
		frappe.db.commit()
		return leaked


def run(module, site="nhk.local"):
	frappe.init(site=site)
	frappe.connect()

	tests = sorted((n, f) for n, f in vars(module).items() if n.startswith("test_"))
	passed = failed = 0

	for name, fn in tests:
		cleanup = Cleanup()
		try:
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
