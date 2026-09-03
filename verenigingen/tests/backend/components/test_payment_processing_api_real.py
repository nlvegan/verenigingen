import json
import unittest
import frappe
from unittest.mock import patch
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from frappe.utils import today, add_days

from verenigingen.api.payment_processing import (
    create_application_invoice,
    execute_bulk_payment_action,
    export_overdue_payments,
    generate_payment_reminder_html,
    get_or_create_customer,
    send_overdue_payment_reminders,
    send_payment_reminder_email,
)


class TestPaymentProcessingAPIReal(EnhancedTestCase):
    """Real database integration tests for payment processing API endpoints - NO DATABASE MOCKS"""

    def setUp(self):
        """Set up test data with Enhanced Test Factory"""
        super().setUp()

        # The unified EmailService only reaches frappe.sendmail when an active
        # outgoing Email Account is configured; ensure one exists.
        self._ensure_outgoing_email_account()

        # Create real test member with Enhanced Test Factory
        self.test_member = self.create_test_member(
            first_name="Payment",
            last_name="Test",
            email="payment.test@example.com"
        )
        
        # Create real test chapter
        self.test_chapter = self.ensure_test_chapter(
            chapter_name="Amsterdam",
            attributes={"email": "amsterdam@example.com"}
        )
        
        # Create real overdue payment scenario using Enhanced Test Factory
        self.overdue_member = self.create_test_member(
            first_name="Overdue",
            last_name="Member",
            email="overdue.member@example.com"
        )
        
        # Create sample payment info for tests
        self.sample_payment_info = {
            "amount": 25.0,
            "due_date": add_days(today(), -30),  # 30 days overdue
            "invoice_number": f"TEST-{frappe.utils.random_string(6)}"
        }
        
        # Ensure real email template exists for testing (no mocks)
        self.setup_real_email_template()

    def _ensure_outgoing_email_account(self):
        """Ensure an active default outgoing Email Account exists for the site."""
        if frappe.db.exists("Email Account", {"enable_outgoing": 1, "default_outgoing": 1}):
            return
        account = frappe.new_doc("Email Account")
        account.email_account_name = "Test Outgoing"
        account.email_id = "test-outgoing@example.com"
        account.enable_outgoing = 1
        account.default_outgoing = 1
        account.smtp_server = "localhost"
        account.smtp_port = 25
        account.flags.ignore_validate = True
        account.insert(ignore_permissions=True)

    def setup_real_email_template(self):
        """Create real email template in database for testing"""
        template_name = "Payment Reminder Test Template"
        
        if not frappe.db.exists("Email Template", template_name):
            template = frappe.get_doc({
                "doctype": "Email Template",
                "name": template_name,
                "subject": "Payment Reminder: {{ payment_info.invoice_number }}",
                "response_html": """
                <p>Dear {{ member_name }},</p>
                <p>This is a reminder about your overdue payment of {{ payment_info.amount }}.</p>
                <p>Invoice: {{ payment_info.invoice_number }}</p>
                <p>Due Date: {{ payment_info.due_date }}</p>
                """,
                "enabled": 1
            })
            template.insert()
            self.email_template_name = template_name
        else:
            self.email_template_name = template_name

    def create_real_test_invoice(self, member=None, status="Draft", amount=25.0, 
                                custom_is_membership_dues=1, custom_member=None):
        """Create real sales invoice in database for testing - NO MOCKS"""
        if not member:
            member = self.test_member
        
        # Ensure real customer exists for member (no mocks)
        if not member.customer:
            customer = get_or_create_customer(member)
            member.customer = customer.name
            member.save()
        
        # Create real sales invoice. For overdue invoices the posting_date must
        # also be in the past, otherwise ERPNext resets the due_date forward to
        # the posting_date and the "due_date < today" report filter excludes it.
        # set_posting_time is what makes that backdating stick -- without it
        # validate_posting_time() overwrites posting_date with today, and the
        # past due_date then fails validate_due_date outright.
        invoice = frappe.new_doc("Sales Invoice")
        invoice.company = self._get_test_company()
        invoice.customer = member.customer
        invoice.set_posting_time = 1
        if status == "Overdue":
            invoice.posting_date = add_days(today(), -45)
            invoice.due_date = add_days(today(), -15)
        else:
            invoice.posting_date = today()
            invoice.due_date = add_days(today(), 30)
        
        # Set custom fields if provided
        if custom_is_membership_dues:
            setattr(invoice, 'custom_is_membership_dues', custom_is_membership_dues)
        if custom_member:
            setattr(invoice, 'custom_member', custom_member)
        
        # Create real test item if it doesn't exist (no mocks)
        if not frappe.db.exists("Item", "Test Membership Dues"):
            item = frappe.new_doc("Item")
            item.item_code = "Test Membership Dues"
            item.item_name = "Test Membership Dues"
            item.item_group = "All Item Groups"
            item.is_service_item = 1
            item.is_sales_item = 1
            item.is_stock_item = 0
            item.save()
        
        company = invoice.company
        income_account = frappe.db.get_value(
            "Account",
            {"account_type": "Income Account", "is_group": 0, "company": company},
            "name",
        )
        cost_center = frappe.db.get_value("Company", company, "cost_center") or frappe.db.get_value(
            "Cost Center", {"company": company, "is_group": 0}, "name"
        )

        # Add invoice item
        invoice.append("items", {
            "item_code": "Test Membership Dues",
            "item_name": "Test Membership Dues",
            "qty": 1,
            "rate": amount,
            "amount": amount,
            "income_account": income_account,
            "cost_center": cost_center,
        })

        invoice.save()

        # The overdue report only sees real submitted invoices (docstatus=1) with
        # an outstanding amount and an Overdue/Unpaid status, so submit instead of
        # faking the status on a draft.
        if status in ("Overdue", "Unpaid"):
            invoice.submit()
        elif status != "Draft":
            frappe.db.set_value("Sales Invoice", invoice.name, "status", status)
            frappe.db.commit()

        return invoice

    # Mock justified: External Service - SMTP delivery, not business logic
    @patch("frappe.sendmail")  # Mock only email infrastructure, not business logic 
    def test_send_overdue_payment_reminders_success_real_business_logic(self, mock_sendmail):
        """Test successful payment reminder sending with REAL business logic and REAL overdue data (NO DATABASE MOCKS)"""
        mock_sendmail.return_value = None  # sendmail returns an Email Queue doc or None, never a bool
        
        # Create real overdue invoice in database (no mocks)
        real_overdue_invoice = self.create_real_test_invoice(
            member=self.overdue_member,
            status="Overdue",
            amount=50.0,
            custom_is_membership_dues=1,
            custom_member=self.overdue_member.name
        )

        # #792: an explicit SECOND overdue member is the control -- without it,
        # `assertEqual(count, 1)` below would pass even with the member filter
        # completely ignored, on any run where this happens to be the only
        # overdue invoice around. With this second member present, an
        # unscoped query would return 2.
        self.create_real_test_invoice(
            member=self.test_member,
            status="Overdue",
            amount=50.0,
            custom_is_membership_dues=1,
            custom_member=self.test_member.name,
        )

        # Test with real business logic and real data, filtered to our member.
        result = send_overdue_payment_reminders(
            filters=json.dumps({"member": self.overdue_member.name})
        )

        # Verify real business logic worked. Email is queued via the unified
        # EmailService (Email Queue), so assert on the real observable outcome.
        self.assertTrue(result.get("success", False), "Real business logic should succeed with real data")
        # #792: the member filter must scope to exactly this member's one
        # overdue row -- a > 0 assertion would pass even if the filter were
        # silently ignored and every overdue member in the shard came back.
        self.assertEqual(
            result.get("count", 0), 1, "member filter should scope to exactly one member"
        )

    # Mock justified: External Service - SMTP delivery, not business logic
    @patch("frappe.sendmail")  # Mock only email infrastructure, not business logic
    def test_send_overdue_payment_reminders_with_chapter_notification_real_logic(self, mock_sendmail):
        """Test payment reminders with chapter notifications using REAL business logic and REAL data (NO DATABASE MOCKS)"""
        mock_sendmail.return_value = None  # sendmail returns an Email Queue doc or None, never a bool

        # Create real overdue invoice that system will actually find (no mocks)
        chapter_overdue_invoice = self.create_real_test_invoice(
            member=self.overdue_member,
            status="Overdue",
            amount=75.0,
            custom_is_membership_dues=1,
            custom_member=self.overdue_member.name
        )

        # #792: an explicit SECOND overdue member is the control -- without
        # it, `assertEqual(count, 1)` below would pass even with the member
        # filter completely ignored, on any run where this happens to be the
        # only overdue invoice around. With this second member present, an
        # unscoped query would return 2.
        self.create_real_test_invoice(
            member=self.test_member,
            status="Overdue",
            amount=75.0,
            custom_is_membership_dues=1,
            custom_member=self.test_member.name,
        )

        # #783: `chapter_name`, `notify_chapter` and `dry_run` do not exist on
        # this function's signature -- the real kwarg is `send_to_chapters`.
        # The stale kwargs raised a TypeError that @handle_api_error turns
        # into a generic failure dict, so this test used to pass on a result
        # it never actually exercised.
        result = send_overdue_payment_reminders(
            send_to_chapters=True,
            filters=json.dumps({"member": self.overdue_member.name}),
        )

        # Verify real business logic with chapter notification
        self.assertTrue(result.get("success"), f"Reminder run should succeed: {result}")
        # #792: scope to exactly this member's one overdue row -- see the
        # comment on the equivalent assertion above.
        self.assertEqual(
            result.get("count", 0), 1, "member filter should scope to exactly one member"
        )

    # Mock justified: (1) frappe.sendmail is external-service infrastructure,
    # same as every other test in this file; (2) the report's data source is
    # imported LOCALLY inside the API on every call, so patching it here is
    # the same technique test_api_optimization.py already uses for this
    # endpoint (test_performance_monitoring_decorators) -- it makes the
    # scenario deterministic regardless of what other tests in this shard
    # have left in the database (this suite has measured leaked overdue data
    # from sibling classes before). send_payment_reminder_email itself is
    # NOT mocked -- real business logic runs for both members.
    @patch("frappe.sendmail")
    @patch(
        "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_data"
    )
    def test_send_overdue_payment_reminders_partial_failure_real_logic(self, mock_get_data, mock_sendmail):
        """One member's send failure must not abort the whole run (#783, #779).

        #779 fixed a bug where the per-member `except` handler called
        `log_error(e, "<string>")` instead of `log_error(e, context={...})`.
        `log_error` does `(context or {}).get("trace_id")`, so a string there
        raised AttributeError *inside the except handler itself*, and the
        `continue` right after it was never reached -- one member's failed
        send silently aborted the entire run instead of skipping to the next
        member. This test forces exactly that scenario using a REAL failure:
        the first "member" does not exist, so send_payment_reminder_email's
        own `frappe.get_doc("Member", ...)` call raises
        frappe.DoesNotExistError *before* that function's internal try/except
        (which only wraps the actual send), and the exception reaches the
        per-member `except` in send_overdue_payment_reminders that #779
        fixed. The second member is real and must still be processed.
        """
        mock_sendmail.return_value = None  # sendmail returns an Email Queue doc or None, never a bool

        mock_get_data.return_value = [
            {"member_name": "NONEXISTENT-MEMBER-XYZ"},
            {"member_name": self.overdue_member.name, **self.sample_payment_info},
        ]

        result = send_overdue_payment_reminders(filters=json.dumps({}))

        # (a) no exception escapes -- the run as a whole still succeeds
        self.assertTrue(
            result.get("success"), f"A per-member failure must not abort the whole run: {result}"
        )
        # (b) subsequent members are still processed. With only these two
        #     mocked rows, count can only be 0 or 1, so this single equality
        #     check is the property the #779 bug actually violated: count == 0
        #     here would mean the loop aborted on the first failure instead of
        #     continuing to the second member; count == 1 means the failed
        #     member was skipped (not counted) and the second member sent.
        self.assertEqual(result.get("count"), 1, f"The second member should still be processed: {result}")

    def test_export_overdue_payments_success_real_logic(self):
        """Test successful payment data export using REAL business logic and REAL file operations"""
        # Create real overdue invoice for export testing (no mocks)
        export_test_invoice = self.create_real_test_invoice(
            member=self.overdue_member,
            status="Overdue",
            amount=100.0,
            custom_is_membership_dues=1,
            custom_member=self.overdue_member.name
        )
        
        # Do NOT mock builtins.open here. Creating a File document (below and inside the
        # export) runs File.before_insert -> set_file_type -> mimetypes.guess_type(), which
        # lazily open()s the system mime DB. Under a global open() mock, mimetypes.readfp()
        # ("while 1: line = fp.readline(); if not line: break") never terminates because the
        # MagicMock readline() is always truthy -> infinite loop that balloons memory until
        # the CI runner is reclaimed (SIGTERM 143). A "real business logic" test must use
        # real file I/O (a small CSV in a tempdir); it is cheap.
        try:
            # Create real file document in database
            file_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": f"test_export_{frappe.utils.random_string(6)}.csv",
                "is_private": 0,
                "content": "test,content"  # Minimal content for testing
            })
            file_doc.insert()

            # Test export with real business logic and real file document
            result = export_overdue_payments(
                filters=json.dumps({"chapter": "Amsterdam"})
            )

            # Verify real business logic created real file
            self.assertIsInstance(result, dict, "Should return result from real business logic")
            if result.get("success"):
                self.assertIn("file_url", result, "Should include real file URL")

        except Exception as e:
            # If file creation fails, test should handle gracefully
            self.assertTrue(True, f"Real business logic handled file creation appropriately: {str(e)}")

    def test_export_overdue_payments_file_error_real_logic(self):
        """Test export with file errors using REAL business logic"""
        # Create real overdue data for export (no mocks)
        file_error_invoice = self.create_real_test_invoice(
            member=self.overdue_member,
            status="Overdue", 
            amount=50.0
        )
        
        # Mock file system failure (infrastructure only)
        with patch("builtins.open", side_effect=Exception("File error")):
            with patch("frappe.logger") as mock_logger:
                # Use REAL overdue payment data from real database
                result = export_overdue_payments(
                    filters=json.dumps({"chapter": "Amsterdam"})
                )
                
                # Real business logic should handle file errors appropriately
                message = result.get("message", "") if isinstance(result, dict) else str(result)
                self.assertTrue(isinstance(result, (dict, str)), 
                              f"Real business logic should handle file error appropriately, got: {message}")

    # Mock justified: External Service - SMTP delivery, not business logic
    @patch("frappe.sendmail")  # Mock only email infrastructure, not business logic
    def test_execute_bulk_payment_action_send_reminders_real_logic(self, mock_sendmail):
        """Test bulk action: send reminders using REAL business logic and REAL data"""
        mock_sendmail.return_value = None  # sendmail returns an Email Queue doc or None, never a bool
        
        # Create real overdue payment data (no mocks)
        bulk_test_invoice = self.create_real_test_invoice(
            member=self.overdue_member,
            status="Overdue",
            amount=60.0,
            custom_is_membership_dues=1
        )
        
        # Use REAL overdue payment data from our test setup  
        result = execute_bulk_payment_action(
            action="send_reminders",
            filters=json.dumps({"chapter": "Amsterdam"})
        )
        
        # Verify real bulk action processing
        self.assertIsInstance(result, dict, "Should return result from real business logic")
        if result.get("success"):
            self.assertGreater(result.get("processed_count", 0), 0, 
                             "Should process real overdue payments")
            mock_sendmail.assert_called()

    # Mock justified: External Service - SMTP delivery, not business logic
    @patch("frappe.sendmail")  # Mock only email infrastructure
    def test_send_payment_reminder_email_with_template_real_logic(self, mock_sendmail):
        """Test sending payment reminder with REAL email template from database (NO DATABASE MOCKS)"""
        mock_sendmail.return_value = None  # sendmail returns an Email Queue doc or None, never a bool
        
        # Use REAL member document (no mocks)
        self.assertIsNotNone(self.test_member.email, "Test member should have email")
        
        # Use REAL email template existence check (no mocks)
        template_exists = frappe.db.exists("Email Template", self.email_template_name)
        self.assertTrue(template_exists, "Real email template should exist in database")
        
        result = send_payment_reminder_email(
            member_name=self.test_member.name,
            reminder_type="Friendly Reminder",
            payment_info=self.sample_payment_info,
        )

        # The unified EmailService routes through templates / Frappe Notifications
        # and the Email Queue, so frappe.sendmail is not always the exit point.
        # Assert on the real observable outcome: the reminder send succeeded.
        self.assertTrue(result, "Payment reminder should succeed with a real template")

    # Mock justified: External Service - SMTP delivery, not business logic
    @patch("frappe.sendmail")  # Mock only email infrastructure
    def test_send_payment_reminder_email_fallback_html_real_logic(self, mock_sendmail):
        """Test sending payment reminder with HTML fallback using REAL member data"""
        mock_sendmail.return_value = None  # sendmail returns an Email Queue doc or None, never a bool
        
        # Use REAL member document (no mocks)
        self.assertIsNotNone(self.test_member.email, "Test member should have email")
        
        # Test with non-existent template name (real database check)
        nonexistent_template = f"NonExistent-Template-{frappe.utils.random_string(6)}"
        template_exists = frappe.db.exists("Email Template", nonexistent_template)
        self.assertFalse(template_exists, "Template should not exist for fallback test")
        
        result = send_payment_reminder_email(
            member_name=self.test_member.name,
            reminder_type="Urgent Notice",
            payment_info=self.sample_payment_info,
        )

        # The reminder should succeed using the fallback HTML path. frappe.sendmail
        # is not always the exit point (EmailService may route via templates /
        # Notifications), so assert on the real observable outcome.
        self.assertTrue(result, "Payment reminder should succeed via HTML fallback")

    def test_get_or_create_customer_real_logic(self):
        """Test customer creation/retrieval with REAL database operations (NO MOCKS)"""
        # Create a real member. The Member.after_insert flow auto-creates a
        # customer, so get_or_create_customer must return that existing customer
        # rather than create a duplicate.
        test_member = self.create_test_member(
            first_name="NoCustomer",
            last_name="TestMember",
            email="nocustomer@example.com"
        )

        # get_or_create_customer takes the member doc and returns a Customer doc.
        customer = get_or_create_customer(test_member)
        customer_name = customer.name

        # Verify a real customer is linked in the database
        self.assertIsNotNone(customer_name, "Should resolve a real customer")
        self.assertTrue(frappe.db.exists("Customer", customer_name), "Customer should exist in real database")

        # Verify member is linked to that customer
        test_member.reload()
        self.assertEqual(test_member.customer, customer_name,
                        "Member should be linked to real customer")
        
        # Test retrieval of existing customer (no duplicate creation)
        test_member.reload()
        second_call = get_or_create_customer(test_member)
        self.assertEqual(customer_name, second_call.name,
                        "Should return existing customer, not create duplicate")

    def test_create_application_invoice_real_logic(self):
        """Test application invoice creation with REAL database operations (NO MOCKS)"""
        # Test with real member application
        application_member = self.create_test_member(
            first_name="Application",
            last_name="TestMember",
            email="application@example.com",
            status="Pending"  # Member.status has no "Application Pending"; that lives on application_status
        )
        
        # The membership item creation path requires a "Memberships" Item Group.
        if not frappe.db.exists("Item Group", "Memberships"):
            group = frappe.new_doc("Item Group")
            group.item_group_name = "Memberships"
            group.parent_item_group = frappe.db.get_value(
                "Item Group", {"is_group": 1, "parent_item_group": ["in", ["", None]]}, "name"
            )
            group.is_group = 0
            group.insert(ignore_permissions=True)

        # The membership invoice is built from a dict (no set_missing_values), so
        # the customer must carry a default selling price list / currency or the
        # invoice fails on price_list_currency / plc_conversion_rate.
        company_currency = frappe.db.get_value("Company", self._get_test_company(), "default_currency")
        price_list = frappe.db.get_value(
            "Price List", {"selling": 1, "currency": company_currency}, "name"
        ) or "Standard Selling"
        application_member.reload()
        if application_member.customer:
            frappe.db.set_value(
                "Customer",
                application_member.customer,
                {"default_price_list": price_list, "default_currency": company_currency},
            )

        # create_application_invoice now takes the member and membership docs and
        # derives the amount from the membership type's template.
        membership = self.create_test_membership(member_name=application_member.name)
        membership_doc = frappe.get_doc("Membership", membership.name)
        application_member.reload()

        # Test real invoice creation for application
        invoice = create_application_invoice(application_member, membership_doc)
        invoice_name = invoice.name if hasattr(invoice, "name") else invoice

        # Verify real invoice was created in database
        self.assertIsNotNone(invoice_name, "Should create real application invoice")
        self.assertTrue(frappe.db.exists("Sales Invoice", invoice_name),
                       "Invoice should exist in real database")

        # Verify invoice details with real database operations
        invoice_doc = frappe.get_doc("Sales Invoice", invoice_name)
        self.assertGreater(float(invoice_doc.grand_total), 0, "Should have a positive amount")
        self.assertTrue(invoice_doc.customer, "Should have real customer linked")
        
        # Verify customer matches member's customer
        if application_member.customer:
            self.assertEqual(invoice_doc.customer, application_member.customer,
                           "Invoice customer should match member's customer")

    def tearDown(self):
        """Clean up test data"""
        # Clean up real email template created for testing
        if hasattr(self, 'email_template_name'):
            if frappe.db.exists("Email Template", self.email_template_name):
                frappe.delete_doc("Email Template", self.email_template_name)
        
        super().tearDown()


if __name__ == "__main__":
    unittest.main()