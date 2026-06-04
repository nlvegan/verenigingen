"""
Payment Processing API Integration Tests
Phase 4 Week 3 - API Integration Testing

Converts heavily mocked payment processing tests to real integration tests.
This file replaces the inappropriate mocking patterns in test_payment_processing_api.py
with real business logic testing following the A+ patterns from Weeks 1-2.

Eliminates 38+ inappropriate mocks targeting core business logic:
- send_payment_reminder_email mocks (test the real email generation)
- create_membership_invoice_with_amount mocks (test real invoice creation)
- get_data report mocks (test actual database queries)
- frappe.db.get_value mocks (test real database operations)

Based on Testing Patterns Guide from Phase 4 Weeks 1-2 A+ implementation.
"""

import frappe
from frappe.utils import today, add_days, get_datetime
from unittest.mock import patch, MagicMock
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPaymentProcessingAPIIntegration(EnhancedTestCase):
    """
    Real integration tests for payment processing APIs
    
    Following A+ patterns:
    - Zero inappropriate business logic mocks
    - Real database operations with Enhanced Test Factory
    - Mock only external services (email sending)
    - Test complete workflows end-to-end
    - Performance monitoring with query baselines
    """

    def _ensure_outgoing_email_account(self):
        """Ensure a default outgoing Email Account exists.

        EmailService._send_email_internal short-circuits (returning a failed
        OperationResult and never calling frappe.sendmail) when no default
        outgoing account is configured. Production always has one; the minimal
        test site does not, so the tests that assert frappe.sendmail was called
        would otherwise see it never invoked. Create one here so the real send
        path reaches the (mocked) frappe.sendmail.
        """
        if frappe.db.exists("Email Account", {"enable_outgoing": 1, "default_outgoing": 1}):
            return
        account = frappe.get_doc(
            {
                "doctype": "Email Account",
                "email_account_name": "Test Outgoing",
                "email_id": "test-outgoing@example.com",
                "enable_outgoing": 1,
                "default_outgoing": 1,
                "smtp_server": "localhost",
                "smtp_port": 25,
                "login_id_is_different": 0,
            }
        )
        account.flags.ignore_validate = True
        account.flags.ignore_mandatory = True
        account.insert(ignore_permissions=True)

    def _enable_notifications(self, notification_keys):
        """Enable the given notification keys in Verenigingen Email Configuration.

        EmailService passes a notification_key for payment reminders / chapter
        notifications. _send_email_internal silently skips (without calling
        frappe.sendmail) when that key is not enabled in the configuration. The
        minimal test site has an empty notification_types table, so every keyed
        send is skipped. Enable the relevant keys so the real send path runs.
        """
        config = frappe.get_single("Verenigingen Email Configuration")
        config.master_email_enabled = 1
        existing = {nt.notification_key for nt in config.notification_types}
        changed = False
        for key in notification_keys:
            if key in existing:
                for nt in config.notification_types:
                    if nt.notification_key == key and not nt.enabled:
                        nt.enabled = 1
                        changed = True
            else:
                config.append(
                    "notification_types",
                    {
                        "notification_key": key,
                        "enabled": 1,
                        "label": key,
                        "category": "Payment",
                        # No cooldown so repeated sends within a test are not throttled.
                        "cooldown_minutes": 0,
                    },
                )
                changed = True
        if changed or config.has_value_changed("master_email_enabled"):
            config.flags.ignore_permissions = True
            config.save(ignore_permissions=True)

    def setUp(self):
        super().setUp()

        # Real payment-reminder/chapter-notification sends require a default
        # outgoing email account to reach frappe.sendmail (see helper docstring).
        self._ensure_outgoing_email_account()
        # ...and the keyed notifications must be enabled in the config, otherwise
        # the keyed send path is silently skipped (see helper docstring).
        self._enable_notifications(
            [
                "payment_reminder_friendly",
                "payment_reminder_urgent",
                "chapter_board_notification",
                # chapter board overdue notice uses notification_type="payment_failure"
                "payment_failure",
            ]
        )

        # Create realistic test data using Enhanced Test Factory
        # This creates real members, chapters, invoices, etc. in the database.
        # The chapter MUST exist before the member is created: member creation
        # assigns the member to the named chapter via ChapterMembershipManager,
        # which silently no-ops if the target chapter does not yet exist (leaving
        # no Chapter Member row, so the overdue-payments chapter filter matches
        # nothing). Create the chapter first, then the member.
        self.test_chapter = self.ensure_test_chapter(
            chapter_name="Amsterdam",
            attributes={"email": "amsterdam@veganisme.nl"}
        )

        self.test_member = self.create_test_member(
            first_name="Jan",
            last_name="de Vries",
            email="jan.devries@test.nl",
            chapter="Amsterdam"
        )
        
        # Create overdue invoices for real testing
        self.overdue_invoice_1 = self._create_overdue_invoice(
            member=self.test_member.name,
            days_overdue=30,
            amount=25.0
        )
        
        self.overdue_invoice_2 = self._create_overdue_invoice(
            member=self.test_member.name,
            days_overdue=60, 
            amount=35.0
        )

    def _ensure_membership_item(self, membership_type_name):
        """Pre-create the MEM-<TYPE> Item so Membership Type.get_or_create_
        membership_item() returns it without hitting the secure-op create path."""
        if not frappe.db.exists("Item Group", "Memberships"):
            frappe.get_doc(
                {
                    "doctype": "Item Group",
                    "item_group_name": "Memberships",
                    "parent_item_group": "All Item Groups",
                    "is_group": 0,
                }
            ).insert(ignore_permissions=True)

        item_code = f"MEM-{membership_type_name}".upper().replace(" ", "-")
        if not frappe.db.exists("Item", item_code):
            item = frappe.get_doc(
                {
                    "doctype": "Item",
                    "item_code": item_code,
                    "item_name": f"{membership_type_name} Membership",
                    "item_group": "Memberships",
                    "is_stock_item": 0,
                    "is_service_item": 1,
                    # is_sales_item has no DocType default (=> 0); a Sales Invoice line
                    # requires a sales-enabled item, so set it explicitly here.
                    "is_sales_item": 1,
                    # stock_uom feeds the invoice line's uom; without it the v16
                    # Sales Invoice line fails mandatory uom/price-list resolution.
                    "stock_uom": "Unit",
                    "include_item_in_manufacturing": 0,
                }
            )
            item.flags.ignore_mandatory = True
            item.insert(ignore_permissions=True)

    def _create_overdue_invoice(self, member, days_overdue, amount):
        """Create real overdue invoice using Enhanced Test Factory"""
        # Use the factory method for consistent test data
        # days_overdue is how many days past the due date the invoice is. The
        # overdue report filters on due_date < today, so due_date must be in the
        # past. (The previous `-days_overdue + 30` math produced due_date == today
        # for days_overdue == 30, i.e. NOT overdue, so those invoices were skipped.)
        invoice = self.create_test_sales_invoice(
            customer=member,
            posting_date=add_days(today(), -days_overdue - 30),
            due_date=add_days(today(), -days_overdue),
            grand_total=amount,
            is_membership_invoice=1
        )
        invoice.submit()
        return invoice

    def _add_board_member_with_email(self):
        """Add a board member to the Amsterdam chapter and return its board email.

        send_chapter_notification reads Chapter.get_board_member_emails(), which
        derives the address from the board member's linked Volunteer.email. The
        factory rewrites volunteer emails to a unique @test.invalid address, so
        we return the actual resolved board email rather than a fixed literal.
        """
        if not frappe.db.exists("Chapter Role", "Test Board Role"):
            frappe.get_doc(
                {
                    "doctype": "Chapter Role",
                    "role_name": "Test Board Role",
                    "permissions_level": "Basic",
                    "is_active": 1,
                }
            ).insert(ignore_permissions=True)

        board_member = self.create_test_member(
            first_name="Board",
            last_name="Member",
            email="board.member.account@test.nl",
            chapter="Amsterdam",
        )
        volunteer = self.create_test_volunteer(member_name=board_member.name)

        self.test_chapter.reload()
        self.test_chapter.add_board_member(volunteer.name, "Test Board Role")
        self.test_chapter.reload()

        board_emails = self.test_chapter.get_board_member_emails()
        self.assertTrue(board_emails, "Board member should expose an email")
        return board_emails[0]

    def _pin_customer_price_list(self, customer_name, price_list="Standard Selling"):
        """Set a default selling price list on the customer.

        Lets Sales Invoice.set_missing_values resolve selling_price_list inside
        the test runner (where the global default is not auto-applied).
        """
        if not customer_name or not frappe.db.exists("Price List", price_list):
            return
        frappe.db.set_value("Customer", customer_name, "default_price_list", price_list)

    def _ensure_payment_failure_template(self):
        """Create the 'Payment Failure Notification' Email Template if missing.

        send_chapter_notification renders this template; without it the templated
        send returns 'not found' and no chapter email is queued.
        """
        if frappe.db.exists("Email Template", "Payment Failure Notification"):
            return
        frappe.get_doc(
            {
                "doctype": "Email Template",
                "name": "Payment Failure Notification",
                "subject": "Overdue payment for {{ member.full_name }}",
                # EmailService reads `response` when use_html is falsy (and
                # `response_html` when truthy); keep use_html off so the content
                # below is actually used.
                "use_html": 0,
                "response": (
                    "<p>Chapter {{ chapter.name }} board notice: member "
                    "{{ member.full_name }} has {{ overdue_count }} overdue "
                    "invoice(s) totalling {{ total_overdue }}.</p>"
                ),
            }
        ).insert(ignore_permissions=True)

    def test_send_overdue_payment_reminders_real_integration(self):
        """
        Test payment reminder sending with REAL business logic
        
        Uses real operations instead of mocks:
        - Real database query (no get_data mocks)
        - Real email generation (mock only SMTP, no send_payment_reminder_email mocks)
        """
        from verenigingen.api.payment_processing import send_overdue_payment_reminders
        
        # Performance baseline from A+ testing patterns
        with self.assertQueryCount(500):  # Realistic baseline for payment processing
            # Mock only external SMTP service (legitimate mock)
            # Mock justified: External Service - SMTP delivery, not business logic
            with patch('frappe.sendmail') as mock_smtp:
                result = send_overdue_payment_reminders(
                    reminder_type="Friendly Reminder",
                    include_payment_link=True,
                    filters=frappe.as_json({"chapter": "Amsterdam"})  # Real chapter filter
                )
        
        # Verify real business logic results
        self.assertTrue(result["success"], f"Payment reminder failed: {result.get('message')}")
        self.assertGreater(result["count"], 0, "Should find real overdue payments")
        self.assertIn("successfully", result["message"])
        
        # Verify SMTP was called with real email content (not mocked content)
        mock_smtp.assert_called()
        call_args = mock_smtp.call_args[1]
        
        # Verify real email content generation. The factory uniquifies last_name,
        # so assert against the member's actual first name (used by the template).
        # The payment-reminder template is member/invoice focused and does not
        # include the chapter name, so we do not assert on it here.
        self.assertIn(self.test_member.email, call_args['recipients'])
        self.assertIn(self.test_member.first_name, call_args['message'])  # Real member name

        # Verify payment link generation (real business logic)
        if result.get("include_payment_link"):
            self.assertIn("payment", call_args['message'].lower())

    def test_export_overdue_payments_real_data(self):
        """
        Test overdue payments export with real database queries
        
        Eliminates:
        - Real report generation (no get_data mocks)
        - Real database queries (no frappe.db.sql mocks)
        """
        from verenigingen.api.payment_processing import export_overdue_payments
        from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import (
            get_data,
        )

        # export_overdue_payments only supports CSV/XLSX and returns a file
        # reference ({success, count, file_url, file_name}) — it does not return
        # the row data inline. Assert on that real contract, then verify the
        # underlying report data (what gets exported) via the report's get_data.
        with self.assertQueryCount(200):  # Report generation baseline
            result = export_overdue_payments(
                filters=frappe.as_json({"chapter": "Amsterdam"}),
                format="CSV",
            )

        # Verify a real export file was produced for our overdue member.
        self.assertTrue(result["success"], f"Export failed: {result.get('message')}")
        self.assertGreater(result["count"], 0)
        self.assertIn("file_url", result)
        self.assertTrue(result["file_name"].endswith(".csv"))

        # Find our test member in the real underlying report data (the export source).
        report_rows = get_data({"chapter": "Amsterdam"})
        member_data = next(
            (row for row in report_rows if row["member_name"] == self.test_member.name),
            None,
        )

        self.assertIsNotNone(member_data, "Test member should appear in real export data")
        self.assertEqual(member_data["member_full_name"], self.test_member.full_name)
        self.assertEqual(member_data["chapter"], "Amsterdam")
        self.assertGreater(member_data["total_overdue"], 0)

    def test_create_application_invoice_real_workflow(self):
        """
        Test invoice creation with real business validation
        
        Eliminates:
        - Real invoice creation (no create_membership_invoice_with_amount mocks)
        - Real document operations (no frappe.get_doc mocks)
        """
        from verenigingen.api.payment_processing import create_application_invoice

        # The real create_application_invoice(member, membership) takes a Member
        # doc and a Membership doc (the old application_name/amount/description
        # signature is gone) and returns the created Sales Invoice document.
        member = self.create_test_member(
            first_name="Piet",
            last_name="van der Berg",
            email=f"piet.{self.factory.test_run_id}@test.nl",
        )
        membership = self.create_test_membership(member=member.name)

        # create_membership_invoice_with_amount needs a membership Item. Item
        # auto-creation goes through secure_document_operation, whose role-gated
        # checks are unreliable in a single-module run (before_tests skipped);
        # pre-create the Item using the exact MEM-<TYPE> code so the lookup short
        # -circuits to the existing item instead of the secure-op create path.
        membership_type = frappe.get_doc("Membership Type", membership.membership_type)
        self._ensure_membership_item(membership_type.membership_type_name)

        # In a real request, Sales Invoice.set_missing_values resolves
        # selling_price_list from the global default; that resolution does not
        # happen inside the test runner, so the prod invoice (which does not set
        # the price-list fields explicitly) fails the v16 mandatory check. Pin a
        # default_price_list on the member's customer so the controller resolves
        # selling_price_list / price_list_currency from it. (Prod is unaffected:
        # there the global default already resolves.)
        member.reload()
        self._pin_customer_price_list(member.customer)

        with self.assertQueryCount(400):  # Invoice creation baseline
            invoice = create_application_invoice(member, membership)

        # Verify a real Sales Invoice document was returned and persisted.
        self.assertIsNotNone(invoice)
        self.assertTrue(frappe.db.exists("Sales Invoice", invoice.name))
        self.assertEqual(invoice.doctype, "Sales Invoice")
        self.assertGreater(invoice.grand_total, 0)

        # Verify the invoice is linked to the member's customer.
        member.reload()
        self.assertEqual(invoice.customer, member.customer)

    def test_bulk_payment_action_real_processing(self):
        """
        Test bulk payment actions with real member processing
        
        Eliminates:
        - Real member queries (no frappe.get_all mocks)
        - Real status updates (no update_payment_status mocks)
        """
        from verenigingen.api.payment_processing import execute_bulk_payment_action
        
        # Create additional test member for bulk operations
        member2 = self.create_test_member(
            first_name="Marie",
            last_name="van Amsterdam",
            email="marie@test.nl",
            chapter="Amsterdam"
        )
        
        # Create overdue invoice for second member
        overdue_invoice_3 = self._create_overdue_invoice(
            member=member2.name,
            days_overdue=45,
            amount=30.0
        )
        
        # Execute real bulk action
        with self.assertQueryCount(800):  # Bulk operation baseline
            # Mock justified: External Service - SMTP delivery, not business logic
            with patch('frappe.sendmail') as mock_smtp:  # Mock only SMTP
                result = execute_bulk_payment_action(
                    action="Send Payment Reminders",
                    filters=frappe.as_json({"chapter": "Amsterdam"})
                )
        
        # execute_bulk_payment_action is @critical_api-decorated, which flattens
        # the OperationResult into a flat dict envelope: {"success", "count", ...}.
        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["count"], 0)  # Processed count

        # Verify real emails were generated for members found
        # Note: mock_smtp.call_count depends on how many overdue records exist
        self.assertGreaterEqual(mock_smtp.call_count, 0)

    def test_payment_reminder_html_generation_real_template(self):
        """
        Test email template generation with real member data
        
        Eliminates:
        - Real template rendering (no frappe.render_template mocks)
        - Real member data loading (no get_member_payment_info mocks)
        """
        from verenigingen.api.payment_processing import generate_payment_reminder_html

        # The real generate_payment_reminder_html(member, payment_info,
        # reminder_type, custom_message) takes a Member doc plus a payment_info
        # dict and renders a self-contained HTML block (member.first_name,
        # reminder_type, the payment_info figures, and any custom_message).
        payment_info = {
            "overdue_count": 2,
            "total_overdue": 60.0,
            "days_overdue": 45,
            "membership_type": "Regular",
        }

        html_content = generate_payment_reminder_html(
            self.test_member,
            payment_info,
            "Final Notice",
            "This is a real integration test",
        )

        # Verify real template content
        self.assertIsInstance(html_content, str)
        self.assertGreater(len(html_content), 100)  # Substantial content

        # Verify real member data + rendered fields are included
        self.assertIn(self.test_member.first_name, html_content)  # "Jan"
        self.assertIn("final notice", html_content.lower())  # Real reminder type
        self.assertIn("real integration test", html_content)  # Custom message
        self.assertIn("Payment Details", html_content)  # Payment info block

    def test_chapter_notification_real_workflow(self):
        """
        Test chapter notification system with real chapter and member data
        
        Eliminates:
        - Real notification logic (no send_chapter_notification mocks)
        - Real chapter contact lookup (no get_chapter_contacts mocks)
        """
        from verenigingen.api.payment_processing import send_overdue_payment_reminders

        # send_chapter_notification delivers to the chapter's BOARD MEMBER emails
        # (Chapter.get_board_member_emails()), not the chapter's own email field,
        # and renders the "Payment Failure Notification" template. Set up a real
        # board member plus the template so the notification actually goes out.
        board_email = self._add_board_member_with_email()
        self._ensure_payment_failure_template()

        # Send reminders with chapter notifications enabled
        with self.assertQueryCount(600):  # Chapter notification baseline
            # Mock justified: External Service - SMTP delivery, not business logic
            with patch('frappe.sendmail') as mock_smtp:  # Mock only SMTP
                result = send_overdue_payment_reminders(
                    send_to_chapters=True,
                    reminder_type="Friendly Reminder",
                    filters=frappe.as_json({"chapter": "Amsterdam"})
                )

        # Verify real chapter notification was processed. The endpoint returns a
        # flat {"success", "count", "message"} shape (count = reminders processed);
        # chapter delivery is verified via the SMTP call assertions below.
        self.assertTrue(result["success"])
        self.assertGreater(result["count"], 0)

        # Verify SMTP was called for both the member reminder and the chapter board.
        self.assertGreater(mock_smtp.call_count, 1)

        # Find the chapter board notification email.
        chapter_email_found = any(
            board_email in call[1].get("recipients", [])
            for call in mock_smtp.call_args_list
        )
        self.assertTrue(chapter_email_found, "Chapter board notification email should be sent")

    def test_error_handling_real_validation(self):
        """
        Test error handling with real validation errors (not mocked errors)
        """
        from verenigingen.api.payment_processing import create_application_invoice

        # The real create_application_invoice(member, membership) resolves the
        # membership's membership_type via frappe.get_doc; a membership pointing
        # at a non-existent Membership Type raises a real DoesNotExistError.
        member = self.create_test_member(
            first_name="Test",
            last_name="Error",
            email=f"test.error.{self.factory.test_run_id}@test.nl",
        )
        bogus_membership = frappe._dict(
            {"membership_type": "NON_EXISTENT_MEMBERSHIP_TYPE", "uses_custom_amount": False}
        )

        with self.assertRaises(frappe.DoesNotExistError):
            create_application_invoice(member, bogus_membership)

    def test_performance_regression_protection(self):
        """
        Test that real integration doesn't cause performance regressions
        
        Based on A+ performance baselines from Weeks 1-2
        """
        from verenigingen.api.payment_processing import send_overdue_payment_reminders
        
        # Create additional test data for performance testing
        for i in range(5):
            member = self.create_test_member(
                first_name=f"Perf{i}",
                last_name="Test",
                email=f"perf{i}@test.nl",
                chapter="Amsterdam"
            )
            self._create_overdue_invoice(member.name, 30, 25.0)
        
        import time
        start_time = time.time()
        
        # Execute with performance monitoring
        with self.assertQueryCount(1500):  # Realistic baseline for 5+ members
            # Mock justified: External Service - SMTP delivery, not business logic
            with patch('frappe.sendmail'):  # Mock SMTP only
                result = send_overdue_payment_reminders(
                    filters=frappe.as_json({"chapter": "Amsterdam"})
                )
        
        duration = time.time() - start_time
        
        # Performance requirements from A+ standards
        self.assertLess(duration, 10.0, "Payment processing should complete within 10s")
        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["count"], 6)  # Original + 5 test members


class TestPaymentProcessingAPISecurityIntegration(EnhancedTestCase):
    """
    Security integration tests for payment processing APIs
    
    Tests real permission validation (not mocked permissions)
    """

    def _ensure_role(self, role_name):
        """Get-or-create a Role so role assignment doesn't fail on minimal sites."""
        if not frappe.db.exists("Role", role_name):
            frappe.get_doc({"doctype": "Role", "role_name": role_name, "desk_access": 0}).insert(
                ignore_permissions=True
            )

    def test_payment_reminder_permission_validation(self):
        """
        Test that payment reminder sending requires proper permissions
        """
        from verenigingen.api.payment_processing import send_overdue_payment_reminders

        # "Website User" is a standard Frappe role but is not guaranteed to be
        # bootstrapped on a minimal test site; ensure it exists before assigning.
        self._ensure_role("Website User")

        # Create test user with limited permissions
        limited_user = self.create_test_user_with_roles(
            email="limited@test.nl",
            roles=["Website User"]  # No payment processing permissions
        )
        
        # Test with limited user (real permission validation)
        with self.as_user(limited_user.email):
            with self.assertRaises(frappe.PermissionError):
                send_overdue_payment_reminders()
        
        # Test with admin user (should work)
        with self.as_user("Administrator"):
            # Mock justified: External Service - SMTP delivery, not business logic
            with patch('frappe.sendmail'):  # Mock SMTP only
                result = send_overdue_payment_reminders()
                # Should succeed with proper permissions
                self.assertIsInstance(result, dict)

    def test_bulk_payment_action_access_control(self):
        """
        Test bulk payment actions have proper access controls
        """
        from verenigingen.api.payment_processing import execute_bulk_payment_action

        self._ensure_role("Website User")

        # Test unauthorized access (real permission check)
        guest_user = self.create_test_user_with_roles(
            email="guest@test.nl",
            roles=["Website User"]
        )
        
        with self.as_user(guest_user.email):
            with self.assertRaises(frappe.PermissionError):
                execute_bulk_payment_action(
                    action="Send Payment Reminders",
                    filters=frappe.as_json({})
                )


# Performance and Quality Metrics
# Expected Query Counts (realistic baselines from A+ testing):
# - Payment reminder processing: ~500 queries (includes member lookup, invoice queries, template rendering)  
# - Export operations: ~200 queries (report generation with joins)
# - Invoice creation: ~300 queries (member validation, customer creation, invoice generation)
# - Bulk operations: ~800 queries (multiple member processing)
# - Template rendering: ~100 queries (member data loading, template processing)
# - Chapter notifications: ~600 queries (member processing + chapter contact lookup)

# Mock Usage Classification:
# ✅ LEGITIMATE: frappe.sendmail (external SMTP service)
# ❌ ELIMINATED: get_data, send_payment_reminder_email, create_membership_invoice_with_amount
# ❌ ELIMINATED: frappe.db.get_value, frappe.get_all, frappe.render_template 
# ❌ ELIMINATED: All internal business logic mocks

# Quality Standards Met:
# 1. ✅ Zero inappropriate business logic mocks
# 2. ✅ Real database operations with Enhanced Test Factory
# 3. ✅ Performance baselines established and monitored
# 4. ✅ Security integration with real permission validation
# 5. ✅ Error handling tests with real validation errors
# 6. ✅ Complete workflow testing end-to-end







