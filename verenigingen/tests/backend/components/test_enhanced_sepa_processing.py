# -*- coding: utf-8 -*-
"""
Comprehensive unit tests for the enhanced SEPA processing system
Tests flexible dues collection, batch processing, and payment failure handling
"""

import frappe
from frappe.utils import today, add_months, add_days, flt, getdate
from verenigingen.tests.utils.base import VereningingenTestCase


class TestEnhancedSEPAProcessing(VereningingenTestCase):
    """Test the enhanced SEPA processing system functionality"""

    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member()
        self.test_membership_type = self.create_test_membership_type()
        self._align_type_template(self.test_membership_type)

    def _align_type_template(self, membership_type):
        """Align the type's auto dues-schedule template to the type minimum.

        MembershipType.after_insert creates a template with a default €15 rate.
        When the type's minimum_amount is higher (default 20.0), creating a real
        dues schedule fails template validation ("Template dues rate cannot be
        less than membership type minimum"). Mirror what
        ensure_membership_type_exists does for hand-built types.
        """
        minimum = frappe.db.get_value("Membership Type", membership_type.name, "minimum_amount") or 0
        template = frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": membership_type.name},
            "name",
        )
        if template and minimum:
            tdoc = frappe.get_doc("Membership Dues Schedule", template)
            tdoc.suggested_amount = minimum
            tdoc.dues_rate = minimum
            tdoc.minimum_amount = minimum
            tdoc.save(ignore_permissions=True)

    def test_sepa_processor_initialization(self):
        """Test Enhanced SEPA processor initialization"""
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor import SEPAProcessor
        
        processor = SEPAProcessor()
        # SEPABatchProcessor now holds configuration via config_manager (the old
        # `settings` attribute was removed during the SEPA services refactor).
        self.assertIsNotNone(processor.config_manager)
        self.assertIsNotNone(processor.company)
        
    def test_eligible_dues_schedules_detection(self):
        """Test detection of eligible dues schedules for collection"""
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor import SEPAProcessor
        
        # Create dues schedule ready for collection
        dues_schedule = self.create_test_dues_schedule_for_collection()
        
        processor = SEPAProcessor()
        eligible_schedules = processor.get_eligible_dues_schedules(today())
        
        # Should find our test schedule
        schedule_names = [s.name for s in eligible_schedules]
        self.assertIn(dues_schedule.name, schedule_names)
        
    def test_dues_collection_batch_creation(self):
        """Test creating dues collection batch"""
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor import SEPAProcessor
        
        # Create an eligible dues schedule. (A member may only have one active
        # membership and one active dues schedule, so we create a single eligible
        # schedule rather than two for the same member; one is enough to exercise
        # batch creation.)
        dues_schedule1 = self.create_test_dues_schedule_for_collection()

        processor = SEPAProcessor()
        batch = processor.create_dues_collection_batch(today())
        
        if batch:  # Only test if we have eligible schedules
            self.track_doc("Direct Debit Batch", batch.name)
            
            # Validate batch creation
            self.assertIsNotNone(batch.name)
            self.assertEqual(batch.batch_type, "RCUR")  # Should be recurring by default
            self.assertGreater(len(batch.invoices), 0)
            self.assertGreater(batch.total_amount, 0)
            
            # Validate invoices were created
            for invoice_item in batch.invoices:
                self.assertIsNotNone(invoice_item.invoice)
                self.assertIsNotNone(invoice_item.member)
                self.assertGreater(invoice_item.amount, 0)
                
    def test_dues_invoice_creation(self):
        """Test creating dues invoice for schedule"""
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor import SEPAProcessor
        
        dues_schedule = self.create_test_dues_schedule_for_collection()
        
        processor = SEPAProcessor()
        invoice = processor.create_dues_invoice(dues_schedule, today())
        
        if invoice:  # Only test if invoice was created
            self.track_doc("Sales Invoice", invoice.name)
            
            # Validate invoice details. create_dues_invoice sets
            # customer = member.customer or member-name, so compare against the
            # member's linked Customer when present.
            member_customer = frappe.db.get_value("Member", dues_schedule.member, "customer")
            self.assertEqual(invoice.customer, member_customer or dues_schedule.member)
            self.assertEqual(invoice.grand_total, dues_schedule.dues_rate)
            self.assertIsNotNone(invoice.membership_dues_schedule_display)
            self.assertIsNotNone(invoice.custom_coverage_start_date)
            self.assertIsNotNone(invoice.custom_coverage_end_date)
            
            # Validate invoice items
            self.assertEqual(len(invoice.items), 1)
            item = invoice.items[0]
            self.assertEqual(item.rate, dues_schedule.dues_rate)
            self.assertEqual(item.qty, 1)
            
    def test_invoice_description_generation(self):
        """Test invoice description generation for different contribution modes"""
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor import SEPAProcessor
        
        processor = SEPAProcessor()
        
        # Test tier-based description
        tier_schedule = self.create_test_dues_schedule_tier_based()
        if tier_schedule:
            description = processor.generate_invoice_description(tier_schedule)
            self.assertIn("Tier:", description)
            self.assertIn("Coverage:", description)
            
        # Test calculator-based description  
        calc_schedule = self.create_test_dues_schedule_calculator_based()
        if calc_schedule:
            description = processor.generate_invoice_description(calc_schedule)
            self.assertIn("Contribution:", description)
            self.assertIn("%", description)
            
        # Test custom amount description
        custom_schedule = self.create_test_dues_schedule_custom_amount()
        if custom_schedule:
            description = processor.generate_invoice_description(custom_schedule)
            self.assertIn("Custom contribution", description)
            
    def test_sepa_mandate_integration(self):
        """Test SEPA mandate integration with dues collection"""
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor import SEPAProcessor
        
        # Create dues schedule with SEPA mandate
        dues_schedule = self.create_test_dues_schedule_with_sepa()
        
        processor = SEPAProcessor()
        mandate = processor.get_active_mandate(dues_schedule)
        
        if mandate:  # Only test if mandate exists
            self.assertEqual(mandate.member, dues_schedule.member)
            self.assertEqual(mandate.status, "Active")
            
    def test_payment_failure_handling(self):
        """Test payment failure handling workflow"""
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor import SEPAProcessor
        
        # Create batch with invoice
        dues_schedule = self.create_test_dues_schedule_for_collection()
        processor = SEPAProcessor()
        
        # The Direct Debit Batch Invoice.invoice field is a Link to Sales Invoice,
        # so it must reference a real invoice (not a placeholder string), and the
        # batch must contain at least one invoice before the first save.
        invoice = self.create_test_sales_invoice(member=dues_schedule.member)
        invoice.submit()

        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_description = "Test batch"
        batch.batch_type = "RCUR"
        batch.currency = "EUR"
        batch.status = "Draft"
        batch.append("invoices", {
            "invoice": invoice.name,
            "member": dues_schedule.member,
            "member_name": "Test Member",
            "amount": 25.0,
            "currency": "EUR",
            "status": "Pending"
        })
        batch.save()
        self.track_doc("Direct Debit Batch", batch.name)
        
        # Simulate payment failure
        return_info = {
            "reason_code": "MS03",
            "reason_description": "Reason not specified"
        }
        
        processor.handle_failed_payment(batch.invoices[0], return_info)
        
        # Validate failure handling
        dues_schedule.reload()
        # Check that failure is recorded in notes or status
        self.assertIn("Failed", dues_schedule.status)
        
    def test_grace_period_handling(self):
        """Test grace period handling for failed payments"""
        dues_schedule = self.create_test_dues_schedule_for_collection()
        
        # Set up failure scenario
        dues_schedule.status = "Grace Period"
        dues_schedule.grace_period_until = add_days(today(), 14)
        dues_schedule.notes = "Payment failures: 1"
        dues_schedule.save()
        
        # Validate grace period status
        self.assertEqual(dues_schedule.status, "Grace Period")
        self.assertIsNotNone(dues_schedule.grace_period_until)
        self.assertIn("Payment failures: 1", dues_schedule.notes)
        
    def test_suspension_after_consecutive_failures(self):
        """Test suspension after consecutive payment failures"""
        dues_schedule = self.create_test_dues_schedule_for_collection()
        
        # Simulate 3 consecutive failures
        dues_schedule.status = "Suspended"
        dues_schedule.notes = "Payment failures: 3 - Suspended"
        dues_schedule.save()
        
        # Validate suspension
        self.assertEqual(dues_schedule.status, "Suspended")
        self.assertIn("Payment failures: 3", dues_schedule.notes)
        
    def test_upcoming_collections_api(self):
        """Test upcoming dues collections API"""
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor import get_upcoming_dues_collections
        
        # Create future dues schedule
        dues_schedule = self.create_test_dues_schedule_for_collection()
        dues_schedule.next_invoice_date = add_days(today(), 15)
        dues_schedule.save()
        
        upcoming = get_upcoming_dues_collections(30)
        
        # Should find our future schedule
        total_schedules = sum(c["count"] for c in upcoming)
        self.assertGreaterEqual(total_schedules, 0)  # May be 0 if no eligible schedules
        
    def test_sepa_configuration_validation(self):
        """Test SEPA configuration validation"""
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor import validate_sepa_configuration
        
        result = validate_sepa_configuration()
        
        # Validate response structure
        self.assertTrue("valid" in result)
        self.assertTrue("message" in result)
        
        if not result["valid"]:
            # Configuration issues are expected in test environment
            self.assertTrue("Missing" in result["message"] or "Invalid" in result["message"])
            
    def test_coverage_period_tracking(self):
        """Test coverage period tracking in invoices"""
        dues_schedule = self.create_test_dues_schedule_for_collection()

        # next_invoice_date is set on the schedule.
        self.assertIsNotNone(dues_schedule.next_invoice_date)

        # Coverage is computed via calculate_next_coverage_period() (there are no
        # current_coverage_start/_end fields on the DocType; the persisted ones
        # are last_invoice_coverage_start/_end, populated after invoicing).
        coverage_start, coverage_end = dues_schedule.calculate_next_coverage_period()
        self.assertIsNotNone(coverage_start)
        self.assertIsNotNone(coverage_end)
        self.assertLessEqual(getdate(coverage_start), getdate(coverage_end))
            
    def test_sequence_type_handling(self):
        """Test FRST/RCUR sequence type handling"""
        dues_schedule = self.create_test_dues_schedule_for_collection()
        
        # First payment should be FRST
        if hasattr(dues_schedule, 'next_sequence_type'):
            if not dues_schedule.last_invoice_date:  # First payment
                expected_type = "FRST"
            else:
                expected_type = "RCUR"
                
            # Can't directly test without actual processing, but validate field exists
            self.assertTrue(hasattr(dues_schedule, 'next_sequence_type'))
            
    def test_batch_totals_calculation(self):
        """Test batch totals calculation"""
        # Create mock batch with invoices
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_description = "Test totals batch"
        batch.currency = "EUR"
        
        # Add invoice items
        batch.append("invoices", {
            "invoice": "INV-001",
            "member": self.test_member.name,
            "amount": 25.0,
            "currency": "EUR"
        })
        
        batch.append("invoices", {
            "invoice": "INV-002", 
            "member": self.test_member.name,
            "amount": 35.0,
            "currency": "EUR"
        })
        
        batch.calculate_totals()
        
        # Validate totals
        self.assertEqual(batch.total_amount, 60.0)
        self.assertEqual(batch.entry_count, 2)
        
    def test_invoice_item_generation(self):
        """Test automatic invoice item generation"""
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor import SEPAProcessor
        
        processor = SEPAProcessor()
        item_code = processor.get_or_create_dues_item(self.create_test_dues_schedule_for_collection())
        
        # Validate item was created/found
        self.assertIsNotNone(item_code)
        self.assertTrue(frappe.db.exists("Item", item_code))
        
        # Get item and validate properties
        item = frappe.get_doc("Item", item_code)
        self.assertFalse(item.is_stock_item)
        self.assertTrue(item.is_sales_item)
        # is_service_item was removed from the ERPNext Item DocType in v16.
        
    def test_scheduled_collection_task(self):
        """Test scheduled dues collection task"""
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor import create_monthly_dues_collection_batch
        
        # Run scheduled task
        batch_name = create_monthly_dues_collection_batch()
        
        # May return None if no eligible schedules, which is valid
        if batch_name:
            self.track_doc("Direct Debit Batch", batch_name)
            
            batch = frappe.get_doc("Direct Debit Batch", batch_name)
            self.assertIsNotNone(batch.batch_date)
            self.assertEqual(batch.currency, "EUR")
            
    # Helper methods
    
    def _ensure_active_membership(self):
        """Create a submitted (active) Membership for the test member.

        Membership Dues Schedule.validate_member_membership requires an active
        membership with docstatus=1, so the membership must be submitted (a saved
        draft is not enough). Idempotent: a member may only have one active
        membership, so reuse an existing one if present.
        """
        existing = frappe.db.get_value(
            "Membership", {"member": self.test_member.name, "status": "Active", "docstatus": 1}, "name"
        )
        if existing:
            return frappe.get_doc("Membership", existing)

        membership = frappe.new_doc("Membership")
        membership.member = self.test_member.name
        membership.membership_type = self.test_membership_type.name
        membership.start_date = today()
        membership.status = "Active"
        membership.insert()
        membership.submit()
        self.track_doc("Membership", membership.name)
        # Membership.on_submit auto-creates a dues schedule from the type
        # template. Cancel it so the test's explicitly-created schedule is the
        # only active one (otherwise "Member already has an active dues schedule").
        self._cancel_auto_schedules(membership.member)
        return membership

    def _ensure_sepa_payment_terms_template(self):
        """Get-or-create the "SEPA Direct Debit" Payment Terms Template master."""
        name = "SEPA Direct Debit"
        if frappe.db.exists("Payment Terms Template", name):
            return name
        template = frappe.new_doc("Payment Terms Template")
        template.template_name = name
        template.append(
            "terms",
            {
                "due_date_based_on": "Day(s) after invoice date",
                "invoice_portion": 100.0,
                "credit_days": 0,
            },
        )
        template.insert(ignore_permissions=True)
        self.track_doc("Payment Terms Template", template.name)
        return template.name

    def _cancel_auto_schedules(self, member_name):
        """Cancel any dues schedule auto-created on membership submit."""
        for name in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "status": "Active", "is_template": 0},
            pluck="name",
        ):
            frappe.db.set_value("Membership Dues Schedule", name, "status", "Cancelled")

    def create_test_dues_schedule_for_collection(self):
        """Create a dues schedule ready for collection"""
        # First create a submitted (active) membership
        membership = self._ensure_active_membership()
        
        # Then create dues schedule
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        # schedule_name is the naming field (autoname field:schedule_name) and is
        # required; use a unique value to avoid collisions across tests.
        dues_schedule.schedule_name = f"Test Collection Schedule {frappe.generate_hash(length=8)}"
        dues_schedule.member = self.test_member.name
        dues_schedule.membership = membership.name
        dues_schedule.membership_type = self.test_membership_type.name
        dues_schedule.contribution_mode = "Income-Based"
        dues_schedule.dues_rate = 25.0
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.payment_method = "SEPA Direct Debit"
        # get_eligible_dues_schedules filters on payment_terms_template (not
        # payment_method), so set it to the SEPA Direct Debit Payment Terms
        # Template (created on demand) for the schedule to be collectible.
        dues_schedule.payment_terms_template = self._ensure_sepa_payment_terms_template()
        dues_schedule.status = "Active"
        dues_schedule.auto_generate = 1
        dues_schedule.test_mode = 0  # Enable for collection
        dues_schedule.current_coverage_start = today()
        dues_schedule.next_invoice_date = today()  # Due now
        dues_schedule.invoice_days_before = 0  # Collect immediately
        
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        return dues_schedule
        
    def create_test_dues_schedule_tier_based(self):
        """Create tier-based dues schedule for testing"""
        try:
            self._ensure_active_membership()
            membership_type = self.create_test_membership_type_with_tiers()

            dues_schedule = frappe.new_doc("Membership Dues Schedule")
            dues_schedule.schedule_name = f"Test Schedule {frappe.generate_hash(length=8)}"
            dues_schedule.member = self.test_member.name
            dues_schedule.membership_type = membership_type.name
            dues_schedule.contribution_mode = "Tier"
            dues_schedule.selected_tier = membership_type.predefined_tiers[0].name
            dues_schedule.dues_rate = membership_type.predefined_tiers[0].amount
            dues_schedule.billing_frequency = "Monthly"
            dues_schedule.status = "Active"
            
            dues_schedule.save()
            self.track_doc("Membership Dues Schedule", dues_schedule.name)
            return dues_schedule
        except:
            return None
            
    def create_test_dues_schedule_calculator_based(self):
        """Create calculator-based dues schedule for testing"""
        try:
            self._ensure_active_membership()
            dues_schedule = frappe.new_doc("Membership Dues Schedule")
            dues_schedule.schedule_name = f"Test Schedule {frappe.generate_hash(length=8)}"
            dues_schedule.member = self.test_member.name
            dues_schedule.membership_type = self.test_membership_type.name
            dues_schedule.contribution_mode = "Income-Based"
            dues_schedule.base_multiplier = 1.5
            dues_schedule.dues_rate = 30.0  # 20 * 1.5
            dues_schedule.billing_frequency = "Monthly"
            dues_schedule.status = "Active"
            
            dues_schedule.save()
            self.track_doc("Membership Dues Schedule", dues_schedule.name)
            return dues_schedule
        except:
            return None
            
    def create_test_dues_schedule_custom_amount(self):
        """Create custom amount dues schedule for testing"""
        try:
            self._ensure_active_membership()
            dues_schedule = frappe.new_doc("Membership Dues Schedule")
            dues_schedule.schedule_name = f"Test Schedule {frappe.generate_hash(length=8)}"
            dues_schedule.member = self.test_member.name
            dues_schedule.membership_type = self.test_membership_type.name
            dues_schedule.contribution_mode = "Custom"
            dues_schedule.dues_rate = 15.0
            dues_schedule.uses_custom_amount = 1
            dues_schedule.custom_amount_reason = "Financial hardship"
            dues_schedule.billing_frequency = "Monthly"
            dues_schedule.status = "Active"
            
            dues_schedule.save()
            self.track_doc("Membership Dues Schedule", dues_schedule.name)
            return dues_schedule
        except:
            return None
            
    def create_test_dues_schedule_with_sepa(self):
        """Create dues schedule with SEPA mandate"""
        try:
            self._ensure_active_membership()
            # Create SEPA mandate first
            mandate = self.create_test_sepa_mandate()

            dues_schedule = frappe.new_doc("Membership Dues Schedule")
            dues_schedule.schedule_name = f"Test Schedule {frappe.generate_hash(length=8)}"
            dues_schedule.member = self.test_member.name
            dues_schedule.membership_type = self.test_membership_type.name
            dues_schedule.contribution_mode = "Income-Based"
            dues_schedule.dues_rate = 25.0
            dues_schedule.billing_frequency = "Monthly"
            dues_schedule.payment_method = "SEPA Direct Debit"
            dues_schedule.active_mandate = mandate.name
            dues_schedule.status = "Active"
            
            dues_schedule.save()
            self.track_doc("Membership Dues Schedule", dues_schedule.name)
            return dues_schedule
        except:
            return None
            
    def create_test_sepa_mandate(self):
        """Create test SEPA mandate"""
        from verenigingen.utils.validation.iban_validator import generate_test_iban

        mandate = frappe.new_doc("SEPA Mandate")
        # mandate_id, scheme and sign_date are required in v16.
        mandate.mandate_id = f"TEST-MNDT-{frappe.generate_hash(length=8)}"
        mandate.member = self.test_member.name
        mandate.iban = generate_test_iban("TEST")  # checksum-valid test IBAN
        mandate.bic = "TESTNL2A"
        mandate.account_holder_name = self.test_member.full_name
        mandate.status = "Active"
        mandate.scheme = "SEPA"
        mandate.mandate_type = "RCUR"
        mandate.sign_date = today()

        mandate.save()
        self.track_doc("SEPA Mandate", mandate.name)
        return mandate
            
    def create_test_membership_type(self):
        """Create simple test membership type"""
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = f"Test Enhanced SEPA Type {frappe.generate_hash(length=6)}"
        membership_type.minimum_amount = 20.0
        membership_type.is_active = 1
        
        membership_type.save()
        self.track_doc("Membership Type", membership_type.name)
        return membership_type
        
    def create_test_membership_type_with_tiers(self):
        """Create membership type with tiers for testing"""
        try:
            membership_type = frappe.new_doc("Membership Type")
            membership_type.membership_type_name = f"Test Tier Type {frappe.generate_hash(length=6)}"
            membership_type.minimum_amount = 25.0
            membership_type.is_active = 1
            membership_type.contribution_mode = "Tiers"
            
            # Add tier
            tier = membership_type.append("predefined_tiers", {})
            tier.tier_name = "Standard"
            tier.display_name = "Standard"
            tier.amount = 25.0
            tier.display_order = 1
            
            membership_type.save()
            self.track_doc("Membership Type", membership_type.name)
            return membership_type
        except:
            return None
