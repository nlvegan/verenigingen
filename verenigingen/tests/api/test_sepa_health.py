"""
Tests for SEPA health check endpoint.

These tests verify that the health check endpoint correctly reports
the status of SEPA infrastructure components -- including that the
"healthy"/count fields actually flip in response to real data, not
just that the response has the right shape.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from verenigingen.api.sepa_duplicate_prevention import check_redis_health


class TestSEPAHealthEndpoint(FrappeTestCase):
    """Test cases for SEPA health check endpoint."""

    def test_health_check_returns_status(self):
        """Health endpoint should return overall status and checks, and the
        overall status must be exactly 'degraded' when any sub-check is
        unhealthy, 'healthy' otherwise (not just any string)."""
        from verenigingen.api.sepa_health import get_sepa_health

        result = get_sepa_health()

        self.assertIn("status", result)
        self.assertIn("timestamp", result)
        self.assertIn("checks", result)
        self.assertIsInstance(result["timestamp"], str)

        any_unhealthy = any(not c.get("healthy", True) for c in result["checks"].values())
        expected_status = "degraded" if any_unhealthy else "healthy"
        self.assertEqual(result["status"], expected_status)

    def test_health_check_redis_reflects_real_check(self):
        """The redis sub-check must be a live view of check_redis_health() and
        frappe.conf, not a static/independent value."""
        from verenigingen.api.sepa_health import get_sepa_health

        real_redis_health = check_redis_health()
        result = get_sepa_health()

        self.assertEqual(result["checks"]["redis"]["healthy"], real_redis_health.get("healthy", False))
        self.assertEqual(
            result["checks"]["redis"]["locks_enabled"],
            bool(frappe.conf.get("use_redis_locks_for_sepa", False)),
        )

    def test_pending_batches_warning_flips_above_threshold(self):
        """pending_batches.warning must become True once more than 5 batches
        are in Draft/Generated/Submitted state (the real threshold in
        _check_pending_batches), and reflect the real count."""
        from verenigingen.api.sepa_health import get_sepa_health

        baseline = frappe.db.count(
            "Direct Debit Batch", filters={"status": ["in", ["Draft", "Generated", "Submitted"]]}
        )

        created = []
        try:
            # Create just enough Draft batches to push the count past 5. Seeded
            # directly via SQL (bypassing the doctype's "at least one real
            # invoice" validate() requirement) since only the status/count
            # query -- not batch document integrity -- is under test here.
            needed = max(0, 6 - baseline)
            now = now_datetime()
            for i in range(needed):
                name = frappe.generate_hash(length=10)
                frappe.db.sql(
                    """
                    INSERT INTO `tabDirect Debit Batch`
                        (name, creation, modified, modified_by, owner, docstatus,
                         batch_date, batch_description, currency, status, batch_type,
                         total_amount, entry_count)
                    VALUES
                        (%(name)s, %(now)s, %(now)s, %(user)s, %(user)s, 0,
                         %(today)s, %(desc)s, 'EUR', 'Draft', 'CORE', 0, 0)
                    """,
                    {
                        "name": name,
                        "now": now,
                        "user": frappe.session.user,
                        "today": frappe.utils.today(),
                        "desc": f"Health check warning test {i}",
                    },
                )
                created.append(name)

            result = get_sepa_health()
            pending = result["checks"]["pending_batches"]
            expected_count = baseline + len(created)

            self.assertEqual(pending["count"], expected_count)
            self.assertTrue(pending["healthy"])  # this check never reports unhealthy by design
            self.assertTrue(pending["warning"], "warning must be True once pending count exceeds 5")
        finally:
            if created:
                frappe.db.sql(
                    "DELETE FROM `tabDirect Debit Batch` WHERE name IN %(names)s", {"names": created}
                )

    def test_unreconciled_becomes_unhealthy_above_threshold(self):
        """unreconciled.healthy must become False once 50+ Pending Direct
        Debit Batch Invoice rows are older than 7 days (the real threshold
        in _check_unreconciled). Child rows are seeded directly (bulk SQL)
        rather than via the full Member/Membership/Invoice factory chain,
        since only the count query -- not document integrity -- is under
        test here.
        """
        from verenigingen.api.sepa_health import get_sepa_health

        threshold = 50
        baseline = frappe.db.count(
            "Direct Debit Batch Invoice",
            filters={"status": "Pending", "creation": ["<", add_days(now_datetime(), -7)]},
        )

        # A parent batch to attach the synthetic rows to. Seeded via SQL (like
        # the child rows below) since the doctype's validate() requires at
        # least one real, existing Sales Invoice line -- irrelevant to this
        # count-only check.
        batch_name = frappe.generate_hash(length=10)
        now = now_datetime()
        frappe.db.sql(
            """
            INSERT INTO `tabDirect Debit Batch`
                (name, creation, modified, modified_by, owner, docstatus,
                 batch_date, batch_description, currency, status, batch_type,
                 total_amount, entry_count)
            VALUES
                (%(name)s, %(now)s, %(now)s, %(user)s, %(user)s, 0,
                 %(today)s, 'Health check unreconciled test parent', 'EUR', 'Draft',
                 'CORE', 0, 0)
            """,
            {
                "name": batch_name,
                "now": now,
                "user": frappe.session.user,
                "today": frappe.utils.today(),
            },
        )

        needed = max(0, (threshold + 1) - baseline)
        old_creation = add_days(now_datetime(), -10)
        row_names = []
        try:
            for i in range(needed):
                row_name = frappe.generate_hash(length=10)
                row_names.append(row_name)
                frappe.db.sql(
                    """
                    INSERT INTO `tabDirect Debit Batch Invoice`
                        (name, creation, modified, modified_by, owner, docstatus,
                         parent, parentfield, parenttype, idx, status, amount, currency)
                    VALUES
                        (%(name)s, %(creation)s, %(creation)s, %(user)s, %(user)s, 0,
                         %(parent)s, 'invoices', 'Direct Debit Batch', %(idx)s, 'Pending', 25.0, 'EUR')
                    """,
                    {
                        "name": row_name,
                        "creation": old_creation,
                        "user": frappe.session.user,
                        "parent": batch_name,
                        "idx": i + 1,
                    },
                )

            result = get_sepa_health()
            unreconciled = result["checks"]["unreconciled"]
            expected_count = baseline + len(row_names)

            self.assertEqual(unreconciled["count"], expected_count)
            self.assertEqual(unreconciled["threshold"], threshold)
            self.assertFalse(
                unreconciled["healthy"],
                f"unreconciled must be unhealthy once count ({expected_count}) >= threshold ({threshold})",
            )
            # An unhealthy sub-check must flip the overall status to "degraded"
            # (get_sepa_health's overall_healthy aggregation).
            self.assertEqual(result["status"], "degraded")
        finally:
            if row_names:
                frappe.db.sql(
                    "DELETE FROM `tabDirect Debit Batch Invoice` WHERE name IN %(names)s",
                    {"names": row_names},
                )
            frappe.db.sql("DELETE FROM `tabDirect Debit Batch` WHERE name=%s", batch_name)

    def _create_upload_log(self, batch_name):
        """Factory helper: seed one SEPA Batch Upload Log row for the given batch.
        The doctype is immutable (on_trash blocks deletion for audit integrity,
        even with ignore_permissions), so the row is left for FrappeTestCase's
        transaction rollback to undo -- consistent with the rest of this suite."""
        log = frappe.get_doc(
            {
                "doctype": "SEPA Batch Upload Log",
                "batch_name": batch_name,
                "batch_status": "Uploaded",
                "upload_time": now_datetime(),
                "uploaded_by": frappe.session.user,
                "file_name": "health_check_test.xml",
            }
        )
        log.insert(ignore_permissions=True)
        return log

    def test_recent_uploads_count_reflects_real_upload_log(self):
        """recent_uploads.count_24h must increase when a real SEPA Batch
        Upload Log with upload_time in the last 24h is created."""
        from verenigingen.api.sepa_health import get_sepa_health

        before = get_sepa_health()["checks"]["recent_uploads"]["count_24h"]

        # A SEPA Batch Upload Log requires an existing Direct Debit Batch
        # (Batch Name is mandatory); seed one via SQL as in the other tests
        # above -- only the upload_time-based count is under test here.
        batch_name = frappe.generate_hash(length=10)
        now = now_datetime()
        frappe.db.sql(
            """
            INSERT INTO `tabDirect Debit Batch`
                (name, creation, modified, modified_by, owner, docstatus,
                 batch_date, batch_description, currency, status, batch_type,
                 total_amount, entry_count)
            VALUES
                (%(name)s, %(now)s, %(now)s, %(user)s, %(user)s, 0,
                 %(today)s, 'Health check recent-uploads test parent', 'EUR', 'Draft',
                 'CORE', 0, 0)
            """,
            {
                "name": batch_name,
                "now": now,
                "user": frappe.session.user,
                "today": frappe.utils.today(),
            },
        )

        self._create_upload_log(batch_name)

        after = get_sepa_health()["checks"]["recent_uploads"]["count_24h"]
        self.assertEqual(after, before + 1)
