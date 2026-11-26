"""#3201: Member deletion must not turn 1213/1205 into a logged-and-continue.

``MemberCleanupService.handle_member_deletion`` (reached from ``Member.on_trash``) wrapped each
child cleanup in ``except Exception`` and carried on. A deadlock / lock-wait timeout raised inside
one of them therefore read as an ordinary cleanup failure, and the later steps (and the Member row
delete itself) ran against a transaction the server may already have rolled back.

The lock error is injected at the DRIVER, below every swallow layer: ``frappe.db.execute_query``
raises a real ``OperationalError`` 1213/1205 and frappe's own dispatch converts it into
``QueryDeadlockError`` / ``QueryTimeoutError``, as in production (same technique as #2409). The
entry point is ``frappe.delete_doc("Member", ...)``. Controls: the SAME statement failing with an
ordinary error (2013 lost connection) is still tolerated as before, and an unfaulted deletion
still removes the member.
"""

import traceback
from unittest.mock import patch

import frappe

from verenigingen.services.member.lifecycle.member_cleanup_service import get_member_cleanup_service
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.dues_schedule_invoice_fixtures import make_referenceable_dues_schedule

LOCK_ERRNOS = {frappe.QueryDeadlockError: 1213, frappe.QueryTimeoutError: 1205}
ORDINARY_ERRNO = 2013

# (handler, statement the handler issues, frame that must be on the stack). One member carries a
# row for every handler, so each statement is really issued on the way through. Pinning the frame to
# handle_member_deletion keeps Member's OWN later deletes (child tables, the row) out of the test.
SERVICE = "handle_member_deletion"
HANDLERS = (
    ("dues schedule", "DELETE FROM `tabMembership Dues Schedule`", SERVICE),
    ("membership", "DELETE FROM `tabMembership` ", SERVICE),
    ("sepa mandate", "DELETE FROM `tabSEPA Mandate` ", SERVICE),
    ("sales invoice reference", "UPDATE `tabSales Invoice`", SERVICE),
    ("chapter member", "DELETE FROM `tabChapter Member` ", SERVICE),
    ("customer", "FROM `tabPayment Entry`", SERVICE),
    # Customer deletion touches Address/Dynamic Link too, so pin this one to the address helper.
    ("address unlink", "tabDynamic Link", "_unlink_member_from_address"),
    ("child table loop", "DELETE FROM `tabMember Payment History`", SERVICE),
)


class _DriverFault:
    """Fail the cursor with a real driver OperationalError for statements containing ``needle``.

    Statements issued while a failure is being RECORDED (frames named log_error) are not failed, so
    the error cannot escape from inside a handler's own logging and fake a re-raise."""

    def __init__(self, needle, errno, in_frame=None):
        self.needle, self.errno, self.in_frame = needle, errno, in_frame
        self.hits = 0

    def __enter__(self):
        real = frappe.db.execute_query

        def execute_query(query, values=None):
            names = [f.name for f in traceback.extract_stack()]
            if (
                self.needle in str(query)
                and "log_error" not in names
                and (self.in_frame is None or self.in_frame in names)
            ):
                self.hits += 1
                raise frappe.db.OperationalError(self.errno, f"injected {self.errno} for #3201")
            return real(query, values)

        self._patch = patch.object(frappe.db, "execute_query", execute_query)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        return False


class TestMemberCleanupLockErrors3201(EnhancedTestCase):
    def _loop_gate_open(self):
        """The child-table loop is gated by ``frappe.db.table_exists("tab<Name>")``, which asks for
        ``tabtab<Name>`` and is therefore False in production (the loop body never runs; filed
        separately). This opens that gate so the handler behind it can be exercised at all; the
        fault itself is still a real driver error."""
        real = frappe.db.table_exists
        return patch.object(  # Mock justified: Infrastructure - dead gate, see docstring
            frappe.db,
            "table_exists",
            lambda doctype, cached=True: real(doctype.removeprefix("tab"), cached),
        )

    def _member_with_every_child(self, tag):
        member = self.create_test_member(
            first_name="Lock", last_name=f"Err{tag}", email=f"lock.err3201.{tag}@example.com"
        )
        self.assertTrue(member.customer, "the customer handler needs a Customer to act on")
        make_referenceable_dues_schedule(self, member)
        self.create_test_membership(member_name=member.name, membership_type_name=None)
        self.create_test_sepa_mandate(member_name=member.name)
        chapter = self.create_test_chapter()
        chapter.append(
            "members",
            {"member": member.name, "status": "Active", "enabled": 1, "join_date": frappe.utils.today()},
        )
        chapter.save()
        address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": f"Lock Err {tag}",
                "address_line1": "1 Test Street",
                "city": "Test City",
                "pincode": "1234AB",
                "country": "Netherlands",
                "address_type": "Personal",
                "links": [{"link_doctype": "Member", "link_name": member.name}],
            }
        ).insert()
        member.reload()
        member.primary_address = address.name
        member.save(ignore_version=True)
        member.reload()
        return member

    def test_lock_error_in_any_handler_aborts_member_deletion(self):
        for label, needle, in_frame in HANDLERS:
            for error, errno in LOCK_ERRNOS.items():
                with self.subTest(handler=label, error=error.__name__):
                    member = self._member_with_every_child(f"{label[:4]}{errno}".replace(" ", ""))
                    with self._loop_gate_open(), _DriverFault(needle, errno, in_frame) as fault:
                        with self.assertRaises(error):
                            frappe.delete_doc("Member", member.name, force=True)
                    self.assertGreaterEqual(fault.hits, 1, "the fault never fired: nothing was tested")
                    self.assertTrue(
                        frappe.db.exists("Member", member.name),
                        "the Member row must survive: the delete was abandoned, not resumed",
                    )

    def test_ordinary_error_in_any_handler_is_still_tolerated(self):
        for label, needle, in_frame in HANDLERS:
            with self.subTest(handler=label):
                member = self._member_with_every_child(f"o{label[:4]}".replace(" ", ""))
                with self._loop_gate_open(), _DriverFault(needle, ORDINARY_ERRNO, in_frame) as fault:
                    get_member_cleanup_service().handle_member_deletion(member)
                self.assertGreaterEqual(fault.hits, 1, "the fault never fired: nothing was tested")

    def test_clean_member_deletion_still_removes_everything(self):
        member = self._member_with_every_child("clean")
        customer, mandate_count = member.customer, frappe.db.count("SEPA Mandate", {"member": member.name})
        self.assertGreater(mandate_count, 0)
        frappe.delete_doc("Member", member.name, force=True)
        self.assertFalse(frappe.db.exists("Member", member.name))
        self.assertFalse(frappe.db.exists("Customer", customer))
        self.assertEqual(frappe.db.count("SEPA Mandate", {"member": member.name}), 0)
        self.assertEqual(frappe.db.count("Chapter Member", {"member": member.name}), 0)
        self.assertEqual(frappe.db.count("Membership", {"member": member.name}), 0)
