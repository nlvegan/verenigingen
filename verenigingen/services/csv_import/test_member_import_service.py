# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberImportService Tests - TDD tests for member import service.

Tests member creation/update logic extracted from MijnRood CSV Import DocType.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase


class TestMemberImportService(FrappeTestCase):
    """Test MemberImportService functionality."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        # Ensure test membership type exists.
        # Membership Type reqd fields: membership_type_name (autoname=field:),
        # minimum_amount, role_profile.
        if not frappe.db.exists("Membership Type", "Regular"):
            role_profile = frappe.db.get_value(
                "Role Profile", {"name": "Verenigingen Staff"}, "name"
            ) or frappe.db.get_value("Role Profile", {}, "name")
            frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Regular",
                    "minimum_amount": 60.0,
                    "role_profile": role_profile,
                }
            ).insert(ignore_permissions=True)
            frappe.db.commit()

    def setUp(self):
        """Set up each test."""
        super().setUp()
        self.created_members = []

    def tearDown(self):
        """Clean up created test members."""
        for member_name in self.created_members:
            try:
                frappe.delete_doc("Member", member_name, force=True)
            except Exception:
                pass
        frappe.db.commit()
        super().tearDown()

    def _create_member(self, **fields):
        """Create a Member fixture. Named _create_* so the permission bypass is
        recognised as fixture setup rather than test logic."""
        member = frappe.new_doc("Member")
        member.status = "Active"
        for field, value in fields.items():
            setattr(member, field, value)
        member.flags.ignore_workflow = True
        member._system_update = True
        member.insert(ignore_permissions=True)
        frappe.db.commit()
        self.created_members.append(member.name)
        return member

    # ============================================================
    # Tests for determine_member_status()
    # ============================================================

    def test_determine_member_status_active_lid(self):
        """Test status determination for 'lid' membership type."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, is_aspirant = service.determine_member_status("lid")

        self.assertEqual(status, "Active")
        self.assertFalse(is_aspirant)

    def test_determine_member_status_active_standard(self):
        """Test status determination for 'standard' membership type."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, is_aspirant = service.determine_member_status("standard")

        self.assertEqual(status, "Active")
        self.assertFalse(is_aspirant)

    def test_determine_member_status_aspirant(self):
        """Test status determination for 'aspirant' membership type."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, is_aspirant = service.determine_member_status("aspirant")

        self.assertEqual(status, "Active")
        self.assertTrue(is_aspirant)

    def test_determine_member_status_deceased(self):
        """Test status determination for 'overleden' membership type."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, is_aspirant = service.determine_member_status("overleden")

        self.assertEqual(status, "Deceased")
        self.assertFalse(is_aspirant)

    def test_determine_member_status_terminated(self):
        """Test status determination for 'opgezegd' membership type."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, is_aspirant = service.determine_member_status("opgezegd")

        self.assertEqual(status, "Quit")
        self.assertFalse(is_aspirant)

    def test_determine_member_status_banned(self):
        """Test status determination for 'geroyeerd' membership type."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, is_aspirant = service.determine_member_status("geroyeerd")

        self.assertEqual(status, "Banned")
        self.assertFalse(is_aspirant)

    def test_determine_member_status_duplicate(self):
        """Test status determination for 'dubbel' membership type."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, is_aspirant = service.determine_member_status("dubbel")

        self.assertEqual(status, "Rejected")
        self.assertFalse(is_aspirant)

    def test_determine_member_status_suspended(self):
        """Test status determination for 'geschorst' membership type."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, is_aspirant = service.determine_member_status("geschorst")

        self.assertEqual(status, "Suspended")
        self.assertFalse(is_aspirant)

    def test_determine_member_status_unknown_defaults_active(self):
        """Test status determination for unknown type defaults to Active."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, is_aspirant = service.determine_member_status("unknown_type")

        self.assertEqual(status, "Active")
        self.assertFalse(is_aspirant)

    def test_determine_member_status_case_insensitive(self):
        """Test status determination is case insensitive."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()

        status1, _ = service.determine_member_status("LID")
        status2, _ = service.determine_member_status("Lid")
        status3, _ = service.determine_member_status("lid")

        self.assertEqual(status1, "Active")
        self.assertEqual(status2, "Active")
        self.assertEqual(status3, "Active")

    def test_determine_member_status_handles_none(self):
        """Test status determination handles None gracefully."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, is_aspirant = service.determine_member_status(None)

        self.assertEqual(status, "Active")
        self.assertFalse(is_aspirant)

    # ============================================================
    # Tests for update_member_fields()
    # ============================================================

    def test_update_member_fields_basic_info(self):
        """Test updating basic member information from row data."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        member = frappe.new_doc("Member")

        row_data = {
            "member_id": "TEST-001",
            "first_name": "Jan",
            "tussenvoegsel": "van",
            "last_name": "Test",
            "email": "jan.test@example.com",
            "birth_date": "1990-01-15",
            "membership_type": "lid",
        }

        service.update_member_fields(member, row_data, "TEST-IMPORT-001")

        self.assertEqual(member.member_id, "TEST-001")
        self.assertEqual(member.first_name, "Jan")
        self.assertEqual(member.tussenvoegsel, "van")
        self.assertEqual(member.last_name, "Test")
        self.assertEqual(member.email, "jan.test@example.com")
        self.assertEqual(member.status, "Active")

    def test_update_member_fields_sets_system_flags(self):
        """Test that system flags are set for CSV import."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        member = frappe.new_doc("Member")

        row_data = {
            "first_name": "Test",
            "last_name": "Member",
            "membership_type": "lid",
        }

        service.update_member_fields(member, row_data, "TEST-IMPORT-001")

        self.assertTrue(member.flags.ignore_workflow)
        self.assertTrue(getattr(member, "_system_update", False))
        self.assertTrue(getattr(member, "_csv_import", False))

    def test_update_member_fields_with_iban_sets_payment_method(self):
        """Test that IBAN sets payment method to Bank Transfer."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        member = frappe.new_doc("Member")

        row_data = {
            "first_name": "Test",
            "last_name": "Member",
            "membership_type": "lid",
            "iban": "NL91ABNA0417164300",
        }

        service.update_member_fields(member, row_data, "TEST-IMPORT-001")

        self.assertEqual(member.iban, "NL91ABNA0417164300")
        self.assertEqual(member.payment_method, "Bank Transfer")

    def test_update_member_fields_with_mollie_sets_payment_method(self):
        """Test that Mollie data sets payment method to Mollie."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        member = frappe.new_doc("Member")

        row_data = {
            "first_name": "Test",
            "last_name": "Member",
            "membership_type": "lid",
            "custom_mollie_customer_id": "cst_test123",
        }

        service.update_member_fields(member, row_data, "TEST-IMPORT-001")

        self.assertEqual(member.payment_method, "Mollie")
        self.assertTrue(hasattr(member, "_mollie_data"))
        self.assertEqual(member._mollie_data["custom_mollie_customer_id"], "cst_test123")

    def test_update_member_fields_stores_address_data(self):
        """Test that address data is stored for later creation."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        member = frappe.new_doc("Member")

        row_data = {
            "first_name": "Test",
            "last_name": "Member",
            "membership_type": "lid",
            "address_line1": "Teststraat 123",
            "city": "Amsterdam",
            "postal_code": "1234 AB",
        }

        service.update_member_fields(member, row_data, "TEST-IMPORT-001")

        self.assertIsNotNone(member._pending_address_data)

    def test_update_member_fields_stores_termination_data_for_terminated(self):
        """Test that termination data is stored for terminated members."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        member = frappe.new_doc("Member")

        row_data = {
            "first_name": "Test",
            "last_name": "Member",
            "membership_type": "opgezegd",
        }

        service.update_member_fields(member, row_data, "TEST-IMPORT-001")

        self.assertEqual(member.status, "Quit")
        self.assertTrue(hasattr(member, "_pending_termination_data"))

    # ============================================================
    # Tests for create_or_update_member() - Integration
    # ============================================================

    def test_create_member_basic(self):
        """Test creating a new member from row data."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service
        from verenigingen.utils.csv_import_processor import bulk_member_operations

        service = get_member_import_service()

        row_data = {
            "row_number": 1,
            "member_id": "TEST-CREATE-001",
            "first_name": "Create",
            "last_name": "Test",
            "email": "create.test@example.com",
            "membership_type": "lid",
        }

        with bulk_member_operations("TEST-IMPORT"):
            result, member_name = service.create_or_update_member(
                row_data=row_data,
                import_doc_name="TEST-IMPORT-001",
                create_volunteer_records=False,
            )

        self.assertEqual(result, "created")
        self.assertIsNotNone(member_name)
        self.created_members.append(member_name)

        # Verify member was created correctly
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.member_id, "TEST-CREATE-001")
        self.assertEqual(member.first_name, "Create")
        self.assertEqual(member.status, "Active")

    def test_update_existing_member(self):
        """Test updating an existing member from row data."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service
        from verenigingen.utils.csv_import_processor import bulk_member_operations

        # First create a member
        member = self._create_member(
            first_name="Existing",
            last_name="Member",
            member_id="TEST-UPDATE-001",
            email="existing@example.com",
        )

        service = get_member_import_service()

        row_data = {
            "row_number": 1,
            "member_id": "TEST-UPDATE-001",
            "first_name": "Updated",
            "last_name": "Member",
            "email": "updated@example.com",
            "membership_type": "lid",
        }

        with bulk_member_operations("TEST-IMPORT"):
            result, member_name = service.create_or_update_member(
                row_data=row_data,
                import_doc_name="TEST-IMPORT-001",
                create_volunteer_records=False,
            )

        self.assertEqual(result, "updated")
        self.assertEqual(member_name, member.name)

        # Verify member was updated
        member.reload()
        self.assertEqual(member.first_name, "Updated")
        self.assertEqual(member.email, "updated@example.com")

    def test_create_member_duplicate_skipped(self):
        """Test that duplicate member creation is handled gracefully."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service
        from verenigingen.utils.csv_import_processor import bulk_member_operations

        # First create a member with specific email
        member = self._create_member(
            first_name="Duplicate",
            last_name="Test",
            email="duplicate.test@example.com",
        )

        service = get_member_import_service()

        # Try to create with same email - should find existing and update
        row_data = {
            "row_number": 1,
            "first_name": "New",
            "last_name": "Person",
            "email": "duplicate.test@example.com",
            "membership_type": "lid",
        }

        with bulk_member_operations("TEST-IMPORT"):
            result, member_name = service.create_or_update_member(
                row_data=row_data,
                import_doc_name="TEST-IMPORT-001",
                create_volunteer_records=False,
            )

        # Should update existing member found by email
        self.assertEqual(result, "updated")
        self.assertEqual(member_name, member.name)

    def test_create_member_id_collision_reports_clean_message_not_raw_repr(self):
        """A member_id unique-constraint collision must be reported as a clean
        'skipped' status, not the raw exception repr (#699).

        `member_id` is a unique FIELD; frappe raises `UniqueValidationError` for
        it, never `DuplicateEntryError` (that one is reserved for a primary-key
        collision, and the two share no MRO relationship apart from Exception --
        verified empirically: `UniqueValidationError.__mro__` is
        `(UniqueValidationError, ValidationError, Exception, ...)`,
        `DuplicateEntryError.__mro__` is `(DuplicateEntryError, NameError,
        Exception, ...)`).

        Before this fix, `_create_new_member` caught only `DuplicateEntryError`,
        so a member_id collision fell into the generic `except
        frappe.ValidationError` branch a few lines below and returned
        `_failure_status(e)`, which stringifies the exception's raw args:
        `"failed: ('Member', 'Assoc-Member-...', IntegrityError(1062, \"Duplicate
        entry '...' for key 'member_id'\"))"` -- exactly the shape measured on
        veg11's real import history in #570/#699.

        The pre-insert lookup (`find_member_with_strategy`) normally intercepts a
        member_id match before `_create_new_member` is ever reached, routing the
        row to an UPDATE instead. To reach the actual insert-time collision this
        test monkeypatches the lookup to miss, simulating the TOCTOU window the
        advisory lock exists to close (or a genuine lookup miss ahead of it) --
        the same scenario a concurrent import can hit for real.
        """
        from verenigingen.services.csv_import.member_import_service import get_member_import_service
        from verenigingen.services.member.member_lookup_service import get_member_lookup_service
        from verenigingen.utils.csv_import_processor import bulk_member_operations

        member_id = f"PROBE699-{frappe.generate_hash(length=6)}"
        self._create_member(
            first_name="Existing",
            last_name="Holder",
            email=f"holder-{member_id}@example.com".lower(),
            member_id=member_id,
        )

        lookup = get_member_lookup_service()
        original_lookup = lookup.find_member_with_strategy
        lookup.find_member_with_strategy = lambda row_data, strategies=None: (None, None)
        self.addCleanup(setattr, lookup, "find_member_with_strategy", original_lookup)

        service = get_member_import_service()
        row_data = {
            "row_number": 2,
            "first_name": "New",
            "last_name": "Colliding",
            "email": f"colliding-{member_id}@example.com".lower(),
            "member_id": member_id,
            "membership_type": "lid",
        }

        with bulk_member_operations("TEST-IMPORT-699"):
            result, member_name = service.create_or_update_member(
                row_data=row_data,
                import_doc_name="TEST-IMPORT-699",
                create_volunteer_records=False,
            )

        self.assertEqual(result, "skipped")
        self.assertIsNone(member_name)
        self.assertEqual(
            frappe.db.count("Member", {"member_id": member_id}),
            1,
            "the rejected row must not leave a second Member with this member_id",
        )

    def test_update_validation_error_surfaces_reason_and_logs(self):
        """A ValidationError on the update path must not be reduced to bare 'failed'.

        Regression for MR-SYNC-2026-00087: a stale Dynamic Link in the member's
        payment_history (reference_doctype='Membership' pointing at a Membership
        Dues Schedule) makes _validate_links() raise LinkValidationError on every
        save. The service used to swallow the reason entirely — it returned
        ("failed", name) and, unlike the generic Exception branch, never wrote an
        Error Log — so the operator saw only "Member update failed" with nothing
        anywhere to explain it.

        The stale row is inserted with raw SQL on purpose: doc.save() would
        reject it, which is precisely why the corruption is invisible until the
        next save attempt.
        """
        from verenigingen.services.csv_import.member_import_service import get_member_import_service
        from verenigingen.utils.csv_import_processor import bulk_member_operations

        member = self._create_member(
            first_name="Stale",
            last_name="LinkMember",
            email="stale.link@example.com",
        )

        bogus_reference = "Schedule-Does-Not-Exist-As-A-Membership-001"
        frappe.db.sql(
            """
            INSERT INTO `tabMember Payment History`
                (name, parent, parenttype, parentfield, idx, docstatus,
                 transaction_type, reference_doctype, reference_name)
            VALUES (%s, %s, 'Member', 'payment_history', 1, 0,
                    'Membership Invoice', 'Membership', %s)
            """,
            (frappe.generate_hash(length=10), member.name, bogus_reference),
        )
        frappe.db.commit()

        log_marker = frappe.utils.now_datetime()

        with bulk_member_operations("TEST-IMPORT"):
            status, returned_name = get_member_import_service().create_or_update_member(
                row_data={
                    "row_number": 7,
                    "first_name": "Stale",
                    "last_name": "LinkMember",
                    "email": "stale.link@example.com",
                    "membership_type": "lid",
                },
                import_doc_name="TEST-IMPORT-001",
            )

        # Still a failure status, so every `status in ("created", "updated")`
        # caller keeps behaving identically.
        self.assertTrue(status.startswith("failed"), f"expected a failed status, got {status!r}")
        self.assertNotIn("created", status)
        self.assertNotIn("updated", status)
        self.assertEqual(returned_name, member.name)

        # The reason the operator needs is now in the status itself.
        self.assertIn(bogus_reference, status)

        # ...and an Error Log row carries the traceback. Assert the specific
        # title — a bare count would be satisfied by any unrelated Error Log.
        titles = frappe.get_all(
            "Error Log",
            filters={"creation": [">=", log_marker]},
            pluck="error",
            limit=50,
        )
        self.assertTrue(
            any("CSV Import Update Validation Error Row 7" in (t or "") for t in titles)
            or frappe.db.exists(
                "Error Log", {"method": ["like", "%CSV Import Update Validation Error Row 7%"]}
            ),
            "expected an Error Log titled 'CSV Import Update Validation Error Row 7'",
        )

    def test_a_destroyed_savepoint_replaces_the_validation_error_instead_of_being_reported(self):
        """#701: the ValidationError branch of `_update_existing_member` writes its
        `ROLLBACK TO SAVEPOINT` bare, with no `try` around it at all -- not even the
        silent-swallow shape the other branches use. If the savepoint is gone (a
        1213, or a nested commit -- mt940_import hit exactly this and hand-wrote
        this same function twice), that ROLLBACK raises 1305 and REPLACES the
        ValidationError being handled (#561's shape): `create_or_update_member`
        never reaches `_failure_status(e)`, and the operator never learns the row
        failed on the stale link -- only that a savepoint went missing.

        Reproduces the same stale-Dynamic-Link ValidationError as
        `test_update_validation_error_surfaces_reason_and_logs`, but releases the
        savepoint immediately after it is created -- simulating what a 1213 or a
        nested commit leaves behind -- so the later ROLLBACK TO SAVEPOINT has
        nothing left to roll back to.
        """
        from verenigingen.services.csv_import.member_import_service import get_member_import_service
        from verenigingen.utils.csv_import_processor import bulk_member_operations

        member = self._create_member(
            first_name="Stale",
            last_name="LinkMember2",
            email="stale.link2@example.com",
        )
        self.created_members.append(member.name)

        bogus_reference = "Schedule-Does-Not-Exist-As-A-Membership-002"
        frappe.db.sql(
            """
            INSERT INTO `tabMember Payment History`
                (name, parent, parenttype, parentfield, idx, docstatus,
                 transaction_type, reference_doctype, reference_name)
            VALUES (%s, %s, 'Member', 'payment_history', 1, 0,
                    'Membership Invoice', 'Membership', %s)
            """,
            (frappe.generate_hash(length=10), member.name, bogus_reference),
        )
        frappe.db.commit()

        original_sql = frappe.db.sql

        def sql_that_destroys_the_savepoint(query, *args, **kwargs):
            result = original_sql(query, *args, **kwargs)
            if isinstance(query, str) and query.startswith("SAVEPOINT "):
                name = query.split(" ", 1)[1]
                # Simulate what a 1213 deadlock (or a nested commit) leaves
                # behind: the savepoint is gone before the handler ever tries
                # to roll back to it.
                original_sql(f"RELEASE SAVEPOINT {name}")
            return result

        with patch.object(frappe.db, "sql", side_effect=sql_that_destroys_the_savepoint):
            with bulk_member_operations("TEST-IMPORT"):
                status, returned_name = get_member_import_service().create_or_update_member(
                    row_data={
                        "row_number": 8,
                        "first_name": "Stale",
                        "last_name": "LinkMember2",
                        "email": "stale.link2@example.com",
                        "membership_type": "lid",
                    },
                    import_doc_name="TEST-IMPORT-001",
                )

        # The desired behaviour: the row is reported as a failure naming the REAL
        # reason (the stale link), exactly as it is when the savepoint survives
        # (see test_update_validation_error_surfaces_reason_and_logs). Before the
        # #701 fix this never executes -- the ROLLBACK's own 1305 propagates out
        # of create_or_update_member instead, so this assertion is what proves the
        # masking: an unhandled exception here, not a returned status, is the
        # symptom.
        self.assertTrue(status.startswith("failed"), f"expected a failed status, got {status!r}")
        self.assertIn(bogus_reference, status)
        self.assertEqual(returned_name, member.name)

    def test_a_deadlock_during_member_creation_is_swallowed_instead_of_abandoning_the_import(self):
        """#701: a 1213 discards the ENTIRE transaction, not just this row.

        Before the fix, `_create_new_member`'s catch-all treated a deadlock as an
        ordinary row failure -- silently failing to roll back to a savepoint the
        deadlock had already destroyed (a bare `except Exception: pass`) and
        returning `_failure_status(e)` as if one row had failed cleanly, instead of
        letting the caller (the CSV import batch loop) learn the transaction was
        discarded and abandon the import.
        """
        from verenigingen.services.csv_import.member_import_service import (
            MemberImportService,
            get_member_import_service,
        )
        from verenigingen.utils.csv_import_processor import bulk_member_operations

        service = get_member_import_service()
        row_data = {
            "row_number": 9,
            "member_id": "TEST-DEADLOCK-001",
            "first_name": "Deadlock",
            "last_name": "Test",
            "email": "deadlock.test@example.com",
            "membership_type": "lid",
        }

        with patch.object(
            MemberImportService,
            "update_member_fields",
            side_effect=frappe.QueryDeadlockError(
                "Deadlock found when trying to get lock; try restarting transaction"
            ),
        ):
            with bulk_member_operations("TEST-IMPORT"):
                with self.assertRaises(frappe.QueryDeadlockError):
                    service.create_or_update_member(
                        row_data=row_data,
                        import_doc_name="TEST-IMPORT-001",
                        create_volunteer_records=False,
                    )

    def test_failure_status_truncates_long_reasons(self):
        """The reason is capped so it cannot bloat the status or the event field."""
        from verenigingen.services.csv_import.member_import_service import (
            _FAILURE_REASON_MAX_LENGTH,
            _failure_status,
        )

        status = _failure_status(Exception("x" * 5000))

        self.assertTrue(status.startswith("failed: "))
        self.assertEqual(len(status) - len("failed: "), _FAILURE_REASON_MAX_LENGTH)

    def test_failure_status_collapses_newlines(self):
        """Keeps the status single-line for both the log and the sync-event field."""
        from verenigingen.services.csv_import.member_import_service import _failure_status

        self.assertEqual(
            _failure_status(Exception("line one\nline  two\n\tline three")),
            "failed: line one line two line three",
        )

    def test_failure_status_without_a_message_stays_bare(self):
        from verenigingen.services.csv_import.member_import_service import _failure_status

        self.assertEqual(_failure_status(Exception()), "failed")

    def test_singleton_service_instance(self):
        """Test that get_member_import_service returns singleton."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service1 = get_member_import_service()
        service2 = get_member_import_service()

        self.assertIs(service1, service2)
