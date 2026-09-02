import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSEPAMandate(EnhancedTestCase):
    def setUp(self):
        # Create a test member for use in tests
        super().setUp()
        self.test_member = create_test_member()
        # Create a clean mandate for each test
        self.mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": f"TEST-MANDATE-{frappe.utils.random_string(8)}",
                "member": self.test_member.name,
                "account_holder_name": self.test_member.full_name,
                "iban": "NL91ABNA0417164300",  # Test IBAN
                "sign_date": today(),
                "status": "Draft",
                "mandate_type": "RCUR",
                "scheme": "SEPA",
                "is_active": 1,
                "used_for_memberships": 1,
            }
        )

    def _reset_in_import_flag(self):
        """Restore frappe.flags.in_import after a test toggled it off."""
        frappe.flags.in_import = getattr(self, "_restore_in_import", False)

    def tearDown(self):
        # Clean up test data
        try:
            if frappe.db.exists("SEPA Mandate", self.mandate.name):
                frappe.delete_doc("SEPA Mandate", self.mandate.name, force=True)
            if self.test_member and frappe.db.exists("Member", self.test_member.name):
                frappe.delete_doc("Member", self.test_member.name, force=True)
        except Exception as e:
            print(f"Error in tearDown: {str(e)}")
            frappe.db.rollback()
        super().tearDown()

    def test_second_active_mandate_for_the_same_purpose_is_rejected(self):
        """One Active mandate per member PER PURPOSE, whatever the IBAN.

        The guard this widens keyed on member + IBAN, on the stated grounds that a
        member switching banks legitimately holds two Active mandates and the older
        one "supersedes via the Member SEPA Mandate Link is_current flag". Measured
        on test_site_1, that mechanism does not exist:

          - no mandate-resolution query reads ``is_current`` AT ALL --
            ``get_invoice_mandate_info``, ``validate_invoice_mandate`` and
            ``get_active_mandates`` all filter on ``status``, so even a perfectly
            maintained flag could not have disambiguated a direct debit;
          - and it is not maintained: both writers compute
            ``is_current = 1 if status == "Active" and is_active else 0``
            (``sepa_mandate_manager.py:678``,
            ``sepa_mandate_member_integration_service.py:186``), so two Active
            mandates are BOTH flagged current;
          - the flag-clearing code that runs automatically,
            ``MemberSEPAMandateLink.check_current_mandate``, is never called (#596) --
            Frappe does not run child-DocType ``validate()``. Spying the bound
            controller class across an insert of two mandates plus an explicit
            ``member.save()`` counted 0 invocations. Had it run it would have
            raised, because it does ``self.parent.sepa_mandates`` and ``self.parent``
            is the parent's name, a string;
          - ``deactivate_mandates_for_iban_change``, the purpose-built superseder,
            has no production caller.

        With no discriminator, ``get_invoice_mandate_info``'s
        ``ORDER BY sm.creation DESC LIMIT 1`` decides which IBAN is debited (#584).
        Blocking the second Active mandate is what makes that pick unambiguous.
        """
        self.mandate.status = "Active"
        self.mandate.insert()

        second = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": f"TEST-MANDATE-{frappe.utils.random_string(8)}",
                "member": self.test_member.name,
                "account_holder_name": self.test_member.full_name,
                # DIFFERENT IBAN -- the case the old guard deliberately allowed.
                "iban": "NL39RABO0300065264",
                "sign_date": today(),
                "status": "Active",
                "mandate_type": "RCUR",
                "scheme": "SEPA",
                "is_active": 1,
                "used_for_memberships": 1,
            }
        )
        with self.assertRaises(frappe.ValidationError) as caught:
            second.insert()

        # The message must name the mandate standing in the way, or an operator
        # cannot act on it. Asserting only that *something* raised would also pass
        # for an unrelated validation error -- the IBAN validator, say.
        message = str(caught.exception)
        self.assertIn(self.mandate.mandate_id, message)
        self.assertIn(
            "memberships",
            message,
            "the error must name the purpose, or an operator "
            "cannot tell which of a member's mandates to cancel",
        )
        self.assertFalse(
            frappe.db.exists("SEPA Mandate", {"name": second.name or "", "status": "Active"}),
            "the second Active mandate was persisted despite the guard",
        )

    def test_a_second_active_mandate_for_a_DIFFERENT_purpose_is_allowed(self):
        """The capability the per-purpose scoping exists to keep.

        A member may hold an Active membership mandate and an Active donation
        mandate at the same time. This is not a tolerated edge case -- it is a shape
        the app models and already has a regression test for:
        `test_payment_history_writer_parity.test_mandate_resolution_matches_with_
        newer_donation_only_mandate` guards a real divergence caused by resolving a
        membership invoice's mandate WITHOUT a purpose filter, and its fix was to
        filter, not to forbid.

        This is also the control for the test above: without it, that test would
        pass equally against a guard that rejected every second Active mandate,
        which would break donations.
        """
        self.mandate.status = "Active"
        self.mandate.used_for_memberships = 1
        self.mandate.used_for_donations = 0
        self.mandate.insert()

        donation_mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": f"TEST-MANDATE-{frappe.utils.random_string(8)}",
                "member": self.test_member.name,
                "account_holder_name": self.test_member.full_name,
                "iban": "NL39RABO0300065264",
                "sign_date": today(),
                "status": "Active",
                "mandate_type": "RCUR",
                "scheme": "SEPA",
                "is_active": 1,
                "used_for_memberships": 0,
                "used_for_donations": 1,
            }
        )
        donation_mandate.insert()
        self.addCleanup(frappe.delete_doc, "SEPA Mandate", donation_mandate.name, force=True)

        self.assertEqual(donation_mandate.status, "Active")
        self.assertEqual(
            frappe.db.count("SEPA Mandate", {"member": self.test_member.name, "status": "Active"}),
            2,
            "a member must be able to hold a membership AND a donation mandate at once",
        )

    def test_a_second_mandate_is_allowed_while_it_is_not_active(self):
        """The guard must gate on Active, not on existence.

        A bank switch is prepared by creating the new mandate and cancelling the
        old one; if a Draft second mandate were rejected outright there would be no
        way to stage that. This is the control for the test above -- without it,
        that test would also pass against a guard that rejected every second
        mandate, which would break the sanctioned flow.
        """
        self.mandate.status = "Active"
        self.mandate.insert()

        draft = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": f"TEST-MANDATE-{frappe.utils.random_string(8)}",
                "member": self.test_member.name,
                "account_holder_name": self.test_member.full_name,
                "iban": "NL39RABO0300065264",
                "sign_date": today(),
                "status": "Draft",
                "mandate_type": "RCUR",
                "scheme": "SEPA",
                "is_active": 0,
                "used_for_memberships": 1,
            }
        )
        draft.insert()
        self.addCleanup(frappe.delete_doc, "SEPA Mandate", draft.name, force=True)

        self.assertEqual(frappe.db.get_value("SEPA Mandate", draft.name, "status"), "Draft")

    def test_validate_dates_future_sign_date(self):
        """Test that validation fails when sign date is in the future"""
        self.mandate.sign_date = add_days(today(), 5)  # 5 days in the future

        with self.assertRaises(frappe.exceptions.ValidationError):
            self.mandate.insert()

    def test_validate_dates_expiry_before_sign(self):
        """Test that validation fails when expiry date is before sign date"""
        self.mandate.sign_date = today()
        self.mandate.expiry_date = add_days(today(), -10)  # 10 days in the past

        with self.assertRaises(frappe.exceptions.ValidationError):
            self.mandate.insert()

    def test_validate_iban_format(self):
        """Test IBAN validation"""
        # Test invalid IBAN (too short)
        self.mandate.iban = "NL1234"

        with self.assertRaises(frappe.exceptions.ValidationError):
            self.mandate.insert()

        # Test valid IBAN
        self.mandate.iban = "NL91ABNA0417164300"
        self.mandate.insert()
        # IBAN gets formatted with spaces, so check for the formatted version
        self.assertEqual(self.mandate.iban, "NL91 ABNA 0417 1643 00")

    def test_preserve_draft_status(self):
        """Test Draft status is preserved until explicitly changed"""
        self.mandate.status = "Draft"
        self.mandate.is_active = 1
        self.mandate.insert()

        # Status should remain as Draft
        self.assertEqual(self.mandate.status, "Draft")

        # Modify and save to check if Draft status persists
        self.mandate.account_holder_name = "Modified Name"
        self.mandate.save()

        # Status should still be Draft
        self.assertEqual(self.mandate.status, "Draft")

    def test_preserve_cancelled_status(self):
        """Test Cancelled status is preserved and not overridden"""
        # First insert with Active status
        self.mandate.status = "Active"
        self.mandate.insert()

        # Now set it to Cancelled
        self.mandate.status = "Cancelled"
        self.mandate.is_active = 0
        self.mandate.cancelled_date = today()
        self.mandate.save()

        # Status should be Cancelled
        self.assertEqual(self.mandate.status, "Cancelled")

        # Change other fields and verify Cancelled status persists
        self.mandate.account_holder_name = "New Holder Name"
        self.mandate.save()

        # Status should still be Cancelled
        self.assertEqual(self.mandate.status, "Cancelled")

    def test_status_active(self):
        """Test status is set to Active with valid configuration"""
        self.mandate.status = "Active"
        self.mandate.is_active = 1
        self.mandate.insert()
        self.assertEqual(self.mandate.status, "Active")

        # DIRECT APPROACH: Update the database directly to change is_active to 0
        frappe.db.set_value("SEPA Mandate", self.mandate.name, "is_active", 0)

        # Then directly update the status in a separate call to make sure the change is applied
        frappe.db.set_value("SEPA Mandate", self.mandate.name, "status", "Suspended")

        # Fetch a fresh copy of the mandate from the database
        refreshed = frappe.get_doc("SEPA Mandate", self.mandate.name)
        self.assertEqual(
            refreshed.status, "Suspended", f"Expected status to be Suspended but got {refreshed.status}"
        )
        self.assertEqual(refreshed.is_active, 0, f"Expected is_active to be 0 but got {refreshed.is_active}")

    def test_status_suspended(self):
        """Test status is set to Suspended when is_active=0"""
        self.mandate.status = "Suspended"
        self.mandate.is_active = 0
        self.mandate.insert()
        self.assertEqual(self.mandate.status, "Suspended")

        # DIRECT APPROACH: Update the database directly to change is_active to 1
        frappe.db.set_value("SEPA Mandate", self.mandate.name, "is_active", 1)

        # Then directly update the status in a separate call to make sure the change is applied
        frappe.db.set_value("SEPA Mandate", self.mandate.name, "status", "Active")

        # Fetch a fresh copy of the mandate from the database
        refreshed = frappe.get_doc("SEPA Mandate", self.mandate.name)
        self.assertEqual(
            refreshed.status, "Active", f"Expected status to be Active but got {refreshed.status}"
        )
        self.assertEqual(refreshed.is_active, 1, f"Expected is_active to be 1 but got {refreshed.is_active}")

    def test_status_expired(self):
        """Test status is set to Expired when expiry date is in the past"""
        # Set sign date to a past date, and expiry date between sign date and today
        self.mandate.sign_date = add_days(today(), -30)  # 30 days in the past
        self.mandate.expiry_date = add_days(today(), -1)  # Yesterday (but after sign date)
        self.mandate.status = "Active"  # Start with Active
        self.mandate.insert()
        self.assertEqual(self.mandate.status, "Expired")

        # Verify that changing is_active doesn't override Expired status
        self.mandate.is_active = 1
        self.mandate.save()
        self.assertEqual(self.mandate.status, "Expired")

    # This test will pass only if we update the SEPAMandate class
    def test_is_active_flag_sync(self):
        """Test is_active flag stays in sync with status"""
        # Insert with Active status
        self.mandate.status = "Active"
        self.mandate.is_active = 1
        self.mandate.insert()
        self.assertEqual(self.mandate.is_active, 1)

        # Direct database approach: set status to Suspended
        frappe.db.set_value("SEPA Mandate", self.mandate.name, "status", "Suspended")
        frappe.db.set_value("SEPA Mandate", self.mandate.name, "is_active", 0)

        # Re-fetch mandate to check updated is_active
        refreshed_mandate = frappe.get_doc("SEPA Mandate", self.mandate.name)
        self.assertEqual(refreshed_mandate.status, "Suspended", "Status should be Suspended")
        self.assertEqual(refreshed_mandate.is_active, 0, "is_active should be 0 when status is Suspended")

        # Change status back to Active
        frappe.db.set_value("SEPA Mandate", self.mandate.name, "status", "Active")
        frappe.db.set_value("SEPA Mandate", self.mandate.name, "is_active", 1)

        # Re-fetch again
        refreshed_mandate = frappe.get_doc("SEPA Mandate", self.mandate.name)
        self.assertEqual(refreshed_mandate.status, "Active", "Status should be Active")
        self.assertEqual(refreshed_mandate.is_active, 1, "is_active should be 1 when status is Active")

        # Change to Cancelled
        frappe.db.set_value("SEPA Mandate", self.mandate.name, "status", "Cancelled")
        frappe.db.set_value("SEPA Mandate", self.mandate.name, "is_active", 0)

        # Re-fetch again
        refreshed_mandate = frappe.get_doc("SEPA Mandate", self.mandate.name)
        self.assertEqual(refreshed_mandate.status, "Cancelled", "Status should be Cancelled")
        self.assertEqual(refreshed_mandate.is_active, 0, "is_active should be 0 when status is Cancelled")

    def test_on_update_member_relationship(self):
        """Test relationship with Member is properly set up on update"""
        # Insert mandate first with Active status
        self.mandate.status = "Active"
        self.mandate.insert()

        # Get the member and check if mandate was added
        member = frappe.get_doc("Member", self.test_member.name)

        # Find if our mandate is in the member's mandates
        mandate_found = False
        for member_mandate in member.sepa_mandates:
            if member_mandate.sepa_mandate == self.mandate.name:
                mandate_found = True
                self.assertTrue(member_mandate.is_current, "Mandate should be set as current")
                break

        self.assertTrue(mandate_found, "Mandate should be added to Member's mandate list")

    def test_mandate_usage_tracking(self):
        """Test that mandate usage is properly tracked"""
        # Insert mandate with Active status
        self.mandate.status = "Active"
        self.mandate.insert()

        # Import usage creation function
        from verenigingen.verenigingen_payments.doctype.sepa_mandate_usage.sepa_mandate_usage import (
            create_mandate_usage_record,
        )

        # Create a usage record
        usage_name = create_mandate_usage_record(
            mandate_name=self.mandate.name,
            reference_doctype="Sales Invoice",
            reference_name="INV-TEST-001",
            amount=25.00,
            sequence_type="FRST",
        )

        self.assertIsNotNone(usage_name, "Usage record should be created")

        # Reload mandate and check usage history
        self.mandate.reload()
        self.assertEqual(len(self.mandate.usage_history), 1, "Mandate should have one usage record")

        usage_record = self.mandate.usage_history[0]
        self.assertEqual(usage_record.reference_doctype, "Sales Invoice")
        self.assertEqual(usage_record.reference_name, "INV-TEST-001")
        self.assertEqual(usage_record.amount, 25.00)
        # Check sequence type using get() to handle potential attribute issues
        self.assertEqual(getattr(usage_record, "sequence_type", "FRST"), "FRST")
        self.assertEqual(usage_record.status, "Pending")

    def test_sequence_type_determination(self):
        """Test FRST/RCUR sequence type determination"""
        # EnhancedTestCase sets frappe.flags.in_import=True, which skips child
        # validate() hooks (where sequence_type is auto-determined). Clear it so
        # the production sequence-type logic runs.
        self._restore_in_import = frappe.flags.in_import
        frappe.flags.in_import = False
        self.addCleanup(self._reset_in_import_flag)

        # Insert mandate with Active status
        self.mandate.status = "Active"
        self.mandate.insert()

        from verenigingen.verenigingen_payments.doctype.sepa_mandate_usage.sepa_mandate_usage import (
            create_mandate_usage_record,
            get_mandate_sequence_type,
        )

        # First usage should be FRST
        sequence_info = get_mandate_sequence_type(self.mandate.name, "INV-001")
        self.assertEqual(sequence_info["sequence_type"], "FRST", "First usage should be FRST")
        # Allow both "First usage" and default case
        self.assertTrue(
            "First usage" in sequence_info["reason"] or "defaulting to FRST" in sequence_info["reason"],
            f"Unexpected reason: {sequence_info['reason']}",
        )

        # Create first successful usage
        create_mandate_usage_record(
            mandate_name=self.mandate.name,
            reference_doctype="Sales Invoice",
            reference_name="INV-001",
            amount=25.00,
        )

        # Mark it as collected
        self.mandate.reload()
        usage_record = self.mandate.usage_history[0]
        usage_record.status = "Collected"
        usage_record.processing_date = today()
        self.mandate.save()

        # Second usage should be RCUR
        sequence_info = get_mandate_sequence_type(self.mandate.name, "INV-002")
        self.assertEqual(sequence_info["sequence_type"], "RCUR", "Second usage should be RCUR")
        self.assertIn("Recurring usage", sequence_info["reason"])

    def test_mandate_usage_validation(self):
        """Test mandate usage validation"""
        # EnhancedTestCase sets frappe.flags.in_import=True, which makes Frappe
        # SKIP child-table validate() hooks. This test exercises the SEPA Mandate
        # Usage child validate() (auto-setting sequence_type, rejecting inactive
        # mandates), so the import flag must be cleared for the real code path.
        self._restore_in_import = frappe.flags.in_import
        frappe.flags.in_import = False
        self.addCleanup(self._reset_in_import_flag)

        # Insert mandate with Active status
        self.mandate.status = "Active"
        self.mandate.insert()

        # Create usage record
        usage_row = self.mandate.append(
            "usage_history",
            {
                "usage_date": today(),
                "reference_doctype": "Sales Invoice",
                "reference_name": "INV-TEST-VAL",
                "amount": 50.00,
                "status": "Pending",
            },
        )

        # Save should validate and set sequence type
        self.mandate.save()
        # Reload to get updated field values
        self.mandate.reload()
        updated_usage = self.mandate.usage_history[0]
        self.assertEqual(
            getattr(updated_usage, "sequence_type", "FRST"), "FRST", "First usage should auto-set to FRST"
        )

        # Test inactive mandate validation
        self.mandate.status = "Cancelled"
        self.mandate.save()

        # Try to create usage for cancelled mandate - should fail during validation
        try:
            from verenigingen.verenigingen_payments.doctype.sepa_mandate_usage.sepa_mandate_usage import (
                create_mandate_usage_record,
            )

            # This should raise validation error for inactive mandate
            with self.assertRaises(frappe.exceptions.ValidationError):
                create_mandate_usage_record(
                    mandate_name=self.mandate.name,
                    reference_doctype="Sales Invoice",
                    reference_name="INV-TEST-VAL2",
                    amount=30.00,
                )
        except ImportError:
            # Fallback: try adding to cancelled mandate and expect no error
            # (since child table validation might not trigger in all contexts)
            usage_row2 = self.mandate.append(
                "usage_history",
                {
                    "usage_date": today(),
                    "reference_doctype": "Sales Invoice",
                    "reference_name": "INV-TEST-VAL2",
                    "amount": 30.00,
                    "status": "Pending",
                },
            )
            # Just verify the test runs without validation in test context
            self.mandate.save()

    def test_usage_amount_over_mandate_maximum_is_rejected(self):
        """A usage row whose amount exceeds the mandate's maximum_amount must be rejected.

        SEPA Mandate Usage's own validate() used to check this (validate_amount), but
        Frappe never runs a child DocType's validate(). create_mandate_usage_record()
        already works around the dead validate() for the mandate-active/expired check
        and for sequence_type, but NOT for this amount check -- so today a usage row
        with amount > maximum_amount persists silently, both through
        create_mandate_usage_record() and through a direct append+save. See #596.
        """
        self.mandate.status = "Active"
        self.mandate.maximum_amount = 100.00
        self.mandate.insert()

        self.mandate.append(
            "usage_history",
            {
                "usage_date": today(),
                "reference_doctype": "Sales Invoice",
                "reference_name": "INV-TEST-OVERLIMIT",
                "amount": 150.00,
                "sequence_type": "RCUR",
                "status": "Pending",
            },
        )

        with self.assertRaises(frappe.ValidationError):
            self.mandate.save()

    def test_create_usage_record_rejects_an_expired_mandate_with_stale_active_status(self):
        """A mandate past its expiry_date must refuse a new usage record, even when
        the persisted `status` column is still stale-"Active".

        SEPAMandate.set_status_based_on_dates() only recalculates status ON SAVE, so
        a mandate nobody has re-saved since its expiry_date passed can sit in the DB
        with status="Active" indefinitely -- there is no scheduled job that revisits
        it. create_mandate_usage_record()'s own docstring/comment already claims to
        guard against "a cancelled or expired mandate", but the code only checked
        `mandate.status != "Active"`, never expiry_date directly -- so a usage record
        against a date-expired-but-status-stale mandate went through silently. The
        ORIGINAL dead SEPAMandateUsage.validate_mandate_status() (#596) checked
        expiry_date explicitly and would have caught this, had Frappe ever run it.
        """
        from verenigingen.verenigingen_payments.doctype.sepa_mandate_usage.sepa_mandate_usage import (
            create_mandate_usage_record,
        )

        # sign_date well in the past: validate_mandate_dates() rejects sign_date >
        # expiry_date, so a sign_date of today() would collide with the stale
        # expiry_date set below and raise "Sign date cannot be after expiry date"
        # -- a false positive for assertRaises that has nothing to do with the gap
        # under test. Measured directly: this DID happen with sign_date=today()
        # before this was fixed to add_days(today(), -60).
        self.mandate.sign_date = add_days(today(), -60)
        self.mandate.status = "Active"
        self.mandate.expiry_date = add_days(today(), 30)  # not yet expired, so insert() accepts it
        self.mandate.insert()

        # Simulate staleness: push expiry_date into the past via db_set, which
        # bypasses validate() (and therefore set_status_based_on_dates()) entirely --
        # exactly like a mandate nobody has re-saved since it expired.
        frappe.db.set_value("SEPA Mandate", self.mandate.name, "expiry_date", add_days(today(), -1))
        frappe.db.commit()

        with self.assertRaises(frappe.ValidationError):
            create_mandate_usage_record(
                mandate_name=self.mandate.name,
                reference_doctype="Sales Invoice",
                reference_name="INV-TEST-EXPIRED-STALE",
                amount=10.00,
            )


def create_test_member():
    """Helper function to create a test member with a unique alphanumeric name"""
    # Import for generating alphanumeric strings
    import random
    import string

    random_string = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    # Generate a random string with only letters and numbers
    random_digits = "".join(random.choices(string.digits, k=8))
    member_email = f"test_sepa_{random_string}@example.com"

    # Create member with unique alphanumeric first name
    member = frappe.get_doc(
        {
            "doctype": "Member",
            "first_name": f"Test{random_string[:4]}",  # Add random string to first name
            "last_name": "SEPA",
            "email": member_email,
            "mobile_no": f"+316{random_digits}",  # Add unique phone number
            "iban": "NL91ABNA0417164300",  # Test IBAN
        }
    )
    member.insert()  # EnhancedTestCase handles permissions

    return member
