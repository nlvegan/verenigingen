"""
Safety Test: Verify Payment Mixin Dead Code Detection

This test verifies that certain payment_mixin methods are NOT called anywhere
in the codebase before we delete them. This is a safety check to prevent
accidentally removing code that's actually in use.

Methods to be deleted (suspected dead code):
- create_payment_entry() - References non-existent fields
- process_payment() - Calls create_payment_entry
- add_to_direct_debit_batch() - References non-existent fields
- mark_as_paid() - References non-existent fields
- check_payment_status() (Member version) - References non-existent fields
- sync_payment_amount() - References non-existent fields
- set_payment_reference() - Generates reference for non-existent field

Why we believe they're dead:
- Reference fields that don't exist on Member DocType (payment_amount, start_date)
- Zero test coverage
- Not called in production code paths
- Added during incomplete refactor (mollie payment refactor commit)
"""

import os
import re
import unittest
from pathlib import Path

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPaymentMixinDeadCodeVerification(EnhancedTestCase):
    """Verify suspected dead code methods are not used"""

    # Methods we confirmed are dead code and deleted
    SUSPECTED_DEAD_METHODS = [
        'create_payment_entry',
        'process_payment',
        'add_to_direct_debit_batch',
        'mark_as_paid',
        'sync_payment_amount',
        # NOTE: set_payment_reference() is NOT dead code - payment_reference field exists on Member
    ]

    # Directories to search (exclude tests and archived)
    SEARCH_DIRS = [
        'verenigingen/verenigingen',
        'verenigingen/api',
        'verenigingen/utils',
        'verenigingen/services',
        'verenigingen/integrations',
    ]

    # Patterns that indicate actual usage (not just definition)
    USAGE_PATTERNS = [
        r'\.{method}\(',  # member.create_payment_entry(
        r'\["{method}"\]',  # member["create_payment_entry"]
        r'getattr\([^,]+,\s*"{method}"',  # getattr(member, "create_payment_entry"
        r'hasattr\([^,]+,\s*"{method}"',  # hasattr(member, "create_payment_entry"
    ]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app_path = frappe.get_app_path("verenigingen")
        cls.usage_findings = {}

    def test_01_verify_methods_deleted_from_payment_mixin(self):
        """Verify suspected dead methods were successfully deleted from payment_mixin"""
        payment_mixin_path = os.path.join(
            self.app_path,
            'verenigingen/doctype/member/mixins/payment_mixin.py'
        )

        with open(payment_mixin_path, 'r') as f:
            content = f.read()

        for method in self.SUSPECTED_DEAD_METHODS:
            self.assertNotIn(
                f'def {method}(',
                content,
                f"Method {method} should NOT exist - it was deleted as dead code but still found in payment_mixin"
            )

    def test_02_verify_member_fields_dont_exist(self):
        """Verify Member DocType doesn't have the fields these methods reference"""
        import json

        member_json_path = os.path.join(
            self.app_path,
            'verenigingen/doctype/member/member.json'
        )

        with open(member_json_path, 'r') as f:
            doctype = json.load(f)

        field_names = [f['fieldname'] for f in doctype['fields']]

        # These fields are referenced by dead code methods but don't exist
        missing_fields = [
            'payment_amount',  # Referenced by create_payment_entry, process_payment
            'start_date',      # Referenced by check_payment_status
            'payment_status',  # Referenced by check_payment_status, mark_as_paid
        ]

        for field in missing_fields:
            self.assertNotIn(
                field,
                field_names,
                f"Field '{field}' should NOT exist on Member (if it does, our analysis is wrong!)"
            )

    def test_03_search_for_method_usage_in_codebase(self):
        """Search entire codebase for usage of suspected dead methods"""

        for method in self.SUSPECTED_DEAD_METHODS:
            self.usage_findings[method] = []

            for search_dir in self.SEARCH_DIRS:
                full_path = os.path.join(self.app_path, search_dir)
                if not os.path.exists(full_path):
                    continue

                # Search all Python files
                for py_file in Path(full_path).rglob('*.py'):
                    # Skip test files and payment_mixin itself
                    if 'test_' in str(py_file) or 'payment_mixin' in str(py_file):
                        continue

                    try:
                        with open(py_file, 'r', encoding='utf-8') as f:
                            content = f.read()

                        # Check each usage pattern
                        for pattern_template in self.USAGE_PATTERNS:
                            pattern = pattern_template.format(method=method)
                            matches = re.finditer(pattern, content)

                            for match in matches:
                                # Get line number
                                line_num = content[:match.start()].count('\n') + 1

                                # Get surrounding context
                                lines = content.split('\n')
                                context_start = max(0, line_num - 2)
                                context_end = min(len(lines), line_num + 2)
                                context = '\n'.join(lines[context_start:context_end])

                                self.usage_findings[method].append({
                                    'file': str(py_file.relative_to(self.app_path)),
                                    'line': line_num,
                                    'pattern': pattern,
                                    'context': context
                                })
                    except Exception as e:
                        # Skip files that can't be read
                        pass

    def test_04_assert_no_usage_found(self):
        """Assert that none of the suspected dead methods are used"""

        # Run search first if not already done
        if not self.usage_findings:
            self.test_03_search_for_method_usage_in_codebase()

        findings_report = []
        has_usage = False

        for method, findings in self.usage_findings.items():
            if findings:
                has_usage = True
                findings_report.append(f"\n{method}: FOUND {len(findings)} usage(s)")
                for finding in findings:
                    findings_report.append(
                        f"  - {finding['file']}:{finding['line']}\n"
                        f"    Context:\n{finding['context']}\n"
                    )
            else:
                findings_report.append(f"\n{method}: ✓ No usage found (safe to delete)")

        # Print report regardless of pass/fail
        print("\n" + "="*80)
        print("DEAD CODE VERIFICATION REPORT")
        print("="*80)
        print(''.join(findings_report))
        print("="*80)

        if has_usage:
            self.fail(
                "Found usage of methods we thought were dead code! "
                "See report above. Do NOT delete these methods without investigation."
            )

    def test_05_verify_production_flow_doesnt_use_mixin(self):
        """Verify actual production payment flow doesn't use these methods"""

        # Check MembershipDuesSchedule.generate_invoice doesn't call payment_mixin
        dues_schedule_path = os.path.join(
            self.app_path,
            'verenigingen/doctype/membership_dues_schedule/membership_dues_schedule.py'
        )

        with open(dues_schedule_path, 'r') as f:
            content = f.read()

        # Verify invoice generation goes through the dedicated generation pipeline
        # (InvoiceGenerationOrchestrator -> invoice_generator), NOT the dead
        # payment_mixin. The raw frappe.new_doc("Sales Invoice") call now lives in
        # invoice_generator.py after the orchestrator extraction, so assert the
        # controller delegates to the orchestrator and that the generator does the
        # direct invoice creation.
        self.assertIn(
            "InvoiceGenerationOrchestrator",
            content,
            "MembershipDuesSchedule should generate invoices via InvoiceGenerationOrchestrator",
        )

        invoice_generator_path = os.path.join(
            self.app_path,
            "services/billing/invoice_generator.py",
        )
        with open(invoice_generator_path, "r") as f:
            generator_content = f.read()
        self.assertIn(
            'frappe.new_doc("Sales Invoice")',
            generator_content,
            "invoice_generator should create Sales Invoices directly",
        )

        # Verify it doesn't import or use payment_mixin methods
        for method in self.SUSPECTED_DEAD_METHODS:
            self.assertNotIn(
                f'.{method}(',
                content,
                f"MembershipDuesSchedule should NOT call payment_mixin.{method}"
            )

    def test_06_verify_fields_referenced_by_dead_code(self):
        """Verify the fields referenced by dead code actually don't exist"""

        # Try to create a member and access the fields dead code references
        member = self.create_test_member(
            first_name="DeadCode",
            last_name="Test"
        )

        # These should NOT exist (AttributeError expected)
        with self.assertRaises(AttributeError):
            _ = member.payment_amount

        with self.assertRaises(AttributeError):
            _ = member.start_date

        # payment_status might exist - check
        has_payment_status = hasattr(member, 'payment_status')
        if not has_payment_status:
            print("✓ Member.payment_status does not exist (as expected)")
        else:
            print(f"⚠ WARNING: Member.payment_status EXISTS with value: {member.payment_status}")
            print("  This means check_payment_status() might not be dead code!")

    def test_07_verify_deleted_methods_not_on_payment_mixin(self):
        """Verify deleted methods were removed from PaymentMixin (may exist via other mixins)"""
        import inspect

        member = self.create_test_member(
            first_name="Payment",
            last_name="Methods",
            email="payment.methods@test.com"
        )

        # Check methods that exist on Member - verify they DON'T come from PaymentMixin
        for method_name in ['process_payment', 'mark_as_paid']:
            if hasattr(member, method_name):
                method = member.__class__.__dict__.get(method_name) or getattr(member.__class__, method_name)
                source_file = inspect.getfile(method)

                # Should NOT come from payment_mixin.py
                self.assertNotIn(
                    'payment_mixin.py',
                    source_file,
                    f"{method_name} found on Member but should NOT come from payment_mixin (comes from {source_file})"
                )
                print(f"✓ {method_name} exists on Member but comes from {source_file.split('/')[-1]}, not payment_mixin.py")

        # Methods that should NOT exist anywhere on Member
        for method in ['create_payment_entry', 'add_to_direct_debit_batch', 'sync_payment_amount']:
            self.assertFalse(
                hasattr(member, method),
                f"Method {method} should NOT exist on Member at all"
            )

    def test_08_verify_financial_mixin_methods_now_accessible(self):
        """Verify FinancialMixin methods are accessible after PaymentMixin deletion (MRO fix)"""
        import inspect

        member = self.create_test_member(
            first_name="MRO",
            last_name="Test",
            email="mro.test@example.com"
        )

        # Verify process_payment exists and comes from FinancialMixin
        self.assertTrue(
            hasattr(member, 'process_payment'),
            "Member should have process_payment method (from FinancialMixin)"
        )

        # Check which class provides the method
        method = member.__class__.process_payment
        source_file = inspect.getfile(method)

        self.assertIn(
            'financial_mixin.py',
            source_file,
            f"process_payment should come from FinancialMixin after PaymentMixin deletion, got: {source_file}"
        )

        # Verify mark_as_paid exists and comes from FinancialMixin
        self.assertTrue(
            hasattr(member, 'mark_as_paid'),
            "Member should have mark_as_paid method (from FinancialMixin)"
        )

        method = member.__class__.mark_as_paid
        source_file = inspect.getfile(method)

        self.assertIn(
            'financial_mixin.py',
            source_file,
            f"mark_as_paid should come from FinancialMixin after PaymentMixin deletion, got: {source_file}"
        )

        print("\n✅ MRO Verification: FinancialMixin methods successfully accessible after PaymentMixin deletion")


def run_tests():
    """Run dead code verification tests"""
    unittest.main()


if __name__ == "__main__":
    run_tests()
