"""Guards on which row MemberFinancialHistoryManager actually locks (#424).

``add_or_update_entry`` locks the parent row before it reloads and rewrites the
child table, so two concurrent writers cannot interleave read-modify-write and
lose an entry. The lock used to be spelled with the table hard-coded::

    SELECT name FROM `tabMember` WHERE name = %s FOR UPDATE

but the manager is constructed with whatever document the caller has, and the
Mollie webhook builds it with a **Donor**
(``webhook_wrapper_service_unified._update_donor_record``). A Donor name is not
a Member name, so that statement matched zero rows and took no lock on anything
the manager was about to write -- silently, because a ``FOR UPDATE`` that
matches nothing is not an error.

That is why these tests probe from a SECOND database connection rather than
reading the source or counting queries: the only difference between a lock that
was taken and one that was not is whether somebody else can still take it.
#411 removed this manager's internal commit, so the lock now lives to the end of
the caller's transaction -- which makes a correctly scoped one matter more.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.member_financial_history_manager import (
    MemberFinancialHistoryManager,
    get_payment_history_manager,
)

# Long enough that a busy CI runner does not report a slow lock acquisition as
# "not locked", short enough that a genuinely free row does not stall the suite.
LOCK_PROBE_TIMEOUT = 3


def row_is_locked_from_another_connection(doctype: str, name: str) -> bool:
    """Return True if `doctype`/`name` cannot be locked from a second connection.

    Opens its own connection -- deliberately NOT frappe.db, which is the
    transaction under test and would happily re-take its own locks -- and tries
    the same ``SELECT ... FOR UPDATE``. Error 1205 (lock wait timeout) means
    somebody else holds it; an immediate result means nobody does.

    The row must be COMMITTED before this is called: an uncommitted INSERT holds
    an implicit exclusive lock of its own, which would make every probe return
    True and every assertion below pass vacuously.
    """
    # frappe.db opens it, so the site's own driver and credentials are used --
    # this bench runs mysqlclient, and hand-rolling a pymysql connection here
    # worked only by accident of which driver happened to be installed.
    conn = frappe.db.create_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SET SESSION innodb_lock_wait_timeout = %s", (LOCK_PROBE_TIMEOUT,))
        try:
            cursor.execute(f"SELECT name FROM `tab{doctype}` WHERE name = %s FOR UPDATE", (name,))
            cursor.fetchall()
            return False
        except Exception as e:
            # 1205 ER_LOCK_WAIT_TIMEOUT -- somebody else holds the row.
            if e.args and e.args[0] == 1205:
                return True
            raise
    finally:
        conn.rollback()
        conn.close()


class TestHistoryManagerLocksTheRowItRewrites(VereningingenTestCase):
    def _committed(self, doc):
        """Insert `doc` and commit it, so the probe's connection can see it."""
        doc.insert()
        frappe.db.commit()
        self.track_doc(doc.doctype, doc.name)
        self.addCleanup(self._drop, doc.doctype, doc.name)
        return doc

    def _drop(self, doctype, name):
        """Delete and commit -- the row is durable, and the commit also releases
        whatever row lock the test itself left open."""
        if frappe.db.exists(doctype, name):
            frappe.delete_doc(doctype, name, force=True)
        frappe.db.commit()

    def _donor(self):
        return self._committed(
            frappe.get_doc(
                {
                    "doctype": "Donor",
                    "donor_name": f"LockScope {frappe.generate_hash(length=6)}",
                    "donor_type": "Individual",
                    "donor_email": f"lockscope-{frappe.generate_hash(length=8)}@example.invalid",
                }
            )
        )

    def _member(self):
        return self._committed(
            frappe.get_doc(
                {
                    "doctype": "Member",
                    "first_name": "LockScope",
                    "last_name": f"Member{frappe.generate_hash(length=6)}",
                    "email": f"lockscope-{frappe.generate_hash(length=8)}@example.invalid",
                    "birth_date": "1990-01-01",
                }
            )
        )

    def test_the_probe_tells_a_locked_row_from_a_free_one(self):
        """The instrument, before anything is concluded with it.

        Without this control, "the donor row is locked" and "the probe reports
        True for everything" look identical.
        """
        locked = self._donor()
        free = self._donor()

        self.assertFalse(
            row_is_locked_from_another_connection("Donor", locked.name),
            "nothing has locked this row yet, so the probe is reporting a lock that is not there",
        )

        frappe.db.sql("SELECT name FROM `tabDonor` WHERE name = %s FOR UPDATE", (locked.name,))

        self.assertTrue(
            row_is_locked_from_another_connection("Donor", locked.name),
            "the probe cannot see a lock this test just took itself, so it cannot "
            "be trusted to report the manager's",
        )
        self.assertFalse(
            row_is_locked_from_another_connection("Donor", free.name),
            "the probe reports an unrelated, unlocked row as locked -- it is not "
            "discriminating between rows",
        )

    def test_a_donor_history_write_locks_the_donor_row(self):
        """#424. The Mollie webhook path, which took no lock at all."""
        donor = self._donor()

        manager = MemberFinancialHistoryManager(donor, "donor_history", max_entries=30)
        wrote = manager.add_or_update_entry(
            entry_id="DONAT-LOCKSCOPE-0001",
            entry_builder=lambda: {
                # Matches entry_id, so a link/reqd check gained by Donation
                # History later would fail this test loudly rather than quietly.
                "donation_reference": "DONAT-LOCKSCOPE-0001",
                "donation_date": frappe.utils.nowdate(),
                "donation_amount": 25.0,
                "donation_status": "One-time",
                "paid": 1,
            },
            id_field_name="donation_reference",
        )
        self.assertTrue(wrote, "the history write itself failed, so this proves nothing about locking")

        self.assertTrue(
            row_is_locked_from_another_connection("Donor", donor.name),
            f"Donor {donor.name} is still lockable by another connection after the "
            "history manager rewrote its donor_history. The manager locked some other "
            "table's row (or none), so two concurrent Mollie webhooks for the same "
            "donor can interleave read-modify-write and lose an entry (#424).",
        )

    def test_a_member_payment_history_write_locks_the_member_row(self):
        """The path that always worked -- pinned so the fix cannot trade one for the other."""
        member = self._member()

        manager = get_payment_history_manager(member)
        wrote = manager.add_or_update_entry(
            "ACC-SINV-LOCKSCOPE-0001",
            lambda: {
                "invoice": "ACC-SINV-LOCKSCOPE-0001",
                "posting_date": frappe.utils.nowdate(),
                "amount": 1.0,
                "outstanding_amount": 0.0,
                "payment_status": "Paid",
                "transaction_type": "Membership Invoice",
            },
            "invoice",
        )
        self.assertTrue(wrote, "the history write itself failed, so this proves nothing about locking")

        self.assertTrue(
            row_is_locked_from_another_connection("Member", member.name),
            f"Member {member.name} is still lockable by another connection after the "
            "history manager rewrote its payment_history (#424).",
        )
