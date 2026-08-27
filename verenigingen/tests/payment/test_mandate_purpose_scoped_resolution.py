"""Purpose-blind mandate resolution: the sites #598 left behind (#597).

#598 fixed four sites that resolved a member's SEPA Mandate with
`ORDER BY creation DESC LIMIT 1`. It did NOT establish "one Active mandate per
member" -- it established one per member **per purpose**, because the app
genuinely models a member holding an Active membership mandate alongside an
Active donation mandate (`SEPAMandate.validate_single_active_mandate_per_purpose`
says so, and `test_payment_history_writer_parity` guards a real divergence caused
by exactly that shape).

That makes the remaining sites WORSE than #597 first recorded, not merely
theoretical. Each of them filters `status = 'Active'` with no purpose filter, so
for any member who holds both a dues mandate and a donation mandate the query is
ambiguous **by construction** and resolves the ambiguity by recency. Sites in
`load_unpaid_invoices` write `iban`/`bic`/`mandate_reference` straight into the
Direct Debit Batch rows the SEPA XML is generated from: a donation-only mandate
signed later than the membership mandate supplies the IBAN that gets debited for
dues.

Every fixture here is therefore built with an ordinary `save()`. No
`frappe.db.set_value` bypass is needed -- unlike `test_mandate_candidates`, which
needs one because two Active mandates *sharing* a purpose are blocked. The two
mandates below are both legitimately Active, and `test_the_ambiguous_state_is_reachable`
is the control proving it: if that test ever fails, the rest of this module is
asserting against a state the guard has started rejecting, and the module is
measuring nothing.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment.test_sepa_batch_ui import SepaBatchUITestBase
from verenigingen.verenigingen_payments.api import sepa_batch_ui as ui, sepa_batch_ui_secure as secure

MEMBERSHIP_IBAN = "NL91ABNA0417164300"
DONATION_IBAN = "NL02ABNA0123456789"


def norm_iban(iban):
    """Compare IBANs without depending on stored formatting.

    `SEPA Mandate.iban` is stored FORMATTED, in space-separated groups of four
    ("NL91 ABNA 0417 1643 00"), so a literal comparison against the unspaced
    constant above fails for reasons that have nothing to do with which mandate
    was chosen. Normalising keeps the assertion about the choice.
    """
    return (iban or "").replace(" ", "")

# The membership mandate is signed and created FIRST; the donation mandate is
# newer on every column these sites order by (`creation`, `sign_date`). So
# "newest wins" and "membership wins" give different answers, which is what makes
# each assertion below discriminating rather than merely consistent.
MEMBERSHIP_CREATION = "2020-01-01 00:00:00"
DONATION_CREATION = "2021-01-01 00:00:00"


class PurposeScopedMandateFixture(EnhancedTestCase):
    """A member with one Active membership mandate and one NEWER donation mandate."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="PurposeScope", last_name="Test")
        self.membership_mandate = self._active_mandate(
            iban=MEMBERSHIP_IBAN,
            sign_date=add_days(today(), -400),
            used_for_memberships=1,
            used_for_donations=0,
        )
        self.donation_mandate = self._active_mandate(
            iban=DONATION_IBAN,
            sign_date=add_days(today(), -1),
            used_for_memberships=0,
            used_for_donations=1,
        )
        # Pin `creation` rather than relying on insert order. Insert order does
        # produce the right sequence today, but it is not the property under test
        # and a same-second collision would silently make "newest" arbitrary --
        # which is the exact failure mode these tests exist to detect.
        frappe.db.set_value(
            "SEPA Mandate", self.membership_mandate.name, "creation", MEMBERSHIP_CREATION,
            update_modified=False,
        )
        frappe.db.set_value(
            "SEPA Mandate", self.donation_mandate.name, "creation", DONATION_CREATION,
            update_modified=False,
        )
        # Reload BOTH: `creation` is a constant field, so a doc still holding the
        # pre-pin value raises CannotChangeConstantError ("Value cannot be changed
        # for Created On") on its next save() -- which
        # test_no_membership_mandate_is_not_the_donation_mandate does.
        self.membership_mandate.reload()
        self.donation_mandate.reload()

    def _active_mandate(self, iban, sign_date, used_for_memberships, used_for_donations):
        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": f"PURP-{frappe.generate_hash(length=8)}",
                "member": self.member.name,
                "account_holder_name": self.member.full_name,
                "iban": iban,
                "sign_date": sign_date,
                "status": "Active",
                "is_active": 1,
                "mandate_type": "RCUR",
                "scheme": "SEPA",
                "used_for_memberships": used_for_memberships,
                "used_for_donations": used_for_donations,
            }
        )
        mandate.insert()
        return mandate


class TestTheAmbiguousStateIsReachable(PurposeScopedMandateFixture):
    def test_the_ambiguous_state_is_reachable(self):
        """The control for this whole module: both mandates are Active via save().

        If the per-purpose guard is ever tightened back to one-Active-per-member,
        this fails FIRST and loudly, rather than every other test here quietly
        passing because the second mandate never existed.
        """
        active = frappe.get_all(
            "SEPA Mandate",
            filters={"member": self.member.name, "status": "Active"},
            fields=["name", "iban", "used_for_memberships", "used_for_donations"],
        )
        self.assertEqual(len(active), 2, f"expected two Active mandates, got {active}")
        self.assertEqual(
            {norm_iban(r.iban) for r in active},
            {MEMBERSHIP_IBAN, DONATION_IBAN},
            "the fixture is not the older-membership / newer-donation shape",
        )
        by_iban = {norm_iban(r.iban): r for r in active}
        self.assertTrue(by_iban[MEMBERSHIP_IBAN].used_for_memberships)
        self.assertFalse(by_iban[DONATION_IBAN].used_for_memberships)


class TestGetDefaultMandateIsPurposeScoped(PurposeScopedMandateFixture):
    """Site 7: `SEPAMandateManager.get_default_mandate` returned `mandates[0]`.

    `get_active_mandates` orders `creation desc` with no purpose filter, so the
    newer donation-only mandate won. `payment_history_service._get_default_mandate`
    already documents this defect in a docstring and works around it locally,
    which is why the two payment-history writers agree and every other caller of
    this helper does not.
    """

    def test_the_donation_only_mandate_does_not_become_the_default(self):
        from verenigingen.services.payment.sepa_mandate_manager import SEPAMandateManager

        default = SEPAMandateManager().get_default_mandate(self.member.name)

        self.assertIsNotNone(default, "a membership-capable Active mandate exists")
        self.assertEqual(
            norm_iban(default.iban),
            MEMBERSHIP_IBAN,
            "the newer donation-only mandate was chosen for a membership default",
        )

    def test_a_donation_default_can_still_be_asked_for_explicitly(self):
        from verenigingen.services.payment.sepa_mandate_manager import SEPAMandateManager

        default = SEPAMandateManager().get_default_mandate(
            self.member.name, purpose="used_for_donations"
        )

        self.assertIsNotNone(default)
        self.assertEqual(norm_iban(default.iban), DONATION_IBAN)

    def test_no_membership_mandate_is_not_the_donation_mandate(self):
        """Purpose-scoping must return NOTHING, not fall back across purposes."""
        from verenigingen.services.payment.sepa_mandate_manager import SEPAMandateManager

        self.membership_mandate.status = "Cancelled"
        self.membership_mandate.is_active = 0
        self.membership_mandate.save()

        default = SEPAMandateManager().get_default_mandate(self.member.name)

        self.assertIsNone(
            default,
            "a donation-only mandate was offered as the membership default",
        )


class TestGetActiveSepaMandateIsPurposeScoped(PurposeScopedMandateFixture):
    """Site 8: `limit=1` with NO `order_by` -- nondeterministic, not even recency.

    Its live consumer is `templates/pages/payment_dashboard.py:257`.
    """

    def test_the_module_level_helper_is_purpose_scoped(self):
        from verenigingen.services.payment.sepa_mandate_manager import get_active_sepa_mandate

        mandate = get_active_sepa_mandate(self.member.name)

        self.assertIsNotNone(mandate)
        self.assertEqual(
            norm_iban(mandate["iban"]),
            MEMBERSHIP_IBAN,
            "an arbitrary Active mandate was returned for a membership lookup",
        )

    def test_an_unknown_purpose_raises_instead_of_returning_none(self):
        """A failure inside this helper must not read as "this member has no mandate".

        The old body was `try: ... except Exception: return None`, which collapsed
        *failure* into *absence* -- the trap #581 already paid for: a caller reading
        falsy as "nothing here" goes on to create what is missing, and this repo has
        billed a member a third period that way.

        The direct form of this test injects a database failure and asserts that it
        propagates, but patching the framework query helper counts as a DATABASE MOCK
        under `scripts/validation/test_quality_enforcer.py` and is rejected --
        correctly, as a rule. So the property is covered from two sides instead: a
        real error the function can actually raise (here), and the structural
        guarantee that no handler remains to swallow anything (next test).
        """
        from verenigingen.services.payment.sepa_mandate_manager import get_active_sepa_mandate

        with self.assertRaises(ValueError):
            get_active_sepa_mandate(self.member.name, purpose="not_a_purpose_flag")

    def test_the_helper_has_no_exception_handler_left(self):
        """No `except` in the body, so no failure can be converted into None.

        A source-shape assertion rather than a behavioural one, for the reason given
        above. It is the same kind of instrument the repo already uses for this bug
        class (`scripts/validation/error_swallow_validator.py`), narrowed to one
        function -- and it fails if the handler is reintroduced, which is the
        regression worth catching.
        """
        import ast
        import inspect

        from verenigingen.services.payment.sepa_mandate_manager import get_active_sepa_mandate

        tree = ast.parse(inspect.getsource(get_active_sepa_mandate))
        handlers = [node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)]

        self.assertEqual(
            handlers,
            [],
            "get_active_sepa_mandate caught something again; a swallowed failure here "
            "reads to callers as 'this member has no mandate'",
        )

class TestLoadUnpaidInvoicesIsPurposeScoped(SepaBatchUITestBase):
    """Sites 5 and 6: the batch UI's bulk mandate join.

    `load_unpaid_invoices` resolves every member's mandate in ONE query and then
    deduplicates in Python with an explicit *"Only keep the first (most recent)
    mandate per membership"*. The join filtered `status = 'Active'` with no purpose
    filter, so for a member holding both a dues mandate and a donation mandate the
    result set carried two rows for one membership and the newer one won.

    These values are not cosmetic: `iban`, `bic` and `mandate_reference` are what
    the operator selects into a Direct Debit Batch, and the batch is what the SEPA
    XML is generated from. This is the same consequence that justified fixing
    `get_invoice_mandate_info` in #598 -- the only difference is that this site
    resolves in bulk.

    A purpose filter is the fix rather than blanking-on-ambiguity, which #597
    originally proposed: under a per-purpose invariant, blanking any member with two
    Active mandates would blank every member who merely also donates.
    """

    def _chain_with_newer_donation_mandate(self, first_name):
        chain = self._build_member_with_invoice(first_name=first_name)
        donation = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": f"PURP-DON-{frappe.generate_hash(length=8)}",
                "member": chain["member"].name,
                "account_holder_name": chain["member"].full_name,
                "iban": DONATION_IBAN,
                "sign_date": today(),
                "status": "Active",
                "is_active": 1,
                "mandate_type": "RCUR",
                "scheme": "SEPA",
                "used_for_memberships": 0,
                "used_for_donations": 1,
            }
        )
        donation.insert()
        # The membership mandate must be the OLDER row on the column the join orders
        # by, or "newest wins" and "membership wins" agree and the assertion below
        # would pass against the unfixed code.
        frappe.db.set_value(
            "SEPA Mandate", chain["mandate"].name, "creation", MEMBERSHIP_CREATION,
            update_modified=False,
        )
        frappe.db.set_value(
            "SEPA Mandate", donation.name, "creation", DONATION_CREATION, update_modified=False
        )
        # `creation` is a constant field: a doc still holding the pre-pin value raises
        # CannotChangeConstantError on its next save(), which
        # test_a_donation_only_member_gets_no_dues_iban does.
        chain["mandate"].reload()
        donation.reload()
        return chain, donation

    def _row_for(self, rows, chain):
        self.assertFalse(self._is_error_result(rows), f"endpoint returned an error: {rows}")
        row = next((r for r in rows if r.get("invoice") == chain["invoice"].name), None)
        self.assertIsNotNone(row, f"this chain's invoice was not in the batch list: {rows}")
        return row

    def test_the_batch_list_carries_the_membership_iban(self):
        chain, donation = self._chain_with_newer_donation_mandate("LoadPurpose")

        rows = ui.load_unpaid_invoices(
            date_range="all", membership_type=self._membership_type(chain), limit=100
        )

        row = self._row_for(rows, chain)
        self.assertEqual(
            norm_iban(row["iban"]),
            norm_iban(chain["mandate"].iban),
            "a newer donation-only mandate supplied the IBAN for a dues batch",
        )
        self.assertNotEqual(norm_iban(row["iban"]), DONATION_IBAN)
        self.assertEqual(
            row["mandate_reference"],
            chain["mandate"].mandate_id,
            "the batch would carry the donation mandate's reference",
        )

    def test_the_secure_twin_carries_the_membership_iban(self):
        chain, donation = self._chain_with_newer_donation_mandate("LoadPurposeSec")

        rows = secure.load_unpaid_invoices_secure(
            date_range="all", membership_type=self._membership_type(chain), limit=100
        )

        row = self._row_for(rows, chain)
        self.assertEqual(
            norm_iban(row["iban"]),
            norm_iban(chain["mandate"].iban),
            "a newer donation-only mandate supplied the IBAN for a dues batch",
        )
        self.assertNotEqual(norm_iban(row["iban"]), DONATION_IBAN)

    def test_a_donation_only_member_gets_no_dues_iban(self):
        """Purpose-scoping must not fall back across purposes for the bulk path.

        A member whose ONLY Active mandate is donation-only has no mandate for a
        dues batch. Reporting the donation IBAN here is the defect; reporting the
        donation IBAN because "it is the only one" is the same defect with a nicer
        justification.
        """
        chain, donation = self._chain_with_newer_donation_mandate("LoadPurposeOnly")
        chain["mandate"].status = "Cancelled"
        chain["mandate"].is_active = 0
        chain["mandate"].save()

        rows = ui.load_unpaid_invoices(
            date_range="all", membership_type=self._membership_type(chain), limit=100
        )

        row = self._row_for(rows, chain)
        self.assertEqual(row["iban"], "", f"the donation mandate was offered for dues: {row}")
        self.assertEqual(row["mandate_reference"], "")


class TestBatchMandateHelpersArePurposeScoped(PurposeScopedMandateFixture):
    """The two near-relatives #597 lists: same class, ordered by something else.

    Neither has a production caller today, which is why they are listed separately
    rather than as sites 1-8. They are fixed anyway: both are shared helpers whose
    whole job is "give me this member's mandate", and a future caller would trust
    the answer. `get_active_mandates_for_members` is whitelisted, so it is reachable
    from outside the app regardless of who calls it internally.
    """

    def test_sepa_mandate_service_batch_is_purpose_scoped(self):
        from verenigingen.verenigingen_payments.utils.sepa_mandate_service import SEPAMandateService

        # A fresh instance, not the module singleton: the singleton's in-process
        # cache may already hold an entry for this member from another test.
        result = SEPAMandateService().get_active_mandate_batch([self.member.name])

        self.assertIn(self.member.name, result)
        self.assertEqual(
            norm_iban(result[self.member.name]["iban"]),
            MEMBERSHIP_IBAN,
            "the newer donation-only mandate won a memberships batch lookup",
        )

    def test_sepa_mandate_service_cache_does_not_answer_across_purposes(self):
        """The cache key must carry the purpose, or the first lookup poisons the next."""
        from verenigingen.verenigingen_payments.utils.sepa_mandate_service import SEPAMandateService

        service = SEPAMandateService()
        memberships = service.get_active_mandate_batch([self.member.name])
        donations = service.get_active_mandate_batch(
            [self.member.name], purpose="used_for_donations"
        )

        self.assertEqual(norm_iban(memberships[self.member.name]["iban"]), MEMBERSHIP_IBAN)
        self.assertEqual(
            norm_iban(donations[self.member.name]["iban"]),
            DONATION_IBAN,
            "a memberships lookup answered a donations lookup from cache",
        )

    def test_optimized_queries_batch_is_purpose_scoped(self):
        from verenigingen.utils.optimized_queries import OptimizedSEPAQueries

        result = OptimizedSEPAQueries.get_active_mandates_for_members([self.member.name])

        self.assertIn(self.member.name, result)
        self.assertEqual(
            norm_iban(result[self.member.name]["iban"]),
            MEMBERSHIP_IBAN,
            "the newer donation-only mandate won a memberships batch lookup",
        )

    def test_an_unknown_purpose_is_rejected_not_interpolated(self):
        """`purpose` names a COLUMN and cannot be bound, so the allowlist is the guard.

        `get_active_mandates_for_members` is whitelisted, which makes this value
        caller-supplied.
        """
        from verenigingen.utils.optimized_queries import OptimizedSEPAQueries

        with self.assertRaises(ValueError):
            OptimizedSEPAQueries.get_active_mandates_for_members(
                [self.member.name], purpose="1=1 OR used_for_memberships"
            )


class TestSecureBatchUiMembershipTypeFilter(SepaBatchUITestBase):
    """A separate pre-existing defect, found because it blocked the site-6 test.

    `load_unpaid_invoices_secure` resolved `membership_type` to **Membership** names
    and filtered `membership_dues_schedule_display` -- a Link to **Membership Dues
    Schedule** -- against them. Those name spaces never intersect, so the endpoint
    returned an empty list for every valid membership type. The non-secure twin was
    fixed for exactly this and carries the explanation; this copy never got it.

    The `if memberships:` guard was the dangerous half: on an empty resolution it
    applied NO filter, loading every unpaid invoice on the site into the batch
    selector.
    """

    def test_a_valid_membership_type_finds_its_own_invoice(self):
        chain = self._build_member_with_invoice(first_name="SecureFilter")

        rows = secure.load_unpaid_invoices_secure(
            date_range="all", membership_type=self._membership_type(chain), limit=100
        )

        self.assertFalse(self._is_error_result(rows), f"endpoint returned an error: {rows}")
        self.assertIn(
            chain["invoice"].name,
            [r.get("invoice") for r in rows],
            "the membership_type filter matched nothing for a type that has invoices",
        )

    def test_a_type_with_no_schedules_returns_nothing_not_everything(self):
        membership_type = self.create_test_membership_type(
            membership_type_name=f"PurposeNoSched{frappe.generate_hash(length=6)}"
        )
        # The factory creates a TEMPLATE dues schedule alongside the type, so the
        # type is not schedule-free as created and the `return []` branch is never
        # reached. Remove them, or this test passes for the wrong reason: the
        # template also matches no invoices, so the endpoint returns [] either way.
        for schedule in frappe.get_all(
            "Membership Dues Schedule", filters={"membership_type": membership_type.name}, pluck="name"
        ):
            frappe.delete_doc("Membership Dues Schedule", schedule, force=True, ignore_permissions=True)
        self.assertEqual(
            frappe.get_all(
                "Membership Dues Schedule",
                filters={"membership_type": membership_type.name},
                limit=1,
            ),
            [],
            "fixture invalid: this membership type still has a dues schedule",
        )

        rows = secure.load_unpaid_invoices_secure(
            date_range="all", membership_type=membership_type.name, limit=100
        )

        self.assertEqual(
            rows, [], "an unfiltered invoice list was loaded for a type with no schedules"
        )
