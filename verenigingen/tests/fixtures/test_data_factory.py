"""
Core Test Data Factory for Verenigingen
=======================================

Canonical core factory for creating test data in the Verenigingen association
management system. All other test data factories (EnhancedTestDataFactory,
VereningingenTestCase) delegate entity creation to this class.

Design Philosophy
----------------
- **Fast Defaults**: Uses ignore_permissions=True for speed in tests
- **Deterministic Generation**: Uses configurable seeds for reproducible data
- **Context Manager Support**: Provides automatic cleanup via context managers
- **Scenario Building**: Includes pre-built scenarios for common testing needs

Core Capabilities
----------------
1. **Core Business Objects**: Creates all major DocTypes (Member, Chapter, Volunteer, etc.)
2. **Relationship Management**: Handles complex relationships between DocTypes
3. **Scenario Generation**: Provides complete business scenarios for testing
4. **Edge Case Creation**: Generates edge case data for comprehensive testing
5. **Cleanup Management**: Automatic cleanup of created test data

Usage Patterns
-------------
```python
# Basic usage with context manager (recommended)
with CoreTestDataFactory(cleanup_on_exit=True) as factory:
    member = factory.create_test_member()
    volunteer = factory.create_test_volunteer(member=member)

# Complete scenario creation
scenario = factory.create_complete_test_scenario(member_count=50)

# Edge case testing
edge_cases = factory.create_edge_case_data()

# Performance testing
stress_data = factory.create_stress_test_data(scale="large")
```

Cleanup and Resource Management
------------------------------
- **Dependency Tracking**: Tracks all created records for cleanup
- **Reverse Order Cleanup**: Deletes records in reverse dependency order
- **Context Manager Support**: Automatic cleanup when used as context manager
- **Manual Cleanup**: Explicit cleanup() method for fine-grained control

Note: Uses ``ignore_permissions=True`` for speed. For schema-validated
creation with proper permissions, use ``EnhancedTestDataFactory`` which
delegates core entity creation to this class.
"""

import random
from datetime import datetime
from typing import Dict

import frappe
from frappe.utils import add_days, random_string, today, flt, getdate
from faker import Faker

# Deterministic name pools for reproducible test data (Dutch-flavored)
_FIRST_NAMES = [
    "Adam", "Eva", "Jan", "Maria", "Pieter", "Anna", "Willem", "Sophie",
    "Daan", "Emma", "Lucas", "Lotte", "Sem", "Julia", "Finn", "Saar",
    "Jesse", "Noor", "Milan", "Tess",
]
_LAST_NAMES = [
    "De Vries", "Jansen", "Van Dijk", "Bakker", "Visser", "Smit", "Meijer",
    "De Boer", "Mulder", "De Groot", "Bos", "Vos", "Peters", "Hendriks",
    "Van Leeuwen", "Dekker", "Brouwer", "De Wit", "Dijkstra", "Vermeer",
]


class CoreTestDataFactory:
    """Canonical core factory for creating consistent test data with intelligent defaults.

    All other test data factories (EnhancedTestDataFactory, VereningingenTestCase)
    delegate entity creation to this class.
    """

    def __init__(self, cleanup_on_exit=True, seed=None):
        """Initialize factory with optional seed for reproducible data"""
        self.cleanup_on_exit = cleanup_on_exit
        self.seed = seed or int(datetime.now().timestamp())
        self.created_records = []
        # Use microsecond timestamp for run-unique ID (independent of seed)
        self.test_run_id = f"{int(datetime.now().timestamp() * 1000000) % 100000000}"

        # Deterministic sequence counters (replaces Faker for core entity creation)
        self._sequence_counters: Dict[str, int] = {}

        # Keep Faker for scenario builders / PaymentHistoryTestFactory
        self.fake = Faker()
        if seed:
            Faker.seed(seed)
            random.seed(seed)

        # Cache for frequently used test data
        self._test_chapters = None
        self._test_membership_types = None
        self._test_region = None

    def cleanup(self):
        """Clean up all created test data in reverse dependency order"""
        print(f"🧹 Cleaning up {len(self.created_records)} test records...")

        # Clean up in reverse order to respect dependencies
        for record in reversed(self.created_records):
            try:
                if frappe.db.exists(record["doctype"], record["name"]):
                    doc = frappe.get_doc(record["doctype"], record["name"])
                    doc.delete(ignore_permissions=True, force=True)
            except Exception as e:
                print(f"⚠️  Failed to delete {record['doctype']} {record['name']}: {e}")

        self.created_records = []

    def track_doc(self, doctype: str, name: str):
        """Track a created record for cleanup"""
        self.created_records.append({"doctype": doctype, "name": name})

    # --- Deterministic Generation Helpers ---

    def _get_next_sequence(self, prefix: str) -> int:
        """Get next sequence number for a given prefix (deterministic)."""
        self._sequence_counters[prefix] = self._sequence_counters.get(prefix, 0) + 1
        return self._sequence_counters[prefix]

    def _generate_name(self, name_type: str = "first") -> str:
        """Deterministic name generation cycling through Dutch name pools.

        Last names include the test_run_id suffix AND the per-call sequence number to
        prevent Customer name collisions (Customer uses full_name as primary key). The
        run_id alone is constant within a run, so once the first/last name pools cycle the
        full_name would repeat — the sequence guarantees per-member uniqueness even for
        large batches (e.g. a 50-member team).
        """
        names = _FIRST_NAMES if name_type == "first" else _LAST_NAMES
        seq = self._get_next_sequence(f"name_{name_type}")
        idx = seq - 1
        base_name = names[idx % len(names)]
        if name_type == "last":
            # `frappe.generate_hash` because `test_run_id[-5:]` is a 10^5 space and
            # constant per factory, so two factories built in the same microsecond
            # produce the same last name -- and Customer uses full_name as its primary
            # key, which is what this suffix exists to protect (#552).
            return f"{base_name}-{self.test_run_id[-5:]}{seq}-{frappe.generate_hash(length=4)}"
        return base_name

    def _generate_email(self, purpose: str = "member") -> str:
        """Email generation with run-unique component to prevent collisions."""
        seq = self._get_next_sequence(f"email_{purpose}")
        # Per-call entropy for the same reason as `_generate_name` and `_generate_member_id`:
        # `test_run_id` is clock-derived and constant per factory, so two factories built in
        # the same microsecond emit the same address. `Member.email` is not a UNIQUE column
        # (those are `member_id`, `application_id`, `user`), so this is the lower-stakes of
        # the three -- fixed together because they are the same defect (#552).
        return f"test-{purpose}-{seq:04d}-{self.test_run_id}-{frappe.generate_hash(length=4)}@test.invalid"

    def _generate_member_id(self) -> str:
        """Generate explicit member_id to avoid autoname counter collisions.

        ``member_id`` is a UNIQUE column, and the old format
        ``f"TEST{microsec:06d}{seq:03d}"`` did NOT give uniqueness "across factory
        instances" the way this docstring used to claim. ``VereningingenTestCase.setUp``
        builds a NEW factory per test method, so ``_sequence_counters`` restarts and the
        first member of every test method is ``...001`` -- every one of them drawing from
        the same 10^6 sub-second space. Measured 2026-08-23, two shards, two modules,
        both ending ``001``: ``TEST153429001`` (#524 shard 3) and ``TEST311263001``
        (develop shard 9) -> IntegrityError 1062 (#549).

        Same format as ``EnhancedTestDataFactory._generate_unique_test_member_id``
        (``enhanced_test_factory.py:589``), which was fixed for this first; the fix
        simply never reached this copy. That method has **zero callers**, so the format
        is inherited from it, not proven by it -- the reason to duplicate rather than
        share is purely import cost. Measured 2026-08-23 on test_site_1, delta over an
        already-connected frappe:

            import enhanced_test_factory -> 6.48s, +1392 modules
            import THIS module (control)  -> 0.05s,   +54 modules

        It pulls ``erpnext.tests.utils``, whose body runs ``BootStrapTestData()``, and
        this light factory must not pay for that.

        ``rand_part`` is what actually carries it: ``pid`` is equal across factories in
        one process and ``test_run_id`` is itself clock-derived, so two factories built
        in the same microsecond share both. Only per-call entropy survives that window.
        """
        import os

        seq = self._get_next_sequence("member_id")
        microsec = int(datetime.now().timestamp() * 1000000) % 1000000
        pid_part = os.getpid() % 100000
        rand_part = frappe.generate_hash(length=6)
        return f"TEST{microsec:06d}{seq:03d}{pid_part:05d}{rand_part}"

    def _validate_fields(self, doctype: str, data: dict) -> dict:
        """Validate field names exist in DocType meta. Raises on unknown fields.

        Only called when validate_fields=True is passed to create methods.
        """
        meta = frappe.get_meta(doctype)
        valid_fields = {f.fieldname for f in meta.fields}
        # Standard fields always valid
        valid_fields |= {
            "doctype", "name", "owner", "docstatus", "modified", "modified_by",
            "creation", "idx", "parent", "parentfield", "parenttype",
        }
        unknown = set(data.keys()) - valid_fields
        if unknown:
            raise ValueError(f"Unknown fields for {doctype}: {unknown}")
        return data

    def _create_customer_for_member(self, member):
        """Create ERPNext Customer + Address for a member (opt-in via auto_create_customer)."""
        if not member.customer:
            original_in_test = getattr(frappe.local, "in_test", False)
            frappe.local.in_test = True
            try:
                member.create_customer()
                member.reload()
            finally:
                frappe.local.in_test = original_in_test

        if member.customer:
            self.track_doc("Customer", member.customer)
            self._create_customer_address(member)

    def _create_customer_address(self, member):
        """Create Address linked to the member's Customer if none exists."""
        existing = frappe.get_all(
            "Address",
            fields=["name"],
            filters=[
                ["Dynamic Link", "link_doctype", "=", "Customer"],
                ["Dynamic Link", "link_name", "=", member.customer],
            ],
            limit=1,
        )
        if existing:
            return

        address = frappe.new_doc("Address")
        address.address_title = f"{member.first_name} {member.last_name} - Test Address"
        address.address_line1 = getattr(member, "address_line_1", None) or "Test Street 123"
        address.city = getattr(member, "city", None) or "Amsterdam"
        address.pincode = getattr(member, "postal_code", None) or "1234 AB"
        address.country = "Netherlands"
        address.is_primary_address = 1
        address.append("links", {
            "link_doctype": "Customer",
            "link_name": member.customer,
        })
        address.insert(ignore_permissions=True)
        self.track_doc("Address", address.name)

    # HELPER METHOD: Region Creation
    def create_test_region(self, **kwargs):
        """Create a test region required for chapter creation"""
        seq = self._get_next_sequence("region")
        region_name = f"Test Region {seq} - {self.test_run_id}"

        # region_code is UNIQUE and capped at 5 chars ([A-Z0-9]{2,5}). The old
        # `f"TR{seq}"[:5]` truncated (TR913 and TR9130 both -> "TR913"), so distinct
        # sequences collided; the persistent test site also carries codes from prior
        # runs, and parallel shards race between exists() and insert(). Prefer the
        # sequence code, but fall back to a random 5-char code and catch the TOCTOU
        # DuplicateEntry so a colliding code never aborts the whole test.
        def _random_code():
            return ("R" + frappe.generate_hash(length=4)).upper()[:5]

        region_code = f"TR{seq}"[:5]
        if frappe.db.exists("Region", {"region_code": region_code}):
            region_code = _random_code()

        defaults = {
            "region_name": region_name,
            "country": "Netherlands",
            "is_active": 1,
            "description": f"Test region created for automated testing - {self.test_run_id}",
        }
        defaults.update(kwargs)

        for _attempt in range(20):
            region = frappe.get_doc({"doctype": "Region", "region_code": region_code, **defaults})
            try:
                region.insert(ignore_permissions=True)
                self.track_doc("Region", region.name)
                return region
            except (frappe.exceptions.DuplicateEntryError, frappe.exceptions.ValidationError) as e:
                # region_code uniqueness surfaces as a ValidationError from the Region
                # controller (validate, pre-DB: "Region Code X already exists") and as
                # DuplicateEntryError from the DB unique index (the exists()->insert()
                # race). Only retry a uniqueness collision; re-raise anything else,
                # e.g. the controller's format error ("must be 2-5 ...").
                is_uniqueness = isinstance(e, frappe.exceptions.DuplicateEntryError) or (
                    "already exists" in str(e).lower()
                )
                if not is_uniqueness:
                    raise
                region_code = _random_code()
        raise RuntimeError("create_test_region: could not allocate a unique region_code")

    def get_or_create_test_region(self):
        """Get cached test region or create new one"""
        if self._test_region is None:
            # Try to find existing test region first
            existing_regions = frappe.get_all("Region", 
                filters={"region_code": "TRTX"}, 
                limit=1)
            
            if existing_regions:
                self._test_region = frappe.get_doc("Region", existing_regions[0].name)
            else:
                self._test_region = self.create_test_region()
        return self._test_region

    # CORE METHOD 1: Chapter Creation
    def create_test_chapter(self, *, validate_fields=False, **kwargs):
        """Create a single test chapter with deterministic defaults.

        Args:
            validate_fields: If True, validates kwargs against DocType schema.
            **kwargs: Field overrides for the Chapter document. Note that
                Chapter has no `chapter_name` field — the kwarg is used to
                set `chapter.name` (since autoname='prompt') and is honored
                when supplied; otherwise a seq-based default is generated.
        """
        seq = self._get_next_sequence("chapter")
        default_chapter_name = f"Test Chapter {seq} - {self.test_run_id}"

        test_region = self.get_or_create_test_region()

        # chapter_name is consumed as the doc's primary key (chapter.name),
        # NOT as a doc field. Pop it from kwargs so honor-kwarg semantics work
        # for both the kwarg-supplied and the default case.
        chapter_name = kwargs.pop("chapter_name", default_chapter_name)

        defaults = {
            "status": "Active",
            "region": test_region.name,
            "postal_codes": f"{1000 + (seq % 9000):04d}-{1000 + (seq % 9000) + 99:04d}",
            "introduction": f"Test chapter created for automated testing - {self.test_run_id}",
            "email": self._generate_email("chapter"),
        }
        defaults.update(kwargs)

        if validate_fields:
            self._validate_fields("Chapter", defaults)

        chapter = frappe.get_doc({"doctype": "Chapter", **defaults})
        chapter.name = chapter_name
        chapter.insert(ignore_permissions=True)
        self.track_doc("Chapter", chapter.name)
        return chapter

    def create_test_chapters(self, count: int = 5, **kwargs):
        """Create multiple test chapters"""
        return [self.create_test_chapter(**kwargs) for _ in range(count)]

    # CORE METHOD 2: Member Creation
    def create_test_member(self, chapter=None, *, auto_create_customer=False, validate_fields=False, **kwargs):
        """Create a single test member with deterministic defaults.

        Args:
            chapter: Chapter name or doc to assign member to (via ChapterMembershipManager).
                     Pass None to auto-create a default chapter. Pass False to skip chapter assignment.
            auto_create_customer: If True, also creates ERPNext Customer + Address.
            validate_fields: If True, validates kwargs against DocType schema.
            **kwargs: Field overrides for the Member document.
        """
        if chapter is None:
            chapter = self.get_or_create_test_chapter()

        # Deterministic defaults (replaces Faker)
        seq = self._get_next_sequence("member")
        defaults = {
            "first_name": self._generate_name("first"),
            "last_name": self._generate_name("last"),
            "email": self._generate_email("member"),
            "member_id": self._generate_member_id(),
            "birth_date": add_days(today(), -random.randint(6570, 25550)),  # 18-70 years
            "status": "Active",
            "address_line_1": f"Teststraat {seq}",
            "city": "Amsterdam",
            "postal_code": f"{1000 + (seq % 9000):04d} AB",
            "country": "Netherlands",
        }
        defaults.update(kwargs)

        if validate_fields:
            self._validate_fields("Member", defaults)

        member = frappe.get_doc({"doctype": "Member", **defaults})
        member.insert(ignore_permissions=True)
        # Frappe bug: Workflow action processing during on_update renders a print
        # view via attach_print(), which sets flags.in_print=True on the document.
        # This causes subsequent save() calls to silently no-op (document.py:531).
        member.flags.in_print = False
        member.flags.pop("print_settings", None)
        self.track_doc("Member", member.name)

        # Chapter assignment via service layer (with child-table fallback)
        if chapter:
            chapter_name = chapter.name if hasattr(chapter, "name") else chapter
            try:
                from verenigingen.utils.chapter_membership_manager import ChapterMembershipManager
                ChapterMembershipManager.assign_member_to_chapter(
                    member_id=member.name,
                    chapter_name=chapter_name,
                    reason="Test data creation",
                    assigned_by="Administrator",
                )
                member.reload()
            except Exception:
                # Fallback: direct child table append (for tests without Verenigingen Settings)
                chapter_doc = frappe.get_doc("Chapter", chapter_name)
                chapter_doc.append("members", {
                    "member": member.name,
                    "enabled": 1,
                    "chapter_join_date": today(),
                    "status": "Active",
                })
                chapter_doc.save(ignore_permissions=True)

        # Opt-in customer creation for ERPNext integration tests
        if auto_create_customer:
            self._create_customer_for_member(member)

        return member

    def create_test_members(self, count: int = 10, chapters=None, **kwargs):
        """Create multiple test members distributed across chapters"""
        if chapters is None:
            chapters = self.get_or_create_test_chapters(max(1, count // 5))
        
        members = []
        for i in range(count):
            chapter = chapters[i % len(chapters)]
            member = self.create_test_member(chapter=chapter, **kwargs)
            members.append(member)
        
        return members

    def create_test_memberships(self, count: int = 10, members=None, **kwargs):
        """Create multiple test memberships for bulk testing"""
        if members is None:
            members = self.create_test_members(count=count)
        
        memberships = []
        membership_type = self.get_or_create_test_membership_type()
        
        for i, member in enumerate(members[:count]):
            membership = self.create_test_membership(
                member=member,
                membership_type=membership_type,
                **kwargs
            )
            memberships.append(membership)
        
        return memberships

    # CORE METHOD 3: Membership Creation
    def create_test_membership(self, member=None, membership_type=None, **kwargs):
        """Create a single test membership with intelligent defaults"""
        if member is None:
            member = self.create_test_member()
        if membership_type is None:
            membership_type = self.get_or_create_test_membership_type()
        elif not hasattr(membership_type, "name"):
            # A bare type NAME was passed; ensure it resolves to a real Membership
            # Type (get-or-create) so the insert doesn't fail with "Could not find
            # Membership Type: <name>" on a fresh site.
            membership_type = ensure_membership_type_exists(membership_type)

        defaults = {
            "member": member.name if hasattr(member, 'name') else member,
            "membership_type": membership_type.name if hasattr(membership_type, 'name') else membership_type,
            "status": "Active",
            "start_date": today(),
            "end_date": add_days(today(), 365)
        }
        defaults.update(kwargs)
        
        membership = frappe.get_doc({"doctype": "Membership", **defaults})
        # Keep backdated Active memberships Active: a past start_date computes a
        # past renewal_date, so set_status() would mark the membership Expired and
        # on_submit skips dues schedule creation. Mirror the production
        # backdated-start path (_is_csv_import -> renewal from today). Skip when the
        # caller explicitly wants a non-Active status (e.g. an Expired fixture).
        if defaults.get("status", "Active") == "Active" and getdate(
            defaults.get("start_date", today())
        ) < getdate(today()):
            membership._is_csv_import = True
        # Use proper admin context for test data creation
        original_user = frappe.session.user
        try:
            frappe.set_user("Administrator")
            membership.insert()
        finally:
            frappe.session.user = original_user
        self.track_doc("Membership", membership.name)
        return membership

    def _ensure_test_uom(self, uom_name="Nos"):
        """Ensure a UOM exists on the test site, returning its name."""
        if not frappe.db.exists("UOM", uom_name):
            uom = frappe.get_doc({"doctype": "UOM", "uom_name": uom_name})
            uom.insert(ignore_permissions=True)
            self.track_doc("UOM", uom.name)
        return uom_name

    def _ensure_selling_price_list(self, currency="EUR"):
        """Return a selling Price List name, preferring ERPNext's 'Standard Selling'."""
        if frappe.db.exists("Price List", "Standard Selling"):
            return "Standard Selling"
        existing = frappe.db.get_value("Price List", {"selling": 1}, "name")
        if existing:
            return existing
        price_list = frappe.get_doc({
            "doctype": "Price List",
            "price_list_name": "Standard Selling",
            "selling": 1,
            "currency": currency,
        })
        price_list.insert(ignore_permissions=True)
        self.track_doc("Price List", price_list.name)
        return price_list.name

    def _ensure_test_item(self, item_code="Test Service"):
        """Ensure a sellable, non-stock test Item exists (with mandatory stock_uom)."""
        if not frappe.db.exists("Item", item_code):
            stock_uom = self._ensure_test_uom("Nos")
            item = frappe.get_doc({
                "doctype": "Item",
                "item_code": item_code,
                "item_name": item_code,
                "item_group": "All Item Groups",
                "stock_uom": stock_uom,
                "is_sales_item": 1,
                "is_stock_item": 0,
                "include_item_in_manufacturing": 0,
                "standard_rate": 100.0,
                "description": "Test item created by Core Test Factory",
            })
            item.insert(ignore_permissions=True)
            self.track_doc("Item", item.name)
        return item_code

    def create_test_sales_invoice(self, customer=None, **kwargs):
        """Create a Sales Invoice for testing.

        Backward-compatibility bridge restored after factory consolidation.

        Args:
            customer: Customer name, Member name, or doc. If a Member is given,
                      its linked Customer is used (created if missing).
            company: Company to invoice under (default: first Company).
            items: Optional list of item dicts; otherwise one default line is
                   added using the "Test Service" item.
            is_membership_invoice / membership: mapped to custom_* fields.
            posting_date / due_date / status / grand_total: passthrough.
        """
        # Resolve customer (accept Member name/doc or Customer name/doc)
        cust_name = customer.name if hasattr(customer, "name") else customer
        if cust_name and frappe.db.exists("Member", cust_name):
            member = frappe.get_doc("Member", cust_name)
            if not member.customer:
                self._create_customer_for_member(member)
            cust_name = member.customer
        if not cust_name or not frappe.db.exists("Customer", cust_name):
            raise ValueError(f"Invalid customer reference for sales invoice: {customer}")

        company = kwargs.get("company") or frappe.get_list("Company", limit=1)[0].name
        company_currency = frappe.db.get_value("Company", company, "default_currency") or "EUR"

        debit_to = frappe.db.get_value("Company", company, "default_receivable_account") or \
            frappe.db.get_value(
                "Account",
                {"account_type": "Receivable", "company": company, "is_group": 0},
                "name",
            )
        # ERPNext's standard chart of accounts leaves account_type EMPTY on income
        # leaves; they carry root_type = "Income" instead (#442).
        income_account = frappe.db.get_value(
            "Account",
            {"root_type": "Income", "company": company, "is_group": 0},
            "name",
        )
        cost_center = frappe.db.get_value("Company", company, "cost_center") or \
            frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")

        invoice_data = {
            "doctype": "Sales Invoice",
            "customer": cust_name,
            "company": company,
            "currency": company_currency,
            "conversion_rate": 1.0,
            "posting_date": kwargs.get("posting_date", today()),
            "due_date": kwargs.get("due_date", add_days(today(), 30)),
            # Selling price list fields are mandatory on Sales Invoice in v16.
            "selling_price_list": self._ensure_selling_price_list(company_currency),
            "price_list_currency": company_currency,
            "plc_conversion_rate": 1.0,
            "ignore_pricing_rule": 1,
            "custom_is_membership_invoice": kwargs.get("is_membership_invoice", 0),
            "custom_membership": kwargs.get("membership"),
        }
        if debit_to:
            invoice_data["debit_to"] = debit_to

        if "items" in kwargs and kwargs["items"]:
            items = kwargs["items"]
            for item in items:
                code = item.get("item_code")
                if code:
                    self._ensure_test_item(code)
                item.setdefault("qty", 1)
                if income_account:
                    item.setdefault("income_account", income_account)
                if cost_center:
                    item.setdefault("cost_center", cost_center)
            invoice_data["items"] = items
        else:
            self._ensure_test_item("Test Service")
            rate = flt(kwargs.get("grand_total", 100.0))
            line = {
                "item_code": "Test Service",
                "qty": 1,
                "rate": rate,
                "uom": "Nos",
            }
            if income_account:
                line["income_account"] = income_account
            if cost_center:
                line["cost_center"] = cost_center
            invoice_data["items"] = [line]

        invoice = frappe.get_doc(invoice_data)
        invoice.insert(ignore_permissions=True)
        self.track_doc("Sales Invoice", invoice.name)

        if kwargs.get("submit") and kwargs.get("status") != "Draft":
            invoice.submit()
        return invoice

    # CORE METHOD 4: Membership Type Creation
    def create_test_membership_type(self, **kwargs):
        """Create membership type with intelligent defaults"""
        # Use existing template if not provided. If none exists yet, leave the
        # field UNSET: MembershipType.after_insert auto-creates a dues schedule
        # template for the new type (and we align its rate below).
        #
        # The old code fell back to a literal "Template-Annual", which does not
        # exist on a fresh CI site -> insert() raised LinkValidationError and the
        # caller's setUp crashed. It only triggered order-dependently (when no
        # other test had created a template yet), so it surfaced as a flaky
        # shard failure rather than a consistent one.
        if 'dues_schedule_template' not in kwargs:
            existing_template = frappe.db.get_value(
                "Membership Dues Schedule",
                {"is_template": 1},
                "name",
                order_by="creation desc"
            )
            if existing_template:
                kwargs['dues_schedule_template'] = existing_template

        # Get a role profile for the membership type (required field)
        role_profile = kwargs.get("role_profile")
        if not role_profile:
            role_profile = frappe.db.get_value("Role Profile", {"name": "Verenigingen Staff"}, "name")
        if not role_profile:
            role_profile = frappe.db.get_value("Role Profile", {}, "name")

        seq = self._get_next_sequence("membership_type")
        amounts = [25, 50, 75, 100, 150, 200]
        defaults = {
            "membership_type_name": f"Test Type {seq} - {self.test_run_id}",
            "minimum_amount": flt(amounts[(seq - 1) % len(amounts)]),
            "is_active": 1,
            "billing_period": "Annual",
            "role_profile": role_profile,
        }
        defaults.update(kwargs)

        membership_type = frappe.get_doc({"doctype": "Membership Type", **defaults})
        membership_type.insert(ignore_permissions=True)
        self.track_doc("Membership Type", membership_type.name)

        # When we did not supply a template, MembershipType.after_insert created
        # one at a default rate that may sit below this type's minimum_amount.
        # That makes a later membership submit fail with "Template dues rate (...)
        # cannot be less than membership type minimum (...)". Align the auto-created
        # template's rate with the type (mirrors ensure_membership_type_exists()).
        if not defaults.get("dues_schedule_template"):
            template = frappe.db.get_value(
                "Membership Dues Schedule",
                {"is_template": 1, "membership_type": membership_type.name},
                "name",
            )
            if template:
                amount = defaults["minimum_amount"]
                template_doc = frappe.get_doc("Membership Dues Schedule", template)
                template_doc.suggested_amount = amount
                template_doc.dues_rate = amount
                template_doc.minimum_amount = amount * 0.5
                template_doc.save(ignore_permissions=True)
                if membership_type.dues_schedule_template != template:
                    membership_type.dues_schedule_template = template
                    membership_type.save(ignore_permissions=True)
        return membership_type

    # CORE METHOD 5: Volunteer Creation
    def create_test_volunteer(self, *, member=None, validate_fields=False, **kwargs):
        """Create test volunteer with deterministic defaults.

        Args:
            member: Member doc or name. Auto-created if None.
            validate_fields: If True, validates kwargs against DocType schema.
            **kwargs: Field overrides for the Volunteer document.
        """
        if member is None:
            member = self.create_test_member()

        member_name = member.name if hasattr(member, "name") else member
        if hasattr(member, "first_name"):
            vol_name = f"{member.first_name} {member.last_name}"
        else:
            vol_name = f"{self._generate_name('first')} {self._generate_name('last')}"

        defaults = {
            "member": member_name,
            "volunteer_name": vol_name,
            "email": self._generate_email("volunteer"),
            "status": "Active",
            "start_date": today(),
        }
        defaults.update(kwargs)

        if validate_fields:
            self._validate_fields("Volunteer", defaults)

        volunteer = frappe.get_doc({"doctype": "Volunteer", **defaults})
        volunteer.insert(ignore_permissions=True)
        self.track_doc("Volunteer", volunteer.name)
        return volunteer

    # CORE METHOD: Team Creation with Team Role Support
    def create_test_team(self, **kwargs):
        """Create test team with deterministic defaults"""
        seq = self._get_next_sequence("team")
        team_name = f"Test Team {seq} - {self.test_run_id}"
        
        defaults = {
            "team_name": team_name,
            "status": "Active", 
            "team_type": "Project Team",
            "start_date": today(),
            "description": f"Test team created for automated testing - {self.test_run_id}"
        }
        defaults.update(kwargs)
        
        team = frappe.get_doc({"doctype": "Team", **defaults})
        team.insert(ignore_permissions=True)
        self.track_doc("Team", team.name)
        return team

    def get_or_create_team_role(self, role_name="Team Member"):
        """Get existing team role or ensure fixture roles exist"""
        # Check if role exists
        if frappe.db.exists("Team Role", role_name):
            return frappe.get_doc("Team Role", role_name)
        
        # If not exists, try installing fixtures
        try:
            from frappe.core.doctype.data_import.data_import import import_doc
            # This will ensure fixtures are loaded
            frappe.get_doc("Data Import", {}).import_doc()
        except:
            pass
            
        # Try again after fixture loading
        if frappe.db.exists("Team Role", role_name):
            return frappe.get_doc("Team Role", role_name)
        
        # Fallback: create the role if it still doesn't exist
        role_data = {
            "Team Leader": {"permissions_level": "Leader", "is_team_leader": 1, "is_unique": 1},
            "Team Member": {"permissions_level": "Basic", "is_team_leader": 0, "is_unique": 0},
            "Coordinator": {"permissions_level": "Coordinator", "is_team_leader": 0, "is_unique": 0},
            "Secretary": {"permissions_level": "Coordinator", "is_team_leader": 0, "is_unique": 1},
            "Treasurer": {"permissions_level": "Coordinator", "is_team_leader": 0, "is_unique": 1}
        }.get(role_name, {"permissions_level": "Basic", "is_team_leader": 0, "is_unique": 0})
        
        team_role = frappe.get_doc({
            "doctype": "Team Role",
            "role_name": role_name,
            "description": f"Test {role_name} role",
            "is_active": 1,
            **role_data
        })
        team_role.insert(ignore_permissions=True)
        self.track_doc("Team Role", team_role.name)
        return team_role

    def create_test_team_member(self, team=None, volunteer=None, team_role_name="Team Member", **kwargs):
        """Create team member with new team_role field structure"""
        if team is None:
            team = self.create_test_team()
        if volunteer is None:
            volunteer = self.create_test_volunteer()
        
        # Get or create the team role
        team_role = self.get_or_create_team_role(team_role_name)
        
        # Add team member to team
        team_doc = frappe.get_doc("Team", team.name if hasattr(team, 'name') else team)
        
        member_defaults = {
            "volunteer": volunteer.name if hasattr(volunteer, 'name') else volunteer,
            "team_role": team_role.name,  # Use new team_role field
            "from_date": today(),
            "is_active": 1,
            "status": "Active"
        }
        member_defaults.update(kwargs)
        
        team_doc.append("team_members", member_defaults)
        team_doc.save(ignore_permissions=True)
        
        return team_doc.team_members[-1]  # Return the added team member record

    # CORE METHOD 6: SEPA Mandate Creation
    def create_test_sepa_mandate(self, member=None, **kwargs):
        """Create SEPA mandate with test bank account"""
        if member is None:
            member = self.create_test_member()
        
        test_iban = self.generate_test_iban()
        # Get member name for account holder
        member_name = member.name if hasattr(member, 'name') else member
        member_doc = frappe.get_doc("Member", member_name) if isinstance(member_name, str) else member
        account_holder_name = f"{member_doc.first_name} {member_doc.last_name}"
        
        defaults = {
            "member": member_name,
            "iban": test_iban,
            "bic": self.derive_bic_from_test_iban(test_iban),
            "status": "Active",
            "mandate_type": "RCUR",  # Required field - use valid option
            "scheme": "SEPA",  # Required field
            "account_holder_name": account_holder_name,  # Required field
            "sign_date": today(),  # Required field (renamed from mandate_date)
            "mandate_id": f"TEST-{random_string(8)}"  # Required field
        }
        defaults.update(kwargs)
        
        mandate = frappe.get_doc({"doctype": "SEPA Mandate", **defaults})
        mandate.insert(ignore_permissions=True)
        self.track_doc("SEPA Mandate", mandate.name)
        return mandate

    # CORE METHOD 7: Complete Business Scenario
    def create_complete_test_scenario(self, member_count: int = 10):
        """Create complete test scenario with all related documents"""
        print(f"🏗️  Creating complete test scenario with {member_count} members...")
        
        # Create supporting data
        chapters = self.create_test_chapters(count=max(1, member_count // 5))
        membership_types = [self.create_test_membership_type() for _ in range(3)]
        
        # Create members and related data
        members = self.create_test_members(count=member_count, chapters=chapters)
        memberships = [self.create_test_membership(member=member, membership_type=random.choice(membership_types)) 
                      for member in members]
        
        # Create volunteers (30% of members)
        volunteers = [self.create_test_volunteer(member=member) 
                     for member in random.sample(members, max(1, member_count // 3))]
        
        # Create SEPA mandates (60% of members)
        mandates = [self.create_test_sepa_mandate(member=member)
                   for member in random.sample(members, max(1, (member_count * 6) // 10))]

        return {
            "chapters": chapters,
            "membership_types": membership_types,
            "members": members,
            "memberships": memberships,
            "volunteers": volunteers,
            "mandates": mandates,
        }

    # UTILITY METHODS (Enhanced)
    def generate_test_iban(self, bank_code: str = None) -> str:
        """Generate valid test IBAN with deterministic sequential generation.

        Delegates to iban_validator.generate_test_iban() with inline MOD-97 fallback.
        """
        bank_codes = ["TEST", "MOCK", "DEMO"]
        if bank_code is None:
            bank_code = bank_codes[self._get_next_sequence("bank") % len(bank_codes)]

        account_number = f"{self._get_next_sequence('account'):010d}"

        try:
            from verenigingen.utils.validation.iban_validator import generate_test_iban
            return generate_test_iban(bank_code, account_number)
        except ImportError:
            # Inline MOD-97 fallback if iban_validator not available
            temp_iban = f"NL00{bank_code}{account_number}"
            numeric_string = ""
            for char in temp_iban[4:] + "NL00":
                if char.isdigit():
                    numeric_string += char
                else:
                    numeric_string += str(ord(char) - ord("A") + 10)
            checksum = 98 - (int(numeric_string) % 97)
            return f"NL{checksum:02d}{bank_code}{account_number}"

    def derive_bic_from_test_iban(self, iban: str) -> str:
        """Derive BIC from test IBAN"""
        bank_code = iban[4:8]
        return f"{bank_code}NL2A"

    def get_or_create_test_chapter(self):
        """Get cached test chapter or create new one"""
        if self._test_chapters is None:
            self._test_chapters = [self.create_test_chapter()]
        return self._test_chapters[0]

    def get_or_create_test_chapters(self, count: int = 3):
        """Get cached test chapters or create new ones"""
        if self._test_chapters is None or len(self._test_chapters) < count:
            self._test_chapters = self.create_test_chapters(count=count)
        return self._test_chapters[:count]

    def get_or_create_test_membership_type(self):
        """Get cached test membership type or create new one"""
        if self._test_membership_types is None:
            self._test_membership_types = [self.create_test_membership_type()]
        return self._test_membership_types[0]


    # CONTEXT MANAGER SUPPORT
    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup"""
        if self.cleanup_on_exit:
            self.cleanup()

    # SCENARIO BUILDERS (Restored from Phase 4 removal)
    def create_team_with_multiple_roles(self, member_count=5):
        """Create team with various roles for comprehensive testing"""
        team = self.create_test_team()
        volunteers = [self.create_test_volunteer() for _ in range(member_count)]
        
        role_assignments = [
            "Team Leader",    # Unique role
            "Secretary",      # Unique role  
            "Treasurer",      # Unique role
            "Coordinator",    # Non-unique role
            "Team Member"     # Non-unique role
        ]
        
        team_members = []
        for i, volunteer in enumerate(volunteers):
            role_name = role_assignments[i % len(role_assignments)]
            # Avoid duplicate unique roles
            if role_name in ["Team Leader", "Secretary", "Treasurer"] and i >= 3:
                role_name = "Team Member"  # Fallback to non-unique role
                
            member = self.create_test_team_member(
                team=team,
                volunteer=volunteer, 
                team_role_name=role_name
            )
            team_members.append(member)
            
        return {
            "team": team,
            "volunteers": volunteers,
            "team_members": team_members,
            "roles_used": list(set(role_assignments[:member_count]))
        }

    def create_edge_case_data(self):
        """Create comprehensive edge case scenario data for testing"""
        print("🔧 Creating edge case test scenario...")
        
        # Create members with edge case characteristics
        edge_members = []
        
        # Member with very old birth date
        old_member = self.create_test_member(
            first_name="VeryOld",
            last_name="EdgeCase",
            email="old.edge@example.com",
            birth_date="1920-01-01"
        )
        edge_members.append(old_member)
        
        # Member with recent birth date (just turned 18)
        from frappe.utils import add_years
        young_member = self.create_test_member(
            first_name="JustEighteen",
            last_name="EdgeCase", 
            email="young.edge@example.com",
            birth_date=add_years(today(), -18)
        )
        edge_members.append(young_member)
        
        # Member with special characters in name
        special_member = self.create_test_member(
            first_name="José-María",
            last_name="van der Berg-O'Connor",
            email="special.chars@example.com"
        )
        edge_members.append(special_member)
        
        # Create edge case memberships
        edge_memberships = []
        
        # Zero-rate membership (scholarship)
        zero_type = self.create_test_membership_type(
            membership_type_name="Zero Rate Scholarship",
            amount=0.00,
            billing_frequency="Annual"
        )
        
        zero_membership = self.create_test_membership(
            member=edge_members[0],
            membership_type=zero_type
        )
        edge_memberships.append(zero_membership)
        
        # High-rate membership
        premium_type = self.create_test_membership_type(
            membership_type_name="Premium Edge Case",
            amount=9999.99,
            billing_frequency="Annual"
        )
        
        premium_membership = self.create_test_membership(
            member=edge_members[1],
            membership_type=premium_type
        )
        edge_memberships.append(premium_membership)
        
        return {
            "members": edge_members,
            "memberships": edge_memberships,
            "membership_types": [zero_type, premium_type],
            "scenario_type": "edge_cases"
        }
    
    def create_billing_conflict_scenario(self):
        """Create billing frequency conflict scenario for testing validation"""
        print("💰 Creating billing conflict test scenario...")
        
        # Create member and membership
        conflict_member = self.create_test_member(
            first_name="Conflict",
            last_name="TestMember",
            email="conflict.test@example.com"
        )
        
        membership = self.create_test_membership(member=conflict_member)
        
        # Create conflicting dues schedules (using basic creation method)
        monthly_schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"Monthly-Conflict-{self.test_run_id}",
            "member": conflict_member.name,
            "dues_rate": 25.00,
            "billing_frequency": "Monthly",
            "status": "Active",
            "is_template": 0
        })
        monthly_schedule.insert(ignore_permissions=True)
        self.track_doc("Membership Dues Schedule", monthly_schedule.name)
        
        annual_schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"Annual-Conflict-{self.test_run_id}",
            "member": conflict_member.name,
            "dues_rate": 250.00,
            "billing_frequency": "Annual",
            "status": "Active",
            "is_template": 0
        })
        annual_schedule.insert(ignore_permissions=True)
        self.track_doc("Membership Dues Schedule", annual_schedule.name)
        
        return {
            "member": conflict_member,
            "membership": membership,
            "monthly_schedule": monthly_schedule,
            "annual_schedule": annual_schedule,
            "conflict_type": "billing_frequency",
            "expected_validation_error": True
        }
    
    def create_stress_test_data(self, scale="medium"):
        """Create stress test data for performance validation"""
        scales = {
            "small": {"members": 50, "chapters": 5},
            "medium": {"members": 200, "chapters": 10},
            "large": {"members": 1000, "chapters": 25}
        }
        
        config = scales.get(scale, scales["medium"])
        print(f"🏋️ Creating {scale} stress test scenario ({config['members']} members)...")
        
        # Create chapters
        chapters = self.create_test_chapters(count=config["chapters"])
        
        # Create members distributed across chapters
        members = []
        for i in range(config["members"]):
            chapter = chapters[i % len(chapters)]
            member = self.create_test_member(
                first_name=f"Stress{i:04d}",
                last_name="TestMember",
                email=f"stress{i:04d}@example.com",
                chapter=chapter
            )
            members.append(member)
        
        # Create memberships for all members
        memberships = []
        membership_types = [self.create_test_membership_type() for _ in range(3)]
        
        for i, member in enumerate(members):
            membership_type = membership_types[i % len(membership_types)]
            membership = self.create_test_membership(
                member=member,
                membership_type=membership_type
            )
            memberships.append(membership)
        
        # Create volunteers (30% of members)
        volunteer_count = config["members"] // 3
        volunteers = []
        for i in range(volunteer_count):
            volunteer = self.create_test_volunteer(member=members[i])
            volunteers.append(volunteer)
        
        return {
            "chapters": chapters,
            "members": members,
            "memberships": memberships,
            "membership_types": membership_types,
            "volunteers": volunteers,
            "scale": scale,
            "stats": {
                "member_count": len(members),
                "chapter_count": len(chapters),
                "volunteer_count": len(volunteers)
            }
        }
    
    def create_test_members_with_status_distribution(self, total_count=20, status_ratios=None):
        """Create members with realistic status distribution for testing"""
        if status_ratios is None:
            status_ratios = {
                "Active": 0.70,      # 70% active
                "Suspended": 0.15,   # 15% suspended
                "Quit": 0.10,  # 10% terminated
                "Pending": 0.05      # 5% pending
            }
        
        members_by_status = {}
        
        for status, ratio in status_ratios.items():
            count = int(total_count * ratio)
            if count == 0 and ratio > 0:
                count = 1  # Ensure at least one member per status
            
            status_members = []
            for i in range(count):
                member = self.create_test_member(
                    first_name=f"{status}{i:02d}",
                    last_name="DistributionTest",
                    email=f"{status.lower()}{i:02d}@example.com",
                    status=status
                )
                status_members.append(member)
            
            members_by_status[status] = status_members
        
        return {
            "members_by_status": members_by_status,
            "total_count": sum(len(members) for members in members_by_status.values()),
            "status_distribution": status_ratios,
            "scenario_type": "status_distribution"
        }
    
    def create_test_members_with_volunteer_ratio(self, member_count=30, volunteer_ratio=0.4):
        """Create members with specified volunteer participation ratio"""
        # Create members
        members = self.create_test_members(count=member_count)
        
        # Calculate volunteer count
        volunteer_count = int(member_count * volunteer_ratio)
        
        # Create volunteers from subset of members
        volunteers = []
        for i in range(volunteer_count):
            volunteer = self.create_test_volunteer(member=members[i])
            volunteers.append(volunteer)
        
        return {
            "members": members,
            "volunteers": volunteers,
            "non_volunteers": members[volunteer_count:],
            "volunteer_ratio": volunteer_count / member_count,
            "stats": {
                "total_members": len(members),
                "volunteer_count": len(volunteers),
                "non_volunteer_count": len(members) - len(volunteers)
            }
        }


def _ensure_member_role_profile():
    """Return a Role Profile name usable for a test Membership Type (reqd field).

    Prefers the app's standard profiles; falls back to any existing profile;
    creates a minimal one only if the site has none (fresh CI site).
    """
    for candidate in ("Verenigingen Member", "Verenigingen Staff"):
        existing = frappe.db.get_value("Role Profile", {"name": candidate}, "name")
        if existing:
            return existing
    existing = frappe.db.get_value("Role Profile", {}, "name")
    if existing:
        return existing
    profile = frappe.new_doc("Role Profile")
    profile.role_profile = "Test Member Profile"
    if frappe.db.exists("Role", "Verenigingen Member"):
        profile.append("roles", {"role": "Verenigingen Member"})
    profile.insert(ignore_permissions=True)
    return profile.name


# A €2/day type owned EXCLUSIVELY by the payment test modules.
#
# Those tests used the name "Daglid", which is also referenced by
# create_test_membership(membership_type="Daglid") elsewhere. That made it a shared
# master, and ensure_membership_type_exists() returns an existing row WITHOUT
# correcting its amount while defaulting to 100.0 -- so whichever caller touched the
# name first fixed its amount for the whole run. When a caller that passes no amount
# won the race, "Daglid" was created at €100 and the payment tests' €2 dues schedules
# died on `Dues rate (€2.00) cannot be less than minimum amount (€100.00)`.
# Order-dependent, so it only ever surfaced in CI (issue #248).
#
# The fix is to stop sharing rather than to repair the shared row mid-run: a name no
# other test references can never be created with the wrong amount in the first place.
# Keep it stable (not tokenised) so it behaves like the bootstrap master it is and
# does not accumulate a row per run.
PAYMENT_TEST_DAILY_TYPE = "TEST Payment Daily 2EUR"
PAYMENT_TEST_DAILY_AMOUNT = 2.0


def ensure_payment_test_daily_type():
    """Get-or-create the payment tests' own €2 membership type; return its name.

    Verifies the amount instead of trusting it. ensure_membership_type_exists()
    returns an existing row untouched, so if anything ever creates this name via the
    no-amount path -- create_test_membership() does exactly that, at the 100.0 default
    -- the type would silently be wrong and every dues schedule built on it would fail
    with an error naming the schedule rather than the type. Since no other test
    references this name, a mismatch means real contamination, and failing here points
    straight at it.
    """
    existed = frappe.db.exists("Membership Type", PAYMENT_TEST_DAILY_TYPE)
    name = ensure_membership_type_exists(PAYMENT_TEST_DAILY_TYPE, amount=PAYMENT_TEST_DAILY_AMOUNT)

    if not existed:
        # COMMIT, or this master does not survive to the tests that need it.
        #
        # Callers seed it from setUpClass. That row survives into the FIRST test method
        # and is destroyed by the FIRST tearDown -- the per-test rollback is this app's
        # own (enhanced_test_factory.py tearDown, and utils/base.py for
        # VereningingenTestCase), not frappe's, which only registers a class-level
        # cleanup. Every method after the first therefore starts with the type absent,
        # and create_test_membership() re-creates it through
        # ensure_membership_type_exists() WITHOUT an amount -- i.e. at the 100.0
        # default. TRACED with a stack dump at the creation point: two creations per
        # run, `amount=2.0` from setUpClass and `amount=100.0` from
        # test_data_factory.py:439 inside a test body.
        #
        # That is issue #248. It bit test_payment_history_sync_with_auto_generated_invoice
        # because unittest runs methods alphabetically and that one sorts last, so by
        # the time it ran the setUpClass row was long gone and the €2 schedule was built
        # against a freshly re-created €100 type:
        # `Dues rate (€2.00) cannot be less than minimum amount (€100.00)`. Whether the
        # bad row then got committed only decides how long the damage outlives the run.
        #
        # Committing makes it a real bootstrap master, exactly as the name being stable
        # and unshared already implies -- the same thing test_data_factory does for the
        # test Region. There is nothing to leak: the row is reused by every subsequent
        # run rather than accumulating. Seed it from setUpClass/setUp, never from a test
        # body, or this commit will also persist whatever that test had already written.
        frappe.db.commit()

    actual = frappe.db.get_value("Membership Type", name, "minimum_amount")
    if actual is None or flt(actual, 2) != flt(PAYMENT_TEST_DAILY_AMOUNT, 2):
        found = "missing" if actual is None else f"minimum_amount={actual}"
        raise AssertionError(
            f"{name!r} is {found} but the payment tests require "
            f"{PAYMENT_TEST_DAILY_AMOUNT}. Something created it via a path that does not "
            f"specify an amount (create_test_membership defaults to 100.0). The type and "
            f"its template link to each other, so the Desk UI cannot delete either one "
            f"first -- clear it from `bench --site <site> console` with:\n"
            f'    frappe.db.set_value("Membership Type", {name!r}, "dues_schedule_template", None)\n'
            f'    for t in frappe.get_all("Membership Dues Schedule", '
            f'filters={{"membership_type": {name!r}}}, pluck="name"):\n'
            f'        frappe.delete_doc("Membership Dues Schedule", t, force=True)\n'
            f'    frappe.delete_doc("Membership Type", {name!r}, force=True)\n'
            f"    frappe.db.commit()"
        )
    return name


def ensure_membership_type_exists(name, *, amount=100.0):
    """Get-or-create a Membership Type with the EXACT given name; return the name.

    Many tests pass a membership_type_name (e.g. "Regular Member", "Daglid",
    "Standard Member", "Monthly Membership") expecting it to already exist. On a
    fresh CI site it doesn't, so the Membership insert fails with "Could not find
    Membership Type: <name>" and the test's setUp crashes. Create a minimal active
    type on first reference. The name is stable, so later tests in the run reuse
    it (get-or-create -> no collision, no per-test cleanup; it behaves like a
    bootstrap master, the same way the default Team Roles do).

    Callers that need a type with *specific* properties (amount, billing period,
    contribution mode) should still build it explicitly via
    create_test_membership_type(); this helper only guarantees a referenced name
    resolves to a valid, active Membership Type.
    """
    if not name:
        raise ValueError("ensure_membership_type_exists() requires a non-empty name")
    if frappe.db.exists("Membership Type", name):
        return name

    membership_type = frappe.new_doc("Membership Type")
    membership_type.membership_type_name = name
    membership_type.is_active = 1
    membership_type.contribution_mode = "Fixed Amount"
    membership_type.minimum_amount = amount
    membership_type.billing_period = "Annual"
    membership_type.role_profile = _ensure_member_role_profile()

    # Get-or-create race (TOCTOU): under run-parallel-tests, multiple worker
    # processes share one site DB, so two tests can both pass the exists() check
    # above and both reach this insert() for the same stable-named shared master.
    # membership_type_name is the autoname/primary key, so only one insert can
    # win; the loser raises DuplicateEntryError. Wrap it in a savepoint so the
    # failed insert rolls back cleanly (no poisoned surrounding transaction),
    # then reuse the row the winner committed. Because only the winner gets past
    # this point, the template alignment below has a single writer and cannot
    # race.
    sp = "ensure_membership_type"
    frappe.db.savepoint(sp)
    try:
        membership_type.insert(ignore_permissions=True)
    except (frappe.exceptions.DuplicateEntryError, frappe.exceptions.UniqueValidationError):
        frappe.db.rollback(save_point=sp)
        return name
    frappe.db.release_savepoint(sp)

    # Membership Type.after_insert auto-creates a dues schedule template with a
    # default €15 rate. That is below our minimum_amount, so create_from_template
    # (run on membership submit) fails with "Template dues rate (...) cannot be
    # less than membership type minimum (...)" and no schedule is created — the
    # caller then sees "No schedule was created with membership". Align the
    # template's rate with the type so a schedule can actually be created (mirrors
    # EnhancedTestCase.create_test_membership_type).
    template = frappe.db.get_value(
        "Membership Dues Schedule",
        {"is_template": 1, "membership_type": membership_type.name},
        "name",
    )
    if template:
        template_doc = frappe.get_doc("Membership Dues Schedule", template)
        template_doc.suggested_amount = amount
        template_doc.dues_rate = amount
        template_doc.minimum_amount = amount * 0.5
        template_doc.save(ignore_permissions=True)
        if membership_type.dues_schedule_template != template:
            membership_type.dues_schedule_template = template
            membership_type.save(ignore_permissions=True)
    return membership_type.name


# CONVENIENCE FUNCTIONS
def create_test_data_set(data_type: str = "minimal", **kwargs):
    """Create standardized test data sets"""
    with CoreTestDataFactory(cleanup_on_exit=False) as factory:
        if data_type == "minimal":
            return {
                "chapter": factory.create_test_chapter(),
                "member": factory.create_test_member(),
                "membership_type": factory.create_test_membership_type()
            }
        elif data_type == "comprehensive":
            return factory.create_complete_test_scenario(member_count=kwargs.get('member_count', 20))
        elif data_type == "performance":
            return factory.create_complete_test_scenario(member_count=kwargs.get('member_count', 100))
        else:
            raise ValueError(f"Unknown data_type: {data_type}")


# BACKWARD COMPATIBILITY ALIASES
TestDataFactory = CoreTestDataFactory
StreamlinedTestDataFactory = CoreTestDataFactory


class TestDataContext:
    """No-op stub for backward compatibility.

    WARNING: This stub ignores all constructor arguments and __enter__ returns
    self (not a dict). Callers like test_performance_edge_cases.py that do
    ``with TestDataContext("performance", member_count=1000) as data:``
    will get a TestDataContext instance, not test data. Those tests need
    rewriting to use CoreTestDataFactory directly.
    """

    def __init__(self, *args, **kwargs):
        self.created_records = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for doctype, name in reversed(self.created_records):
            try:
                import frappe

                if frappe.db.exists(doctype, name):
                    frappe.delete_doc(doctype, name, force=True)
            except Exception:
                pass
        return False

# Additional convenience methods for Team Role testing
def create_test_team_scenario(member_count=5, cleanup_on_exit=True):
    """Create complete team scenario with various roles"""
    with CoreTestDataFactory(cleanup_on_exit=cleanup_on_exit) as factory:
        return factory.create_team_with_multiple_roles(member_count=member_count)

def get_available_team_roles():
    """Get list of available team roles for testing"""
    return ["Team Leader", "Team Member", "Coordinator", "Secretary", "Treasurer"]
