"""#2810: production Sales Invoice builders must pin a selling price list in the
company currency.

`frappe.new_doc("Sales Invoice")` fills the site's global default selling price
list. When that list's currency differs from the company currency erpnext's
`set_price_list_currency` fetches a live exchange rate, which it refuses for a
non-System session user (webhook, guest flow).

Preconditions every test sets explicitly (nothing here relies on the site):
the global default list is a REAL decoy list in JPY (no stored JPY Currency
Exchange row exists for any company currency used here), the exchange-rate cache
is cleared, and the session user is a real Website User.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase, suspend_insert_capture
from verenigingen.tests.backend.components import test_enhanced_sepa_processing as base_sepa
from verenigingen.tests.integration import test_application_payments_invoice_paths as base_paths
from verenigingen.tests.support.sepa_test_company import (
    ensure_membership_dues_item,
    get_eur_test_company,
)

DECOY_CURRENCY = "JPY"


def _make_price_list(name, currency, *, selling=1, enabled=1):
    return frappe.get_doc(
        {
            "doctype": "Price List",
            "price_list_name": name,
            "currency": currency,
            "selling": selling,
            "buying": 0 if selling else 1,
            "enabled": enabled,
        }
    ).insert()


def set_site_default_price_list(name):
    """Write the site default selling price list OUTSIDE the harness's captured-insert drain.

    `set_default` inserts a DefaultValue row; the drain claims every row inserted during a
    test and deletes it at teardown, which deleted the RESTORED default (measured: the site
    ended with no selling_price_list default after the SEPA class)."""
    with suspend_insert_capture():
        frappe.db.set_default("selling_price_list", name)


class _PriceListCase(EnhancedTestCase):
    def setUp(self):
        # Read BEFORE the harness's setUp (which commits and changes site state) or any
        # fixture: the SEPA fixtures left the default unset by the time the decoy went in.
        self._default_before = frappe.db.get_default("selling_price_list")
        super().setUp()
        self._made = []
        self.tag = frappe.generate_hash(length=6)
        self._start_user = frappe.session.user
        self._restorers = []

    def _restore_on_teardown(self, fn, *args):
        """Run `fn(*args)` at the START of tearDown, before the price lists made here are
        deleted. `addCleanup` runs AFTER tearDown, and the harness's tearDown commits: the
        site default then stayed committed pointing at a deleted decoy list (#2233 class)."""
        self._restorers.append((fn, args))

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        default = frappe.db.get_default("selling_price_list")
        assert not default or frappe.db.exists("Price List", default), (
            f"site default selling_price_list {default!r} names a Price List that no longer exists"
        )

    def tearDown(self):
        frappe.set_user(self._start_user)
        while self._restorers:
            fn, args = self._restorers.pop()
            fn(*args)
        set_site_default_price_list(self._default_before)
        assert frappe.db.get_default("selling_price_list") == self._default_before
        for doctype, name in reversed(self._made):
            if frappe.db.exists(doctype, name):
                frappe.delete_doc(doctype, name, force=True)
        # Commit the restore and the deletes together. Mid-test commits (the harness's setUp,
        # the builders) had already committed the decoy default; without this the end-of-class
        # rollback put it back (same reason as own_settings_company's _write).
        frappe.db.commit()
        super().tearDown()

    def _price_list(self, label, currency, **kw):
        pl = _make_price_list(f"ZZ 2810 {label} {self.tag}", currency, **kw)
        self._made.append(("Price List", pl.name))
        return pl.name

    def _zz2810_customer(self, default_price_list=None):
        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": f"ZZ 2810 Customer {self.tag}",
                "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
                "territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
                "default_price_list": default_price_list,
            }
        ).insert()
        self._made.append(("Customer", customer.name))
        return customer.name


class TestResolveSellingPriceList(_PriceListCase):
    def _resolve(self, currency, customer=None):
        from verenigingen.utils.invoice_price_list import get_selling_price_list_for_currency

        return get_selling_price_list_for_currency(currency, customer)

    def test_branch1_customer_default_list_in_company_currency_wins(self):
        # Control: another enabled JPY selling list sorts BEFORE the customer's,
        # so a pick-first-by-name wrong fix returns it instead.
        self._price_list("AAA other", "JPY")
        mine = self._price_list("ZZZ customer", "JPY")
        self.assertEqual(self._resolve("JPY", self._zz2810_customer(mine)), mine)

    def test_branch1_customer_list_in_other_currency_is_ignored(self):
        foreign = self._price_list("foreign", "CHF")
        other = self._price_list("AAA jpy", "JPY")
        self.assertEqual(self._resolve("JPY", self._zz2810_customer(foreign)), other)

    def test_branch2_picks_enabled_selling_list_in_currency_by_name(self):
        # Controls: a disabled list and a buying-only list sort first and must be skipped.
        self._price_list("AAA disabled", "JPY", enabled=0)
        self._price_list("AAB buying", "JPY", selling=0)
        second = self._price_list("BBB second", "JPY")
        self._price_list("CCC third", "JPY")
        picked = self._resolve("JPY")
        self.assertEqual(picked, second)

    def test_branch3_creates_standard_selling_list_when_none_exists(self):
        currency = "CHF"
        self.assertFalse(
            frappe.db.exists("Price List", {"currency": currency, "selling": 1, "enabled": 1}),
            "precondition: no enabled selling CHF list on this site",
        )
        # Non-System caller: creation must not depend on the caller's permissions.
        user = _website_user(self)
        frappe.set_user(user)
        name = self._resolve(currency)
        frappe.set_user(self._start_user)
        self._made.append(("Price List", name))
        self.assertEqual(name, "Standard Selling CHF")
        row = frappe.db.get_value("Price List", name, ["currency", "selling", "enabled"], as_dict=True)
        self.assertEqual((row.currency, row.selling, row.enabled), (currency, 1, 1))
        # Idempotent: a second call reuses it.
        self.assertEqual(self._resolve(currency), name)

    def test_unusable_standard_selling_row_is_never_returned(self):
        """An existing "Standard Selling CHF" that is disabled, buying-only or in another
        currency must not be handed back; a distinct usable list is made instead."""
        currency = "CHF"
        variants = {
            "disabled": {"currency": currency, "enabled": 0},
            "buying only": {"currency": currency, "selling": 0},
            "other currency": {"currency": "JPY"},
        }
        for label, kw in variants.items():
            with self.subTest(label):
                bad = _make_price_list("Standard Selling CHF", **kw)
                self._made.append(("Price List", bad.name))
                picked = self._resolve(currency)
                self.assertNotEqual(picked, bad.name)
                self._made.append(("Price List", picked))
                row = frappe.db.get_value("Price List", picked, ["currency", "selling", "enabled"], as_dict=True)
                self.assertEqual((row.currency, row.selling, row.enabled), (currency, 1, 1))
                for doctype, name in self._made[-2:]:
                    frappe.delete_doc(doctype, name, force=True)

    def test_lost_creation_race_adopts_the_winners_row(self):
        """Probe shortcut: the race is simulated by inserting the competing row between the
        helper's exists-check and its insert (a real second connection is not driven)."""
        from unittest import mock

        currency = "CHF"
        name = f"Standard Selling {currency}"
        real_exists = frappe.db.exists
        raced = []

        def exists_then_lose_race(doctype, filters=None, *a, **k):
            found = real_exists(doctype, filters, *a, **k)
            if doctype == "Price List" and filters == name and not found and not raced:
                raced.append(_make_price_list(name, currency))
            return found

        # Mock justified: injects the concurrent insert at the exact point the race happens.
        with mock.patch.object(frappe.db, "exists", side_effect=exists_then_lose_race):
            picked = self._resolve(currency)
        self.assertTrue(raced, "the competing insert must have happened")
        self._made.append(("Price List", name))
        self.assertEqual(picked, name)


def _website_user(case):
    email = f"zz2810.{case.tag}@example.com".lower()
    frappe.get_doc(
        {
            "doctype": "User",
            "email": email,
            "first_name": "ZZ2810",
            "user_type": "Website User",
            # What the real webhook user carries (a Website User): its role plus Accounts User
            # from its role profile (#1925), which the Item/Customer reads need.
            "roles": [{"role": "Verenigingen Webhook User"}, {"role": "Accounts User"}],
            "send_welcome_email": 0,
        }
    ).insert()
    case._made.append(("User", email))
    return email


class TestBuildersRunAsNonSystemUser(_PriceListCase):
    """Real builders, real Website User, default list in a currency with no stored rate."""

    def setUp(self):
        super().setUp()
        self.company = get_eur_test_company()
        self.company_currency = frappe.db.get_value("Company", self.company, "default_currency")
        self.assertNotEqual(self.company_currency, DECOY_CURRENCY)
        decoy = self._price_list("decoy default", DECOY_CURRENCY)
        set_site_default_price_list(decoy)
        frappe.cache().delete_keys("currency_exchange_rate_*")
        self.assertFalse(
            frappe.db.exists(
                "Currency Exchange", {"from_currency": DECOY_CURRENCY, "to_currency": self.company_currency}
            ),
            "precondition: no stored rate, so only a live fetch could price the list",
        )
        self.user = _website_user(self)

    def test_orphan_invoice_is_created_for_non_system_caller(self):
        from verenigingen.verenigingen_payments.mollie.tests.test_mollie_payment_orchestrator_sweep import (
            _bare_orchestrator,
        )

        ensure_membership_dues_item("Daily")
        income = frappe.db.get_value(
            "Account", {"company": self.company, "root_type": "Income", "is_group": 0}, "name"
        )
        self._zz2810_set_single("Verenigingen Settings", "company", self.company)
        self._zz2810_set_single("Verenigingen Payments Settings", "dues_income_account", income)
        orch = _bare_orchestrator()
        customer = orch._get_or_create_orphan_customer()
        frappe.set_user(self.user)
        name = orch._create_orphan_invoice(
            payment_id=f"tr_2810_{self.tag}",
            customer=customer,
            amount=12.5,
            payment_date=frappe.utils.today(),
        )
        frappe.set_user(self._start_user)
        why = frappe.db.get_value(
            "Error Log", {"method": "Orphan Invoice Creation Error"}, "error", order_by="creation desc"
        )
        self.assertTrue(name, f"orphan invoice must be created for a non-System caller; last error: {why}")
        si = frappe.get_doc("Sales Invoice", name)
        self.assertEqual(si.price_list_currency, self.company_currency)
        self.assertEqual(frappe.db.get_value("Price List", si.selling_price_list, "currency"), self.company_currency)

    def _zz2810_set_single(self, doctype, field, value):
        orig = frappe.db.get_single_value(doctype, field)
        frappe.db.set_single_value(doctype, field, value)
        frappe.clear_document_cache(doctype, doctype)

        def restore():
            frappe.db.set_single_value(doctype, field, orig)
            frappe.clear_document_cache(doctype, doctype)

        self._restore_on_teardown(restore)


class _DecoyDefaultCase(_PriceListCase):
    """Default list in JPY WITH a stored JPY->company rate, so no live fetch is
    needed and the builder runs as Administrator without the network. Unpinned, the
    invoice then keeps the JPY decoy; pinned, it carries a company-currency list."""

    def setUp(self):
        super().setUp()
        self._install_decoy(get_eur_test_company())

    def _install_decoy(self, company):
        self.company_currency = frappe.db.get_value("Company", company, "default_currency")
        decoy = self._price_list("decoy default", DECOY_CURRENCY)
        set_site_default_price_list(decoy)
        rate = frappe.get_doc(
            {
                "doctype": "Currency Exchange",
                "date": frappe.utils.today(),
                "from_currency": DECOY_CURRENCY,
                "to_currency": self.company_currency,
                "exchange_rate": 0.0061,
                "for_selling": 1,
                "for_buying": 1,
            }
        ).insert()
        self._made.append(("Currency Exchange", rate.name))

    def _assert_pinned(self, invoice):
        self.assertEqual(
            frappe.db.get_value("Price List", invoice.selling_price_list, "currency"),
            self.company_currency,
            f"invoice kept price list {invoice.selling_price_list!r} instead of a company-currency one",
        )
        self.assertEqual(invoice.currency, self.company_currency)


class TestGeneratorBuilderPinsPriceList(_DecoyDefaultCase):
    def test_invoice_generator_build_invoice_document(self):
        from types import SimpleNamespace

        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        company = get_eur_test_company()
        income = frappe.db.get_value(
            "Account", {"company": company, "root_type": "Income", "is_group": 0}, "name"
        )
        orig = frappe.db.get_single_value("Verenigingen Settings", "company")
        frappe.db.set_single_value("Verenigingen Settings", "company", company)
        frappe.clear_document_cache("Verenigingen Settings", "Verenigingen Settings")
        self._restore_on_teardown(frappe.db.set_single_value, "Verenigingen Settings", "company", orig)
        self._restore_on_teardown(frappe.clear_document_cache, "Verenigingen Settings", "Verenigingen Settings")
        item = ensure_membership_dues_item("Monthly")
        customer = self._zz2810_customer()
        # Stand-in for the generator instance: only the attributes the builder reads.
        gen = SimpleNamespace(
            schedule_name=f"ZZ2810-{self.tag}",
            schedule=SimpleNamespace(contribution_mode="Regular"),
            member_name=None,
            member_display_name="ZZ 2810",
            membership_type="ZZ",
            billing_frequency="Monthly",
            dues_rate=10.0,
        )
        today = frappe.utils.getdate()
        invoice = InvoiceGenerator._build_invoice_document(
            gen,
            SimpleNamespace(customer=customer, current_membership_plan=None),
            today,
            frappe.utils.add_days(today, 29),
            income,
            None,
            None,
            item,
            {"payment_terms": None, "sepa_mandate_id": None},
        )
        self._made.append(("Sales Invoice", invoice.name))
        self._assert_pinned(invoice)


class TestApprovalInvoiceBuilderPinsPriceList(_DecoyDefaultCase, base_paths._InvoicePathBase):
    """`create_membership_invoice_with_amount` (a get_doc dict builder), with the member's
    Customer deliberately NOT pinned to a list (the base fixture's `_pin_customer_price_list`
    is what hid this)."""

    def setUp(self):
        _PriceListCase.setUp(self)
        base_paths._InvoicePathBase.setUp(self)
        settings_company = frappe.db.get_single_value("Verenigingen Settings", "company")
        self.assertTrue(settings_company, "precondition: Verenigingen Settings.company is set")
        self._made_rate_for = settings_company
        self._install_decoy(settings_company)

    def test_approval_invoice_pins_company_currency_list(self):
        from verenigingen.services.member.approval import application_payments as ap

        member = self.create_test_member(first_name="Inv", last_name=f"P{self.factory.test_run_id}")
        membership = self.create_test_membership(member=member.name)
        membership_type = frappe.get_doc("Membership Type", membership.membership_type)
        self._ensure_membership_item(membership_type.membership_type_name)
        customer = ap.create_customer_for_member(member)
        self.track_doc("Customer", customer.name)
        member.db_set("customer", customer.name)
        member.reload()
        frappe.db.set_value("Customer", customer.name, "default_price_list", None)
        invoice = ap.create_membership_invoice_with_amount(member, membership, 20.0)
        self._track_approval_invoice(invoice.name)
        self._assert_pinned(invoice)


class TestSepaDuesBuilderPinsPriceList(_DecoyDefaultCase):
    """`SEPABatchProcessor.create_dues_invoice`, which sets no currency of its own."""

    # Reuse the SEPA suite's schedule fixtures (borrowed as functions, so that suite's
    # test methods are not collected here).
    _setup_type_template = base_sepa.TestEnhancedSEPAProcessing._setup_type_template
    _ensure_active_membership = base_sepa.TestEnhancedSEPAProcessing._ensure_active_membership
    _cancel_auto_schedules = base_sepa.TestEnhancedSEPAProcessing._cancel_auto_schedules
    _ensure_sepa_payment_terms_template = (
        base_sepa.TestEnhancedSEPAProcessing._ensure_sepa_payment_terms_template
    )
    create_test_dues_schedule_for_collection = (
        base_sepa.TestEnhancedSEPAProcessing.create_test_dues_schedule_for_collection
    )

    def setUp(self):
        _PriceListCase.setUp(self)
        self.test_member = self.create_test_member()
        self.test_membership_type = self.create_test_membership_type(amount=20.0)
        self._setup_type_template(self.test_membership_type)

    def test_sepa_dues_invoice_pins_company_currency_list(self):
        from verenigingen.verenigingen_payments.services.sepa_batch_processor import SEPABatchProcessor

        processor = SEPABatchProcessor()
        self.assertTrue(processor.company, "precondition: SEPA config names a company")
        self._install_decoy(processor.company.name)
        schedule = self.create_test_dues_schedule_for_collection()
        invoice = processor.create_dues_invoice(schedule, frappe.utils.today())
        self.assertTrue(invoice, "dues invoice must be created")
        self._made.append(("Sales Invoice", invoice.name))
        self._assert_pinned(invoice)
