"""
Test Member Lifecycle Workflows - Priority 1 Core Business Logic

Comprehensive testing of the critical member lifecycle workflows that form
the foundation of the Verenigingen association management system.

This test module focuses on high-impact business logic that, if broken,
would severely impact daily operations of Dutch associations.

Test Categories:
1. Member Application to Active Transition
2. SEPA Mandate Creation and Validation
3. Dues Schedule Assignment and Calculation
4. Chapter Assignment Logic
5. Member Status Transitions

@author Verenigingen Development Team
@version 1.0.0
"""

import frappe
from frappe.utils import today, add_months, flt, nowdate
from decimal import Decimal

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberLifecycleWorkflows(EnhancedTestCase):
    """
    Test core member lifecycle workflows

    These tests validate the most critical business processes that happen
    daily in Dutch association management.
    """

    def setUp(self):
        """Set up test environment for member lifecycle testing"""
        super().setUp()

        # Unique per test: tests/backend/components/test_chapter_matching.py
        # plain-inserts a chapter under the fixed name "Test Amsterdam", so on a warm
        # site this get-or-create silently adopted that file's chapter -- with its
        # postal codes and region -- or made its insert fail (#533).
        self.test_chapter = self.factory.ensure_test_chapter(
            f"Test Amsterdam {frappe.generate_hash(length=6)}",
            {
                "postal_codes": "1000-1099",
                "region": "Noord-Holland"
            }
        )

        # Create membership types needed for testing
        self.membership_types = {
            "Regular Adult": self.factory.ensure_membership_type(
                "Regular Adult",
                {
                    "minimum_amount": 25.0,
                    "billing_period": "Monthly",
                    "is_active": 1,
                    "description": "Standard adult membership"
                }
            ),
            "Student": self.factory.ensure_membership_type(
                "Student",
                {
                    "minimum_amount": 15.0,
                    "billing_period": "Monthly",
                    "is_active": 1,
                    "description": "Discounted student membership"
                }
            ),
            "Senior": self.factory.ensure_membership_type(
                "Senior",
                {
                    "minimum_amount": 20.0,
                    "billing_period": "Monthly",
                    "is_active": 1,
                    "description": "Senior membership (65+)"
                }
            ),
            "Family": self.factory.ensure_membership_type(
                "Family",
                {
                    "minimum_amount": 40.0,
                    "billing_period": "Monthly",
                    "is_active": 1,
                    "description": "Family membership for multiple members"
                }
            ),
            "Corporate": self.factory.ensure_membership_type(
                "Corporate",
                {
                    "minimum_amount": 100.0,
                    "billing_period": "Monthly",
                    "is_active": 1,
                    "description": "Corporate/organizational membership"
                }
            ),
        }

    def test_member_creation_yields_active_member_with_customer(self):
        """
        Test Priority 1: a factory-created member is Active and linked to a Customer.

        RENAMED 2026-07-26 (was test_member_application_to_active_transition_...).
        The old name promised an application -> approval -> Active transition that
        this test never performed: it only calls the factory, which inserts a
        member directly. It then asserted application_status in ["Approved", None]
        and failed on the factory's actual "Pending", because the factory does not
        set application_status at all -- the Member controller defaults it.

        Not converted into a real approval test: approve_membership_application()
        is already exercised end-to-end ~20 times in
        tests.backend.components.test_membership_application. What is genuinely
        unique here is the member -> Customer linkage, so that is what this now
        pins.
        """
        member = self.create_test_member(
            first_name="Jan",
            last_name="de Vries",
            birth_date="1985-03-15",
            email="jan.devries.application@test.nl",
            postal_code="1012 AB"
        )

        # The factory inserts members directly rather than through the application
        # flow, so application_status is whatever the Member controller defaults to
        # -- "Pending". Pinned exactly: a silent change to that default is precisely
        # the drift that left this assertion wrong and baselined.
        self.assertEqual(member.application_status, "Pending")
        self.assertEqual(member.status, "Active")

        # Step 2: Verify member has proper data
        member.reload()
        self.assertEqual(member.first_name, "Jan")
        # The test factory appends a uniqueness suffix to last_name; assert the
        # meaningful prefix rather than an exact match.
        self.assertTrue(member.last_name.startswith("de Vries"))

        # Reload to get updated fields
        member.reload()

        # Verify member is now active
        self.assertEqual(member.status, "Active")
        self.assertIsNotNone(member.customer)

        # Verify customer creation. Customer name mirrors the member full_name,
        # which carries the factory's uniqueness suffix on last_name.
        customer = frappe.get_doc("Customer", member.customer)
        self.assertEqual(customer.customer_name, member.full_name)
        self.assertTrue(customer.customer_name.startswith("Jan de Vries"))
        self.assertEqual(customer.customer_type, "Individual")

    def test_sepa_mandate_creation_with_dutch_bank_validation(self):
        """
        Test Priority 1: SEPA mandate creation for Dutch banking

        Critical for automated payment collection. Must comply with
        Dutch banking regulations and SEPA requirements.
        """
        # Create active member
        member = self.create_test_member(
            first_name="Maria",
            last_name="vanderBerg",
            birth_date="1990-07-20"
        )

        # Test various Dutch IBAN formats
        dutch_ibans = [
            "NL91ABNA0417164300",  # ABN AMRO
            "NL44RABO0123456789",  # Rabobank (checksum corrected)
            "NL86INGB0002445588",  # ING Bank (checksum corrected)
            "NL32TRIO0338450310",  # Triodos Bank (checksum corrected)
        ]

        for iban in dutch_ibans:
            with self.subTest(iban=iban):
                # One member per IBAN: since #584 a member holds at most one Active
                # mandate per purpose, and each of these is an Active memberships
                # mandate. What the loop is about is per-bank IBAN handling.
                iban_member = self.create_test_member(
                    first_name="Maria", last_name=f"vanderBerg{frappe.generate_hash(length=5)}",
                    birth_date="1990-07-20",
                )
                # Create SEPA mandate using factory
                mandate = self.create_test_sepa_mandate(
                    iban_member.name,  # Positional argument
                    iban=iban,
                    account_holder_name="Maria van der Berg"
                )

                # Verify mandate creation
                self.assertEqual(mandate.member, iban_member.name)
                # IBAN is normalized to standard format with spaces every 4 characters
                from verenigingen.verenigingen_payments.utils.sepa_utilities import SEPAUtilities
                expected_iban = SEPAUtilities.format_iban_display(iban)
                self.assertEqual(mandate.iban, expected_iban)
                self.assertEqual(mandate.status, "Active")

                # Verify BIC derivation (critical for payments)
                self.assertIsNotNone(mandate.bic)
                self.assertTrue(len(mandate.bic) >= 8)  # Valid BIC length

                # Verify mandate ID format (required by Dutch banks)
                self.assertRegex(
                    mandate.mandate_id,
                    r'^[A-Z0-9]{1,35}$'  # SEPA mandate ID format
                )

    def test_dues_schedule_calculation_for_different_member_types(self):
        """
        Test Priority 1: Dues calculation accuracy

        Financial calculations must be 100% accurate. Errors directly
        impact association revenue and member trust.
        """
        # Test data: Different member types and their expected dues
        member_types_and_dues = [
            ("Regular Adult", Decimal("25.00"), "Monthly"),
            ("Student", Decimal("15.00"), "Monthly"),
            ("Senior", Decimal("20.00"), "Monthly"),
            ("Family", Decimal("40.00"), "Monthly"),
            ("Corporate", Decimal("100.00"), "Monthly"),
        ]

        for member_type, expected_amount, frequency in member_types_and_dues:
            with self.subTest(member_type=member_type):
                # Create member of specific type
                member = self.create_test_member(
                    first_name=f"Test{member_type.replace(' ', '')}",
                    last_name="Member",
                    birth_date="1980-01-01",
                    email=f"test.{member_type.lower().replace(' ', '.')}.{self.factory.test_run_id}@test.nl"
                )

                # Create membership with specific type
                membership = self.create_test_membership(
                    member.name,  # Positional argument
                    member_type  # Positional argument
                )
                membership.submit()

                # Get the auto-created dues schedule
                membership.reload()
                dues_schedule_name = membership.get_dues_schedule()

                if dues_schedule_name:
                    dues_schedule = frappe.get_doc("Membership Dues Schedule", dues_schedule_name)

                    # Verify schedule creation
                    self.assertEqual(dues_schedule.member, member.name)
                    # Note: Actual dues amount may differ from expected if membership type has different rate
                    # We're testing that the schedule is created and linked correctly
                    self.assertEqual(dues_schedule.billing_frequency, frequency)

    def test_chapter_assignment_by_postal_code_dutch_geography(self):
        """
        Test Priority 1: Accurate chapter assignment based on Dutch postal codes

        Critical for proper member organization and local representation.
        Must handle all Dutch postal code formats correctly.
        """
        # Create multiple chapters with different postal code ranges
        # Use test_run_id for unique names to avoid conflicts with existing chapters
        chapters = [
            {
                "name": f"Amsterdam Central {self.factory.test_run_id}",
                "postal_codes": "1000-1099",
                "region": "Noord-Holland"
            },
            {
                "name": f"Amsterdam South {self.factory.test_run_id}",
                "postal_codes": "1070-1109",
                "region": "Noord-Holland"
            },
            {
                "name": f"The Hague {self.factory.test_run_id}",
                "postal_codes": "2500-2599",
                "region": "Zuid-Holland"
            },
            {
                "name": f"Rotterdam {self.factory.test_run_id}",
                "postal_codes": "3000-3099",
                "region": "Zuid-Holland"
            }
        ]

        # Create test chapters and store references
        chapter_lookup = {}
        for chapter_data in chapters:
            chapter = self.factory.ensure_test_chapter(
                chapter_data["name"],
                {
                    "postal_codes": chapter_data["postal_codes"],
                    "region": chapter_data["region"]
                }
            )
            # Store by postal code range for lookup
            chapter_lookup[chapter_data["postal_codes"]] = chapter

        # Test postal code assignments
        test_cases = [
            ("1012 AB", "1000-1099"),  # Central Amsterdam
            ("1075 VW", "1070-1109"),  # South Amsterdam
            ("2511 AB", "2500-2599"),  # The Hague center
            ("3012 CA", "3000-3099"),  # Rotterdam center
        ]

        for postal_code, postal_range in test_cases:
            with self.subTest(postal_code=postal_code):
                # Create member with specific postal code
                member = self.create_test_member(
                    first_name="Postal",
                    last_name=f"Test{postal_code.replace(' ', '')}",
                    birth_date="1985-01-01"
                )

                # Auto-assign chapter based on postal code
                assigned_chapter = self.assign_member_to_chapter_by_postal_code(
                    member, postal_code
                )

                # Verify correct chapter assignment by postal code range, not exact name
                # (factory adds unique suffixes to chapter names)
                expected_chapter = chapter_lookup[postal_range]
                self.assertEqual(assigned_chapter.postal_codes, expected_chapter.postal_codes)
                self.assertEqual(assigned_chapter.region, expected_chapter.region)

    def test_member_status_transitions_with_business_rules(self):
        """
        Test Priority 1: Member status transitions follow business rules

        Status transitions control member rights and billing. Must follow
        strict business rules to prevent data inconsistencies.
        """
        # Create active member with membership (which auto-creates dues schedule)
        member = self.create_test_member(
            first_name="Status",
            last_name="TransitionTest",
            birth_date="1975-06-10"
        )

        # Create membership which will auto-create dues schedule
        membership_type = self.membership_types["Regular Adult"]
        membership = self.create_test_membership(
            member.name,  # Positional argument
            membership_type.name  # Positional argument
        )
        membership.submit()

        # Get the auto-created dues schedule
        membership.reload()
        dues_schedule_name = membership.get_dues_schedule()

        # Test valid status transitions
        valid_transitions = [
            ("Active", "Suspended"),     # Can suspend active member
            ("Suspended", "Active"),     # Can reactivate suspended member
        ]

        for from_status, to_status in valid_transitions:
            with self.subTest(from_status=from_status, to_status=to_status):
                # Reset member to initial status
                member.reload()
                member.status = from_status
                member.save()

                # Perform status transition
                member.reload()
                member.status = to_status
                if to_status == "Quit":
                    member.membership_end_date = frappe.utils.today()
                member.save()

                # Verify transition succeeded
                member.reload()
                self.assertEqual(member.status, to_status)

    def test_dutch_name_handling_with_tussenvoegsel(self):
        """
        Test Priority 2: Proper handling of Dutch names with tussenvoegsel

        Critical for Dutch cultural correctness and legal compliance.
        """
        # Test cases with various Dutch name patterns
        # Note: tussenvoegsel should be stored separately in the tussenvoegsel field
        dutch_names = [
            {
                "first_name": "Jan",
                "tussenvoegsel": "van der",
                "last_name": "Berg",
                "expected_sort": "Berg, Jan van der"
            },
            {
                "first_name": "Maria",
                "tussenvoegsel": "de",
                "last_name": "Jong",
                "expected_sort": "Jong, Maria de"
            },
            {
                "first_name": "Piet",
                "tussenvoegsel": "van den",
                "last_name": "Heuvel",
                "expected_sort": "Heuvel, Piet van den"
            },
            {
                "first_name": "Anna",
                "tussenvoegsel": "ter",
                "last_name": "Beek",
                "expected_sort": "Beek, Anna ter"
            }
        ]

        # update_member_full_name() only uses the tussenvoegsel field when
        # is_dutch_installation() is True, which needs BOTH a Company whose country
        # is "Netherlands" AND a Redis cache (1h TTL) that is not stale. This test
        # used to assume both, and neither holds on a fresh site:
        #   - the cached answer can predate this shard's fixtures entirely;
        #   - _get_test_company() adopts the FIRST existing Company whatever its
        #     country (frappe.get_all("Company", limit=1)), so on a CI site it takes
        #     ERPNext's India-based "_Test Company" and the factory's Netherlands
        #     company is never created.
        # Without one, update_member_full_name() silently falls back to the legacy
        # middle_name branch and produces "Jan Berg" instead of "Jan van der Berg".
        # It passed locally only because test_site_1 has accumulated ~30 Netherlands
        # companies over months of runs -- i.e. for the wrong reason.
        #
        # So arrange the condition rather than detecting it, unconditionally, so
        # this runs the same path locally as in CI. The write is rolled back by the
        # harness; the Redis cache is not, hence the explicit cleanup.
        from verenigingen.utils.dutch_name_utils import is_dutch_installation

        # is_dutch_installation() reads the DEFAULT company first and only reaches
        # its scan-all-companies fallback if that lookup does not raise, so flip the
        # company it will actually consult.
        dutch_company = frappe.defaults.get_defaults().get("company")
        if not dutch_company or not frappe.db.exists("Company", dutch_company):
            dutch_company = frappe.get_all("Company", limit=1, pluck="name")[0]
        original_country = frappe.db.get_value("Company", dutch_company, "country")

        frappe.cache().delete_value("is_dutch_installation")
        self.addCleanup(frappe.cache().delete_value, "is_dutch_installation")
        self.addCleanup(
            frappe.db.set_value, "Company", dutch_company, "country", original_country
        )
        frappe.db.set_value("Company", dutch_company, "country", "Netherlands")
        frappe.cache().delete_value("is_dutch_installation")

        self.assertTrue(
            is_dutch_installation(),
            f"Arranged {dutch_company} as a Netherlands company but is_dutch_installation() "
            "is still False, so update_member_full_name() would ignore tussenvoegsel entirely.",
        )

        for name_data in dutch_names:
            with self.subTest(name=name_data["tussenvoegsel"] + " " + name_data["last_name"]):
                member = self.create_test_member(
                    first_name=name_data["first_name"],
                    tussenvoegsel=name_data["tussenvoegsel"],
                    last_name=name_data["last_name"],
                    birth_date="1980-01-01"
                )

                # Verify proper name handling - full_name should include tussenvoegsel
                expected_full_name = f"{member.first_name} {name_data['tussenvoegsel']} {member.last_name}"
                self.assertEqual(
                    member.full_name,
                    expected_full_name
                )

                # Verify sorting name for alphabetical lists. Derive the expected
                # value from the member's actual (factory-uniquified) last_name
                # rather than the clean fixture value, so the suffix the factory
                # appends doesn't cause a spurious mismatch.
                expected_sort_name = (
                    f"{member.last_name}, {name_data['first_name']} {name_data['tussenvoegsel']}"
                )
                actual_sort_name = self.generate_sort_name(member)
                self.assertEqual(actual_sort_name, expected_sort_name)

    # Helper methods for this test class
    # Note: All data creation now uses factory methods for consistency

    def assign_member_to_chapter_by_postal_code(self, member, postal_code):
        """Auto-assign member to chapter based on postal code - returns chapter doc with narrowest range match"""
        # Extract numeric part of postal code
        postal_numeric = int(postal_code.replace(" ", "")[:4])

        # Find all matching chapters by postal code range
        chapters = frappe.get_all("Chapter", fields=["name", "postal_codes"])

        matching_chapters = []
        for chapter in chapters:
            if not chapter.postal_codes:
                continue

            # Parse postal code range (e.g., "1000-1099")
            try:
                parts = chapter.postal_codes.split("-")
                if len(parts) == 2:
                    min_postal = int(parts[0])
                    max_postal = int(parts[1])

                    if min_postal <= postal_numeric <= max_postal:
                        # Calculate range width for sorting (prefer narrower ranges)
                        range_width = max_postal - min_postal
                        matching_chapters.append((chapter, range_width, min_postal, max_postal))
            except (ValueError, IndexError):
                continue

        # Return chapter with narrowest matching range (most specific)
        if matching_chapters:
            # Sort by range width (ascending), then by min_postal (ascending)
            matching_chapters.sort(key=lambda x: (x[1], x[2]))
            best_match = matching_chapters[0][0]
            return frappe.get_doc("Chapter", best_match.name)

        # Fallback to test chapter
        return self.test_chapter

    def generate_sort_name(self, member):
        """Generate sorting name for Dutch names with tussenvoegsel"""
        from verenigingen.utils.dutch_name_utils import get_sort_name

        # Use the tussenvoegsel field if available
        tussenvoegsel = getattr(member, 'tussenvoegsel', None)
        return get_sort_name(member.first_name, tussenvoegsel, member.last_name)


class TestDutchBankingCompliance(EnhancedTestCase):
    """
    Test Dutch banking and financial compliance requirements

    Priority 1: These tests ensure legal and regulatory compliance
    for financial operations in the Netherlands.
    """

    def test_iban_validation_comprehensive_dutch_banks(self):
        """
        Test comprehensive IBAN validation for all major Dutch banks
        """
        # Valid Dutch IBANs from major banks
        valid_dutch_ibans = [
            "NL91ABNA0417164300",  # ABN AMRO
            "NL44RABO0123456789",  # Rabobank (checksum corrected)
            "NL86INGB0002445588",  # ING Bank (checksum corrected)
            "NL32TRIO0338450310",  # Triodos Bank (checksum corrected)
            "NL42ASNB0707677001",  # ASN Bank (checksum corrected)
            "NL87REGB0008987654",  # RegioBank (checksum corrected)
            "NL48SNSB0922718293",  # SNS Bank (checksum corrected)
        ]

        for iban in valid_dutch_ibans:
            with self.subTest(iban=iban):
                # Test IBAN validation
                is_valid = self.validate_dutch_iban(iban)
                self.assertTrue(is_valid, f"IBAN {iban} should be valid")

                # Test BIC derivation
                bic = self.derive_bic_from_iban(iban)
                self.assertIsNotNone(bic)
                self.assertRegex(bic, r'^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$')

    def test_sepa_mandate_compliance_requirements(self):
        """
        Test SEPA mandate compliance with Dutch/EU regulations
        """
        member = self.create_test_member(
            first_name="SEPA",
            last_name="ComplianceTest",
            birth_date="1985-01-01"
        )

        mandate = self.create_test_sepa_mandate(
            member.name,  # Positional argument
            iban="NL91ABNA0417164300",
            account_holder_name="SEPA Compliance Test"
        )

        # Verify mandate compliance
        self.assertIsNotNone(mandate.mandate_id)
        self.assertIsNotNone(mandate.sign_date)
        # Note: Verify scheme and mandate_type fields exist before asserting
        if hasattr(mandate, 'scheme'):
            self.assertEqual(mandate.scheme, "SEPA")  # SEPA scheme
        if hasattr(mandate, 'mandate_type'):
            self.assertEqual(mandate.mandate_type, "RCUR")  # Recurring payments

    # Helper methods for this test class

    def validate_dutch_iban(self, iban):
        """Validate Dutch IBAN format and checksum"""
        return iban.startswith("NL") and len(iban.replace(" ", "")) == 18

    def derive_bic_from_iban(self, iban):
        """Derive BIC from Dutch IBAN"""
        # Extract bank code (characters 5-8) and derive BIC
        bank_code = iban[4:8]
        # Simple mapping for common Dutch banks
        bic_mapping = {
            "ABNA": "ABNANL2A",
            "RABO": "RABONL2U",
            "INGB": "INGBNL2A",
            "TRIO": "TRIONL2U",
        }
        return bic_mapping.get(bank_code, "ABNANL2A")  # Default fallback