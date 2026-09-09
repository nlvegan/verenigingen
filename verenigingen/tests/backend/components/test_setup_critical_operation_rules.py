# Integration tests for verenigingen/setup/critical_operation_rules_setup.py
#
# This module runs from the `after_install` hook (verenigingen/hooks/lifecycle.py)
# and is the ONLY thing that puts Critical Operation Rule (COR) rows on a brand
# new site: COR is deliberately NOT in hooks.fixtures, precisely so that
# migrations cannot overwrite a site's tuned rate limits. That makes this module
# a single point of failure for fresh installs -- and every failure inside it is
# swallowed into a returned `errors` list, so a broken fixture produces a site
# whose API security framework silently falls back to generic defaults.
#
# Strategy:
#   * Assert the fixture DATA is loadable into real Critical Operation Rule docs
#     (valid doctype/name/fieldnames/Select options). A drifted fixture would
#     otherwise only show up as a swallowed string in `errors` on a fresh site.
#   * Exercise the real create branch by deleting a rule and re-running the
#     setup, asserting the rule comes back with the fixture's exact limits.
#   * Assert the preserve-user-customisation contract (existing rules are
#     skipped, never overwritten) -- that is the documented reason this module
#     exists instead of a fixture.

import json
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.setup import critical_operation_rules_setup as cor_setup

FIXTURE_FILES = [
    "critical_operation_rule.json",
    "critical_operation_rule_ponto_debug.json",
    "critical_operation_rule_balance_transactions.json",
    "critical_operation_rule_payment_recovery.json",
]


def _fixtures_dir():
    return Path(frappe.get_app_path("verenigingen")) / "fixtures"


def _load_all_fixture_rules():
    """Return [(fixture_file, rule_dict), ...] for every shipped COR fixture."""
    rules = []
    for fname in FIXTURE_FILES:
        path = _fixtures_dir() / fname
        if not path.exists():
            continue
        with open(path, "r") as fh:
            for rule in json.load(fh):
                rules.append((fname, rule))
    return rules


class TestCriticalOperationRuleFixtureData(FrappeTestCase):
    """The shipped fixture payloads must actually be insertable.

    setup_critical_operation_rules() wraps every insert in try/except and only
    appends the message to a returned list, so a malformed fixture does NOT fail
    the install -- it just leaves the rule missing. These tests catch that at
    source instead.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rules = _load_all_fixture_rules()

    def test_fixture_files_are_present_and_non_empty(self):
        """All four fixture files the setup module names must exist.

        A renamed/moved fixture file is silently skipped ("Fixture file not
        found") and its rules never get created on a fresh site.
        """
        for fname in FIXTURE_FILES:
            path = _fixtures_dir() / fname
            self.assertTrue(path.exists(), f"COR fixture file missing: {path}")
        self.assertGreater(len(self.rules), 0, "No COR fixture rules loaded at all")

    def test_every_rule_declares_the_critical_operation_rule_doctype(self):
        """frappe.get_doc(rule_data) needs a "doctype" key.

        Without it get_doc raises and the rule is silently dropped into `errors`.
        """
        offenders = [
            (f, r.get("name"))
            for f, r in self.rules
            if r.get("doctype") != "Critical Operation Rule"
        ]
        self.assertEqual(offenders, [], f"Fixture rows with wrong/missing doctype: {offenders[:5]}")

    def test_every_rule_has_a_name(self):
        """setup_critical_operation_rules() skips rows without a "name" entirely
        (`if not rule_name: continue`), so such a row is unreachable data."""
        offenders = [(f, i) for i, (f, r) in enumerate(self.rules) if not r.get("name")]
        self.assertEqual(offenders, [], f"Fixture rows without a name: {offenders[:5]}")

    def test_autoname_overrides_the_fixture_name_key(self):
        """Critical Operation Rule autonames by `field:operation_name`, so the
        "name" key in a fixture row is NOT what lands in the database.

        This matters because setup_critical_operation_rules() keys its existence
        check on the fixture's "name". Any fixture row whose "name" differs from
        its "operation_name" is therefore never recognised as already-present:
        the setup re-attempts the insert on every subsequent run and swallows the
        resulting DuplicateEntryError into `errors`.

        KNOWN DEFECT: 12 shipped rules currently have name != operation_name
        (see test_mismatched_rows_are_the_only_source_of_setup_errors, which
        tolerates exactly those and fails on anything new). The naming mechanism
        itself is pinned here on a throwaway rule.
        """
        doc = frappe.get_doc(
            {
                "doctype": "Critical Operation Rule",
                "name": "zz_declared_name_that_is_discarded",
                "operation_name": "zz.scratch.autonamed_operation",
                "operation_type": "utility",
                "security_level": "low",
            }
        )
        doc.insert()
        self.addCleanup(frappe.delete_doc, "Critical Operation Rule", doc.name, force=1)

        self.assertEqual(doc.name, "zz.scratch.autonamed_operation")
        self.assertFalse(
            frappe.db.exists("Critical Operation Rule", "zz_declared_name_that_is_discarded"),
            "The fixture's `name` key does not survive autonaming",
        )

    def test_every_fixture_rule_is_reachable_by_operation_name(self):
        """`operation_name` -- not `name` -- is the key the runtime looks rules up
        by (RateLimitEngine._get_cor_config filters on operation_name), so every
        shipped rule must be present under its operation_name after install."""
        declared = {r["operation_name"] for _f, r in self.rules if r.get("operation_name")}
        present = set(frappe.get_all("Critical Operation Rule", pluck="operation_name"))
        missing = sorted(declared - present)
        self.assertEqual(
            missing,
            [],
            f"{len(missing)} shipped COR rules are not installed under their "
            f"operation_name (runtime falls back to _generic_api_fallback): {missing[:5]}",
        )

    def test_generic_api_fallback_rule_is_installed(self):
        """RateLimitEngine._get_cor_config falls back to the rule literally named
        "_generic_api_fallback" whenever an operation has no rule of its own. If
        that row is missing on a fresh site, unclassified endpoints get no rate
        limit config at all."""
        fallback = frappe.db.get_value(
            "Critical Operation Rule",
            {"operation_name": "_generic_api_fallback", "enabled": 1},
            ["rate_limit_calls", "rate_limit_period_seconds", "rate_limit_scope"],
            as_dict=True,
        )
        self.assertIsNotNone(fallback, "_generic_api_fallback COR must exist and be enabled")
        self.assertGreater(fallback.rate_limit_calls, 0)
        self.assertGreater(fallback.rate_limit_period_seconds, 0)
        self.assertEqual(fallback.rate_limit_scope, "per_user")

    # Guest-reachable endpoints that resolve a caller-supplied document id
    # whose autoname is a sequential naming_series (#1018), i.e. each one is a
    # docname-enumeration surface. Each needs a rule of its own so its limit is
    # a deliberate choice rather than _generic_api_fallback's per_user scope --
    # which, for an unauthenticated caller, collapses to a single bucket keyed
    # on the literal "Guest" that every anonymous visitor shares (#1028/#1033).
    # That shared bucket is a denial-of-service vector: one abuser exhausts the
    # budget for every other visitor. retry_payment got such a rule from #1028;
    # refresh_payment_status is the sibling found in #1105.
    #
    # Minimum call rate each endpoint's own client legitimately needs, so a
    # limit can never be tightened to a value that silently breaks the page:
    # payment_success.html polls refresh_payment_status every 10s for 5 minutes
    # while a payment is pending (6 calls/minute), and per_ip scope means
    # several visitors behind one NAT share that budget.
    GUEST_ENUMERATION_ENDPOINTS = {
        "retry_payment": 0,
        "refresh_payment_status": 6 / 60.0,
    }

    def test_guest_enumeration_endpoints_have_a_dedicated_per_ip_rule(self):
        """Each guest-reachable enumeration endpoint must have its own rule, scoped
        per_ip rather than per_user, and permissive enough for its own client (#1105).

        Deliberately NOT asserted: that the limit is tighter than the fallback.
        A polling endpoint legitimately needs a HIGHER rate than the fallback's
        100/hour -- the point of a dedicated rule here is that the limit is
        chosen and the scope distinguishes anonymous callers, not that it is
        smaller.
        """
        by_operation = {rule.get("operation_name"): rule for _fname, rule in self.rules}

        missing, wrong_scope, unbounded, too_tight = [], [], [], []
        for operation, required_rate in self.GUEST_ENUMERATION_ENDPOINTS.items():
            rule = by_operation.get(operation)
            if rule is None:
                missing.append(operation)
                continue
            if rule.get("rate_limit_scope") != "per_ip":
                wrong_scope.append((operation, rule.get("rate_limit_scope")))
            calls = rule.get("rate_limit_calls") or 0
            period = rule.get("rate_limit_period_seconds") or 0
            if calls <= 0 or period <= 0:
                unbounded.append((operation, calls, period))
                continue
            if calls / period < required_rate:
                too_tight.append((operation, f"{calls}/{period}s", f"needs >= {required_rate:.3f}/s"))

        self.assertEqual(
            missing,
            [],
            f"Guest enumeration endpoints with no Critical Operation Rule of their own: "
            f"{missing}. They fall to _generic_api_fallback, whose per_user scope is one "
            f"bucket shared by every anonymous visitor (#1105).",
        )
        self.assertEqual(
            wrong_scope,
            [],
            f"Guest enumeration endpoints whose rule is not per_ip: {wrong_scope}. "
            f"per_user cannot distinguish anonymous callers, so one abuser locks out all.",
        )
        self.assertEqual(unbounded, [], f"Rules with a non-positive limit bound nothing: {unbounded}")
        self.assertEqual(
            too_tight,
            [],
            f"Rules too tight for their own client's polling rate, which would break the "
            f"page rather than protect it: {too_tight}",
        )

    def test_no_duplicate_rule_names_across_fixture_files(self):
        """Two fixture files defining the same rule means whichever is processed
        first wins and the other definition is silently skipped forever."""
        seen = {}
        duplicates = []
        for fname, rule in self.rules:
            name = rule.get("name")
            if name in seen:
                duplicates.append((name, seen[name], fname))
            else:
                seen[name] = fname
        self.assertEqual(duplicates, [], f"Duplicate COR names across fixtures: {duplicates[:5]}")

    def test_every_fixture_key_is_a_real_field(self):
        """Frappe silently DROPS unknown keys passed to get_doc().

        A fixture key that no longer exists on the DocType (renamed field) would
        therefore create a rule with a missing rate limit rather than fail, so a
        fresh site would quietly run unthrottled.
        """
        meta = frappe.get_meta("Critical Operation Rule")
        known = {f.fieldname for f in meta.fields} | {"doctype", "name"}
        unknown = set()
        for _fname, rule in self.rules:
            unknown |= set(rule.keys()) - known
        self.assertEqual(unknown, set(), f"Fixture keys not present on the DocType: {sorted(unknown)}")

    def test_select_field_values_are_valid_options(self):
        """An out-of-range Select value makes insert() raise -> rule dropped."""
        meta = frappe.get_meta("Critical Operation Rule")
        select_options = {
            f.fieldname: set((f.options or "").split("\n"))
            for f in meta.fields
            if f.fieldtype == "Select"
        }
        offenders = []
        for _fname, rule in self.rules:
            for fieldname, allowed in select_options.items():
                if fieldname in rule and rule[fieldname] not in allowed:
                    offenders.append((rule.get("name"), fieldname, rule[fieldname]))
        self.assertEqual(offenders, [], f"Invalid Select values in COR fixtures: {offenders[:5]}")

    def test_mandatory_fields_are_populated(self):
        """reqd fields missing -> MandatoryError on insert -> rule dropped."""
        meta = frappe.get_meta("Critical Operation Rule")
        mandatory = [f.fieldname for f in meta.fields if f.reqd]
        self.assertIn("operation_name", mandatory)  # guard: meta really has reqd fields
        offenders = [
            (r.get("name"), fn)
            for _f, r in self.rules
            for fn in mandatory
            if not r.get(fn)
        ]
        self.assertEqual(offenders, [], f"COR fixtures missing mandatory fields: {offenders[:5]}")


class TestSetupCriticalOperationRules(FrappeTestCase):
    """setup_critical_operation_rules() behaviour against the live database."""

    # A low-risk, self-contained rule used to exercise the create branch.
    PROBE_RULE = "_generic_api_fallback"

    def _fixture_for(self, rule_name):
        for _fname, rule in _load_all_fixture_rules():
            if rule.get("name") == rule_name:
                return rule
        self.fail(f"Fixture rule {rule_name!r} not found")

    def test_returns_created_skipped_errors_contract(self):
        result = cor_setup.setup_critical_operation_rules()
        self.assertEqual(sorted(result.keys()), ["created", "errors", "skipped"])
        self.assertIsInstance(result["created"], int)
        self.assertIsInstance(result["skipped"], int)
        self.assertIsInstance(result["errors"], list)

    def test_mismatched_rows_are_the_only_source_of_setup_errors(self):
        """Every swallowed failure lands in `errors`; nothing else may.

        The only tolerated entries are the shipped rules whose fixture "name"
        differs from their "operation_name" (see
        TestCriticalOperationRuleFixtureData.test_autoname_overrides_the_fixture_name_key):
        those can never be recognised as already-present, so on a site where
        they were installed under their autonamed operation_name the setup
        re-attempts the insert and records a duplicate error.

        Any OTHER error means a fixture/DocType drift that leaves a real rule
        missing on a fresh install.
        """
        tolerated = {
            r["name"]
            for _f, r in _load_all_fixture_rules()
            if r.get("name") and r.get("name") != r.get("operation_name")
        }
        result = cor_setup.setup_critical_operation_rules()
        unexpected = [e for e in result["errors"] if e.split(":", 1)[0] not in tolerated]
        self.assertEqual(unexpected, [], f"Unexpected COR setup errors: {unexpected[:5]}")

    def test_recreates_a_deleted_rule_with_the_fixture_values(self):
        """The fresh-install create branch.

        Deleting a rule and re-running the setup must restore it with exactly the
        limits the fixture declares -- this is the only code path that populates
        Critical Operation Rule on a brand new site.
        """
        fixture = self._fixture_for(self.PROBE_RULE)
        self.assertTrue(frappe.db.exists("Critical Operation Rule", self.PROBE_RULE))

        frappe.delete_doc("Critical Operation Rule", self.PROBE_RULE, force=1)
        self.assertFalse(frappe.db.exists("Critical Operation Rule", self.PROBE_RULE))

        result = cor_setup.setup_critical_operation_rules()

        self.assertGreaterEqual(result["created"], 1)
        self.assertTrue(frappe.db.exists("Critical Operation Rule", self.PROBE_RULE))
        restored = frappe.get_doc("Critical Operation Rule", self.PROBE_RULE)
        # Assert against the fixture, not against a re-read of the doc, so a
        # dropped/renamed field in the fixture makes this fail.
        self.assertEqual(restored.operation_type, fixture["operation_type"])
        self.assertEqual(restored.security_level, fixture["security_level"])
        self.assertEqual(restored.rate_limit_calls, fixture["rate_limit_calls"])
        self.assertEqual(
            restored.rate_limit_period_seconds, fixture["rate_limit_period_seconds"]
        )
        self.assertEqual(restored.rate_limit_scope, fixture["rate_limit_scope"])
        self.assertEqual(restored.audit_level, fixture["audit_level"])

    def test_a_fixture_rule_added_by_1105_reaches_an_EXISTING_site(self):
        """setup_critical_operation_rules runs in after_install ONLY (hooks/lifecycle.py:17),
        never in after_migrate, so adding a rule to the fixture installs it on a fresh
        site and on no other. Reaching an existing site takes a patch -- which is why
        patches.txt already carries add_retry_payment_critical_operation_rule for #1028's
        rule. #1105's rule needs the same, or its rate limit is inert everywhere the app
        is already installed.
        """
        rule_name = "refresh_payment_status"
        fixture = self._fixture_for(rule_name)
        self.assertEqual(fixture["rate_limit_scope"], "per_ip")

        # Restore on the way out even if this test fails: the delete below is
        # committed by the patch's own commit, so a failure between the delete
        # and the re-create would strand the rule missing for every sibling
        # test in this class.
        self.addCleanup(cor_setup.setup_critical_operation_rules)

        frappe.delete_doc("Critical Operation Rule", rule_name, force=1)
        self.assertFalse(frappe.db.exists("Critical Operation Rule", rule_name))

        from verenigingen.patches.v2_2.add_refresh_payment_status_critical_operation_rule import (
            execute,
        )

        execute()

        self.assertTrue(
            frappe.db.exists("Critical Operation Rule", rule_name),
            "the patch did not install the rule, so an existing site never gets it",
        )
        restored = frappe.get_doc("Critical Operation Rule", rule_name)
        # Assert against the fixture, not a re-read of the doc, so a dropped or
        # renamed fixture field makes this fail.
        self.assertEqual(restored.rate_limit_scope, fixture["rate_limit_scope"])
        self.assertEqual(restored.rate_limit_calls, fixture["rate_limit_calls"])
        self.assertEqual(restored.rate_limit_period_seconds, fixture["rate_limit_period_seconds"])

    def test_the_1105_patch_is_registered_in_patches_txt(self):
        """A patch module that is not listed never runs, so the fixture/patch pair is
        only complete once patches.txt names it."""
        listed = (
            Path(frappe.get_app_path("verenigingen")).parent / "verenigingen" / "patches.txt"
        ).read_text()
        self.assertIn(
            "verenigingen.patches.v2_2.add_refresh_payment_status_critical_operation_rule",
            listed,
        )

    def test_does_not_overwrite_a_customised_rule(self):
        """The module's entire reason to exist: an operator's tuned rate limit
        must survive re-running the install/patch entry point."""
        original = frappe.db.get_value(
            "Critical Operation Rule", self.PROBE_RULE, "rate_limit_calls"
        )
        self.assertIsNotNone(original)
        customised = int(original) + 4242
        frappe.db.set_value(
            "Critical Operation Rule", self.PROBE_RULE, "rate_limit_calls", customised
        )

        cor_setup.setup_critical_operation_rules()

        self.assertEqual(
            frappe.db.get_value("Critical Operation Rule", self.PROBE_RULE, "rate_limit_calls"),
            customised,
            "setup_critical_operation_rules() must not overwrite an existing rule",
        )

    def test_second_run_creates_nothing_and_accounts_for_every_rule(self):
        """Idempotency: a second run must create nothing, and every named fixture
        rule must be accounted for as either skipped or errored -- no rule may be
        silently dropped from the run."""
        cor_setup.setup_critical_operation_rules()
        second = cor_setup.setup_critical_operation_rules()

        named = [r for _f, r in _load_all_fixture_rules() if r.get("name")]
        self.assertEqual(second["created"], 0, "A repeat run must not create rules")
        self.assertEqual(
            second["skipped"] + len(second["errors"]),
            len(named),
            "Every named fixture rule must be either skipped or reported",
        )

    def test_add_missing_rules_delegates_to_setup(self):
        """add_missing_critical_operation_rules() is the documented
        bench-execute/patch entry point and must behave identically."""
        result = cor_setup.add_missing_critical_operation_rules()
        self.assertEqual(sorted(result.keys()), ["created", "errors", "skipped"])
        self.assertEqual(result["created"], 0)
        self.assertGreater(result["skipped"], 0)

    def test_missing_fixture_file_is_skipped_not_fatal(self):
        """A fixture file that does not exist must be skipped silently rather
        than raising -- otherwise one renamed file aborts the whole install."""
        # Point the module's fixture lookup at a directory with no fixtures.
        missing_dir = Path(frappe.get_site_path()) / "no-such-cor-fixture-dir"
        self.assertFalse(missing_dir.exists())

        class _StubPath:
            """Stands in for pathlib.Path(__file__); resolves to missing_dir."""

            def __init__(self, *_a, **_kw):
                pass

            @property
            def parent(self):
                return self

            def __truediv__(self, other):
                return missing_dir / other

        with patch.object(cor_setup, "Path", _StubPath):
            result = cor_setup.setup_critical_operation_rules()

        self.assertEqual(result, {"created": 0, "skipped": 0, "errors": []})
