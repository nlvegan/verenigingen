"""
Structural regression tests for a CLASS of Mollie-integration defects.

Every defect pinned here actually shipped, and every one of them was found by a
human or an agent reading the diff -- never by a test, a validator or CI. The
point of this module is to move that detection into the suite. Each test closes
a *class* rather than an instance: a static scan plus a ratchet, or a
behavioural invariant that any new instance of the shape must violate.

    1. Non-idempotent remote creates (#345).
       ``subscriptions.create()`` is a non-idempotent remote write. If Mollie
       commits it and the response is lost, a retry creates a SECOND
       subscription and the donor is charged twice per period forever. The SDK
       defaults ``idempotency_key`` to a fresh ``uuid4()`` per call, which gives
       NO cross-retry protection. -> ``TestMollieRemoteCreatesAreIdempotent``
       scans every ``<resource>.create(...)`` call in the Mollie code and
       ratchets the set that has no deterministic key.

    2. Normalised-dict whitelist drift (#343).
       ``_fetch_payment_from_mollie`` rebuilds the Mollie payment as a
       hand-listed dict, TWICE (a dict branch and an object branch). It silently
       dropped ``sequenceType``/``customerId``/``subscriptionId``, leaving three
       readers permanently dead. This shape has now caused three incidents.
       -> ``TestNormalisedPaymentDictContract`` asserts the two branches emit
       identical key sets, and that every key any reader in the class asks of
       that dict is actually produced.

    3. Branch asymmetry between fakes and production (#343).
       A real ``mollie.api.objects.Payment`` subclasses ``dict``, so
       ``isinstance(payment, dict)`` is TRUE and production ALWAYS takes the
       camelCase dict branch. Every fake in this repo was a plain object and
       exercised the OTHER branch, so the camelCase key names were covered by
       nothing. -> ``TestNormalisedPaymentDictContract`` drives the REAL SDK
       class (constructed offline from a canonical payload) rather than a fake,
       and pins the SDK's MRO so an SDK upgrade that changes it goes red.

    4. Readers with no writer across a string-key boundary (#341, #343).
       ``form_data["recurring_interval"]`` had 2 readers and 0 writers;
       ``metadata["subscription_id"]`` has 3 readers and no producer. No
       compiler and no validator notices. -> ``TestMollieMetadataKeysHaveWriters``
       cross-checks the Mollie payment ``metadata`` dict -- the string-key
       boundary that crosses a process, from payment creation to webhook -- and
       ratchets the orphans that exist today. (Scope note in that class.)

    5. Unconditional network calls on paths that do not need them (#344 review).
       ``_handle_fully_processed_payment`` needs no payment data; adding an
       unconditional ``_fetch_payment_from_mollie()`` (which RAISES) broke
       refund/chargeback handling on that path. -> ``TestFullyProcessedPathDoesNotFetch``
       drives the real refund chain with the Mollie client wired to explode.

No network. Only the Mollie SDK/HTTP boundary is faked; no business logic is
mocked.

Run with:
    bench --site test_site_4 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_integration_invariants
"""

import ast
import os
import re
import unittest
from collections import Counter
from types import SimpleNamespace
from unittest.mock import patch

import frappe

import verenigingen
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.unified_idempotency_manager import (
    PaymentIdempotencyCheckResult,
)
from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
    UnifiedWebhookWrapperService,
)

# Root of the *installed* verenigingen package. Under PYTHONPATH=<worktree> this
# resolves to the worktree, so the scan always reads the code under test.
PACKAGE_ROOT = os.path.dirname(os.path.abspath(verenigingen.__file__))

COMPANY = "_Test Company 2"


# ===========================================================================
# Source scanning (shared by the two static classes)
# ===========================================================================
_SKIP_DIRS = {"__pycache__", "node_modules", "tests", "fixtures", "public", "templates"}


def _is_test_module(filename: str) -> bool:
    return filename.startswith("test_") or filename.endswith("_test.py") or "_test_" in filename


def _mollie_source_files():
    """Yield ``(posix_relpath, abspath)`` for every non-test module that can
    reach the Mollie API: everything under ``verenigingen_payments/`` plus any
    other module whose path mentions mollie (e.g. ``api/mollie_payment.py``)."""
    for dirpath, dirnames, filenames in os.walk(PACKAGE_ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for filename in filenames:
            if not filename.endswith(".py") or _is_test_module(filename):
                continue
            path = os.path.join(dirpath, filename)
            rel = os.path.relpath(path, PACKAGE_ROOT).replace(os.sep, "/")
            if rel.startswith("verenigingen_payments/") or "mollie" in rel:
                yield rel, path


def _parse_module(path: str) -> ast.Module:
    with open(path, "r", encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=path)


def _const_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


class _EnclosingFunctionVisitor(ast.NodeVisitor):
    """Base visitor that tracks the name of the innermost enclosing function."""

    def __init__(self, rel: str):
        self.rel = rel
        self._functions = []

    @property
    def where(self) -> str:
        return self._functions[-1] if self._functions else "<module>"

    def visit_FunctionDef(self, node):
        self._functions.append(node.name)
        self.generic_visit(node)
        self._functions.pop()

    visit_AsyncFunctionDef = visit_FunctionDef


# ===========================================================================
# 1. Non-idempotent remote creates
# ===========================================================================

# Mollie SDK resource collections. A call is a remote create iff it looks like
# ``<anything>.<resource>.create(...)``; this deliberately does NOT match local
# helpers such as ``bank_tx_creator.create(...)`` or ``AuditContext.create(...)``.
#
# Hand-written, but no longer unchecked: ``TestTheResourceListMatchesTheSdk``
# derives the creatable resources from the installed SDK and fails if this set
# omits one. A resource missing here is not a weak assertion somewhere -- it is
# a family of remote creates that no test in this module can see at all.
# ``client_links`` was exactly that: creatable since the SDK gained Mollie
# Connect, absent here, unused by this app today and therefore silently
# unprotected the day someone used it.
_MOLLIE_RESOURCES = frozenset(
    {
        "payments",
        "customers",
        "subscriptions",
        "mandates",
        "refunds",
        "chargebacks",
        "orders",
        "shipments",
        "captures",
        "profiles",
        "terminals",
        "payment_links",
        "client_links",
        "settlements",
    }
)

# An idempotency key that is regenerated per call is worse than useless: it looks
# like protection and provides none. These are the ways to accidentally write one.
_NON_DETERMINISTIC_MARKERS = (
    "uuid",
    "random",
    "generate_hash",
    "token_hex",
    "token_urlsafe",
    "time(",
    "now(",
    # frappe's clock helpers do not end in "now(" -- nowdate()/now_datetime()
    # would have slipped past a "now(" substring check.
    "nowdate",
    "now_datetime",
    "today(",
)

# ---------------------------------------------------------------------------
# THE RATCHET.
#
# These Mollie creates carry no idempotency key today. They are recorded, not
# endorsed: the invariant is that this set may SHRINK but never GROW. A new
# unkeyed remote create fails ``test_no_new_unkeyed_mollie_create``; fixing one
# of these fails ``test_the_unkeyed_ratchet_has_not_rotted`` until it is removed
# from the list, so the list cannot silently drift out of date either.
#
# Mapped site -> allowed COUNT, not a bare set: the site key is
# (file, function, resource), so a second unkeyed create inside an
# already-listed function would otherwise collapse into the same entry and
# escape the ratchet entirely.
#
# The two donation-subscription creates in payment_gateways.py are absent
# because they ARE keyed (``donsub-``/``donagr-`` + payment id, #345) -- the
# retry-safety of those two is asserted behaviourally in
# test_donation_subscription_activation.py, and their key *shape* is pinned by
# ``test_keyed_creates_use_a_deterministic_key`` below.
# ---------------------------------------------------------------------------
_KNOWN_UNKEYED_SITES = frozenset(
    {
        ("api/mollie_payment.py", "update_mollie_bank_account", "mandates"),
        ("services/mollie_debug_service.py", "create_mandate", "mandates"),
        ("verenigingen_payments/doctype/mollie_settings/mollie_settings.py", "create_customer", "customers"),
        ("verenigingen_payments/mollie/core/client.py", "create_customer", "customers"),
        ("verenigingen_payments/mollie/core/client.py", "create_mandate", "mandates"),
        ("verenigingen_payments/mollie/core/client.py", "create_payment", "payments"),
        ("verenigingen_payments/mollie/core/client.py", "create_refund", "refunds"),
        ("verenigingen_payments/mollie/core/client.py", "create_subscription", "subscriptions"),
        (
            "verenigingen_payments/mollie/services/payment_service.py",
            "_create_or_get_mollie_customer",
            "customers",
        ),
        ("verenigingen_payments/utils/payment_gateways.py", "process_payment", "payments"),
    }
)

# Each listed site allows exactly ONE unkeyed create. Spelled out as counts so a
# SECOND unkeyed create added inside an already-listed function cannot hide behind
# the first: the site key is (file, function, resource), so both would collapse to
# one entry under set membership. `test_each_ratcheted_site_has_exactly_one_call`
# keeps this derivation honest.
KNOWN_UNKEYED_MOLLIE_CREATES = {site: 1 for site in _KNOWN_UNKEYED_SITES}


class _MollieCreateVisitor(_EnclosingFunctionVisitor):
    def __init__(self, rel):
        super().__init__(rel)
        self.calls = []
        # Local assignments seen so far, so a key passed as a bare name can be
        # resolved to what it actually holds. Without this,
        # `key = str(uuid.uuid4()); ...create(idempotency_key=key)` reads as a
        # clean identifier and sails through the very check meant to catch it.
        self._assigned = {}

    def visit_Assign(self, node):
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            self._assigned[node.targets[0].id] = node.value
        self.generic_visit(node)

    def _resolve(self, value):
        """Follow a bare name to its assigned expression (one hop is enough in
        practice; a chain of aliases is not a pattern this codebase uses)."""
        if isinstance(value, ast.Name) and value.id in self._assigned:
            return self._assigned[value.id], True
        return value, False

    def visit_Call(self, node):
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "create"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr in _MOLLIE_RESOURCES
        ):
            key = resolved_from = None
            is_constant = False
            for keyword in node.keywords:
                if keyword.arg == "idempotency_key":
                    value, was_resolved = self._resolve(keyword.value)
                    key = ast.unparse(value)
                    resolved_from = ast.unparse(keyword.value) if was_resolved else None
                    # A literal is the only genuinely constant case, and it is
                    # exact -- unlike "does it contain a brace", which fails a
                    # perfectly good `_make_key(payment)` helper.
                    is_constant = isinstance(value, ast.Constant)
            self.calls.append(
                SimpleNamespace(
                    site=(self.rel, self.where, func.value.attr),
                    lineno=node.lineno,
                    idempotency_key=key,
                    idempotency_key_is_constant=is_constant,
                    idempotency_key_resolved_from=resolved_from,
                )
            )
        self.generic_visit(node)


def _scan_mollie_creates():
    calls = []
    for rel, path in _mollie_source_files():
        visitor = _MollieCreateVisitor(rel)
        visitor.visit(_parse_module(path))
        calls.extend(visitor.calls)
    return calls


class TestMollieRemoteCreatesAreIdempotent(unittest.TestCase):
    """Defect class 1: a non-idempotent remote create with no deterministic key.

    Static, because the failure mode is a *missing argument at a call site* --
    there is no runtime signal at all when it is absent, which is precisely why
    it survived review until #345.
    """

    @classmethod
    def setUpClass(cls):
        cls.calls = _scan_mollie_creates()

    def test_the_scanner_actually_finds_the_known_call_sites(self):
        """CONTROL. A scan that silently matches nothing would make every other
        test in this class pass vacuously -- the exact failure the repo's
        verification rules call out. Pin the keyed donation site by name.

        This used to pin two sites, one in each of
        ``_activate_direct_subscription_after_first_payment`` and
        ``_activate_donation_subscription_after_first_payment``. Both now route
        through the extracted ``_get_or_create_subscription``, so there is one
        keyed create where there were two -- the coverage did not shrink, the
        duplication did. If that extraction is ever unwound back into two call
        sites, this control goes red and forces a conscious update.
        """
        keyed = {call.site for call in self.calls if call.idempotency_key}
        expected = {
            (
                "verenigingen_payments/utils/payment_gateways.py",
                "_get_or_create_subscription",
                "subscriptions",
            ),
        }
        # Subset, not equality: keying a further create is a FIX, and this
        # control must not punish it.
        self.assertEqual(
            expected - keyed,
            set(),
            "The Mollie-create scanner no longer sees the keyed donation "
            f"subscription create(s) {sorted(expected - keyed)}; it found "
            f"{sorted(keyed)}. Either the scanner is broken (every other "
            "assertion here is now vacuous) or those call sites moved.",
        )

    def test_no_new_unkeyed_mollie_create(self):
        """A new Mollie remote create must carry a deterministic idempotency key.

        Without one, a lost response turns any retry -- ours or Mollie's webhook
        re-delivery -- into a duplicate remote object. For a subscription that
        means the donor is charged twice every period, forever, with only one of
        the two visible to this system.
        """
        # Counted, not set-membership: the site key is (file, function, resource),
        # so a SECOND unkeyed create added inside an already-ratcheted function
        # would collapse into the same site and vanish. Counting makes the ratchet
        # bite per call rather than per function.
        counts = Counter(call.site for call in self.calls if not call.idempotency_key)
        grown = {site: n for site, n in counts.items() if n > KNOWN_UNKEYED_MOLLIE_CREATES.get(site, 0)}
        self.assertEqual(
            grown,
            {},
            "More unkeyed Mollie create(s) than the ratchet allows at:\n"
            + "\n".join(
                f"  {site[0]} in {site[1]}() -> {site[2]}.create(...): "
                f"{n} unkeyed, ratchet allows {KNOWN_UNKEYED_MOLLIE_CREATES.get(site, 0)}"
                for site, n in sorted(grown.items())
            )
            + "\n",
        )
        new = set(counts) - set(KNOWN_UNKEYED_MOLLIE_CREATES)
        self.assertEqual(
            new,
            set(),
            "New Mollie remote create(s) with no deterministic idempotency_key:\n"
            + "\n".join(
                f"  {path}:{call.lineno} in {func}() -> {resource}.create(...)"
                for (path, func, resource) in sorted(new)
                for call in self.calls
                if call.site == (path, func, resource)
            )
            + "\n\nMollie's SDK defaults idempotency_key to a fresh uuid4() per call, "
            "which gives NO protection against a lost response. Pass a key derived "
            'from something stable (e.g. f"donsub-{payment.id}"), or -- if the '
            "create is genuinely safe to repeat -- add it to "
            "KNOWN_UNKEYED_MOLLIE_CREATES with a reason.",
        )

    def test_each_ratcheted_site_has_exactly_one_call(self):
        """The counted ratchet is derived as one-per-site; prove that holds.

        If a listed function ever genuinely contains two unkeyed creates, this
        goes red and the count must be written out explicitly -- rather than the
        derivation quietly licensing an extra one.
        """
        counts = Counter(call.site for call in self.calls if not call.idempotency_key)
        multiples = {site: n for site, n in counts.items() if n > 1}
        self.assertEqual(
            multiples,
            {},
            "These call sites hold more than one unkeyed create, so the "
            "one-per-site derivation of KNOWN_UNKEYED_MOLLIE_CREATES no longer "
            f"describes the code: {sorted(multiples.items())}",
        )

    def test_the_unkeyed_ratchet_has_not_rotted(self):
        """Every entry in the ratchet must still be a real unkeyed call site.

        Without this the list would quietly accumulate dead entries and stop
        describing the code, which is how allowlists lose their meaning.
        """
        unkeyed = {call.site for call in self.calls if not call.idempotency_key}
        stale = set(KNOWN_UNKEYED_MOLLIE_CREATES) - unkeyed
        self.assertEqual(
            stale,
            set(),
            "KNOWN_UNKEYED_MOLLIE_CREATES lists call sites that are no longer "
            f"unkeyed creates: {sorted(stale)}. Remove them from the ratchet so it "
            "keeps describing the code.",
        )

    def test_keyed_creates_use_a_deterministic_key(self):
        """The key must be derived from stable data, not regenerated per call.

        ``idempotency_key=str(uuid.uuid4())`` type-checks, reads like protection,
        and behaves exactly like passing nothing at all.
        """
        for call in self.calls:
            if not call.idempotency_key:
                continue
            expression = call.idempotency_key
            via = (
                f" (passed as {call.idempotency_key_resolved_from}, which holds this)"
                if call.idempotency_key_resolved_from
                else ""
            )
            with self.subTest(site=call.site):
                offenders = [m for m in _NON_DETERMINISTIC_MARKERS if m in expression]
                self.assertEqual(
                    offenders,
                    [],
                    f"{call.site[0]}:{call.lineno} passes idempotency_key={expression}{via}, "
                    f"which is regenerated per call ({offenders}). A per-call key is "
                    "indistinguishable from no key at all: a retry after a lost "
                    "response still creates a duplicate.",
                )
                self.assertFalse(
                    call.idempotency_key_is_constant,
                    f"{call.site[0]}:{call.lineno} passes a constant "
                    f"idempotency_key={expression}{via}. A constant is shared by every "
                    "payment, so the FIRST donor's subscription would be returned "
                    "to all later ones. It must be derived from the payment.",
                )


def _sdk_creatable_resource_accessors():
    """Every attribute name a caller can reach a CREATABLE Mollie resource through.

    Read from the installed SDK, because ``_MOLLIE_RESOURCES`` above is the
    *input* to the scanner: a resource missing from it is not one weak
    assertion, it is a whole family of call sites that no test in this class can
    see. ``ResourceCreateMixin.create``'s signature is already read at runtime
    two hundred lines below for precisely this reason -- the resource list was
    the half still hand-maintained, with nothing to notice an SDK upgrade adding
    a creatable resource.

    Two ways to reach a resource, and both have to be collected:

    * off the client -- ``Client.__init__`` binds ``self.payments = Payments(self)``,
      so instantiating one (no credentials, no network) and reading its instance
      dict gives every client-level name;
    * off an object -- ``Customer.subscriptions`` is a property returning
      ``CustomerSubscriptions(self.client, self)``. Those properties carry no
      return annotation, so the class is read out of their source with ast.

    One accessor name can front several resource classes: ``payments`` is
    ``Payments`` on the client and ``SubscriptionPayments`` on a subscription.
    So this maps name -> {class names}, and a name counts as creatable when ANY
    class behind it is. Collapsing it to one class per name silently drops
    ``payments`` and ``refunds`` from the creatable set -- measured while
    writing this, not hypothesised.
    """
    import mollie.api.objects
    import mollie.api.resources
    from mollie.api.client import Client
    from mollie.api.resources.base import ResourceBase, ResourceCreateMixin

    accessors = {}

    def record(name, cls):
        if isinstance(cls, type) and issubclass(cls, ResourceBase):
            accessors.setdefault(name, set()).add(cls.__name__)

    for name, value in vars(Client()).items():
        record(name, type(value))

    objects_dir = mollie.api.objects.__path__[0]
    for entry in sorted(os.listdir(objects_dir)):
        if not entry.endswith(".py"):
            continue
        for node in ast.walk(_parse_module(os.path.join(objects_dir, entry))):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not any(isinstance(d, ast.Name) and d.id == "property" for d in node.decorator_list):
                continue
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Return)
                    and isinstance(inner.value, ast.Call)
                    and isinstance(inner.value.func, ast.Name)
                ):
                    record(node.name, getattr(mollie.api.resources, inner.value.func.id, None))

    def is_creatable(cls_name):
        cls = getattr(mollie.api.resources, cls_name, None)
        return isinstance(cls, type) and issubclass(cls, ResourceCreateMixin)

    return {
        name: sorted(classes)
        for name, classes in accessors.items()
        if any(is_creatable(cls_name) for cls_name in classes)
    }


class TestTheResourceListMatchesTheSdk(unittest.TestCase):
    """The scanner's blind spot, checked against the SDK rather than by memory.

    ``_MOLLIE_RESOURCES`` decides what counts as a remote create at all. Every
    assertion in ``TestMollieRemoteCreatesAreIdempotent`` is scoped by it, so a
    creatable resource it omits is invisible to the ratchet, to the
    deterministic-key check and to the control that claims the scanner still
    sees anything.
    """

    @classmethod
    def setUpClass(cls):
        cls.creatable = _sdk_creatable_resource_accessors()

    def test_the_sdk_scan_finds_the_resources_it_is_looking_for(self):
        """CONTROL. An empty or near-empty derivation would make the coverage
        assertion below pass while checking nothing -- the failure mode this
        module exists to catch, applied to itself."""
        self.assertGreaterEqual(
            len(self.creatable),
            8,
            "Derived only "
            f"{sorted(self.creatable)} creatable Mollie resource accessor(s) from the "
            "installed SDK. Either the SDK moved its resources (Client no longer "
            "binds them in __dict__, or the object properties no longer return a "
            "resource class by name) or this derivation is broken -- in which case "
            "the coverage assertion below is vacuous.",
        )
        self.assertIn(
            "subscriptions",
            self.creatable,
            "The derivation lost `subscriptions`, the one resource this whole " "module was written about.",
        )

    def test_every_creatable_sdk_resource_is_in_the_scanners_resource_list(self):
        """A creatable resource the scanner does not know is a family of call
        sites nothing here can see.

        Asserted in ONE direction only. ``_MOLLIE_RESOURCES`` may name resources
        the SDK cannot create (``chargebacks``, ``settlements``, ``terminals``
        are list-only today): matching a call that cannot exist costs nothing,
        while removing them would make the list churn every time Mollie makes a
        resource creatable. Under-inclusion is the direction that hides defects.
        """
        missing = {name: self.creatable[name] for name in set(self.creatable) - _MOLLIE_RESOURCES}
        self.assertEqual(
            missing,
            {},
            "The installed Mollie SDK can create resource(s) that _MOLLIE_RESOURCES "
            "does not list, so `<anything>."
            + "|".join(sorted(missing) or ["<none>"])
            + ".create(...)` is invisible to every test in "
            "TestMollieRemoteCreatesAreIdempotent:\n"
            + "\n".join(f"  {name} -> {', '.join(classes)}" for name, classes in sorted(missing.items()))
            + "\n\nAdd the accessor name(s) to _MOLLIE_RESOURCES.",
        )


# ===========================================================================
# 3 (static half). Test stubs that are narrower than the SDK they stand in for
# ===========================================================================
#
# CI on #346 failed exactly this way: production started passing
# ``idempotency_key=`` and eight test stubs declared ``def create(self, data)``.
# The resulting TypeError was swallowed by a broad ``except`` into a generic
# ``{'status': 'error'}``, so it surfaced two shards away as a confusing
# assertion failure rather than as "your stub is wrong".
#
# The invariant is one-directional and simple: **a stub may not be narrower than
# the real method it fakes**. A stub that accepts less than the SDK cannot see
# every call production is allowed to make, so it validates a smaller API than
# the one that ships -- and the divergence is invisible until a caller uses the
# part the stub omitted.
#
# Identification is deliberately syntactic: a class method named ``create``
# whose first parameter after ``self`` is named ``data``. That is the Mollie
# SDK's own parameter name; measured across this app it selects all 16 Mollie
# resource stubs and neither of the two unrelated ``create`` methods
# (``BankTransactionCreator.create(self, date, ...)`` and
# ``AuditContextClean.create(self, execution_source)``). It is under- rather
# than over-inclusive: a future stub written as ``def create(self, payload)``
# would escape. That is an accepted, stated limit -- the alternative is
# importing every test module to inspect it at runtime, which this repo
# forbids (mass-importing test modules poisons the frappe registry).
# ---------------------------------------------------------------------------


def _all_python_files():
    """Every .py in the package, INCLUDING test modules (which is the point)."""
    for dirpath, dirnames, filenames in os.walk(PACKAGE_ROOT):
        dirnames[:] = [d for d in dirnames if d not in {"__pycache__", "node_modules"}]
        for filename in filenames:
            if filename.endswith(".py"):
                path = os.path.join(dirpath, filename)
                yield os.path.relpath(path, PACKAGE_ROOT).replace(os.sep, "/"), path


def _sdk_create_signature():
    """The real ``ResourceCreateMixin.create`` signature -- the thing being faked.

    Read from the installed SDK rather than hardcoded, so an SDK upgrade that
    widens or renames a parameter propagates to every stub check automatically.
    """
    import inspect

    from mollie.api.resources.base import ResourceCreateMixin

    parameters = inspect.signature(ResourceCreateMixin.create).parameters
    named = [
        name
        for name, parameter in parameters.items()
        if name != "self"
        and parameter.kind
        in (parameter.POSITIONAL_OR_KEYWORD, parameter.KEYWORD_ONLY, parameter.POSITIONAL_ONLY)
    ]
    has_catch_all = any(p.kind is p.VAR_KEYWORD for p in parameters.values())
    return named, has_catch_all


def _scan_mollie_resource_stubs():
    """Yield ``(relpath, classname, lineno, accepted_names, has_catch_all)``."""
    stubs = []
    for rel, path in _all_python_files():
        try:
            tree = _parse_module(path)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for member in node.body:
                if not isinstance(member, ast.FunctionDef) or member.name != "create":
                    continue
                positional = [arg.arg for arg in member.args.posonlyargs + member.args.args]
                if len(positional) < 2 or positional[1] != "data":
                    continue  # not a Mollie resource stub
                accepted = set(positional[1:]) | {arg.arg for arg in member.args.kwonlyargs}
                stubs.append(
                    SimpleNamespace(
                        rel=rel,
                        cls=node.name,
                        lineno=member.lineno,
                        accepted=accepted,
                        has_catch_all=member.args.kwarg is not None,
                    )
                )
    return stubs


class TestMollieResourceStubsMatchTheSdk(unittest.TestCase):
    """Defect class 3, static half: a fake narrower than the real thing."""

    @classmethod
    def setUpClass(cls):
        cls.stubs = _scan_mollie_resource_stubs()
        cls.sdk_named, cls.sdk_has_catch_all = _sdk_create_signature()

    def test_the_scanner_finds_the_mollie_resource_stubs(self):
        """CONTROL. An empty scan would make the two assertions below vacuous."""
        self.assertGreaterEqual(
            len(self.stubs),
            10,
            f"Expected the Mollie resource stubs to be found; got {self.stubs}. "
            "Either they were all renamed, or the `first parameter is named "
            "'data'` heuristic no longer selects them -- in which case the "
            "assertions below are checking nothing.",
        )

    def test_the_sdk_create_signature_is_what_the_stubs_are_written_against(self):
        """Pins the real signature. If an SDK upgrade changes it, this is the
        test that says so, instead of eight unrelated shards going red."""
        self.assertEqual(
            self.sdk_named,
            ["data", "idempotency_key"],
            "mollie.api.resources.base.ResourceCreateMixin.create no longer takes "
            f"(data, idempotency_key, **params) -- it now takes {self.sdk_named}. "
            "Every Mollie resource stub in this repo is written against the old "
            "signature and is now narrower than the thing it fakes.",
        )
        self.assertTrue(self.sdk_has_catch_all, "The SDK's create() no longer accepts **params")

    def test_no_stub_is_narrower_than_the_sdk_method_it_fakes(self):
        """Every Mollie resource stub must accept what the real SDK accepts.

        A stub that omits a parameter production is entitled to pass raises
        TypeError deep inside a broadly-caught call path, where it is reported as
        a generic failure somewhere else entirely.
        """
        offenders = []
        for stub in self.stubs:
            missing = [name for name in self.sdk_named if name not in stub.accepted]
            if missing or (self.sdk_has_catch_all and not stub.has_catch_all):
                offenders.append(
                    f"  {stub.rel}:{stub.lineno} {stub.cls}.create() "
                    f"missing={missing or 'nothing'} "
                    f"catch_all={'yes' if stub.has_catch_all else 'NO'}"
                )
        self.assertEqual(
            offenders,
            [],
            "Mollie resource stub(s) are narrower than the SDK method they stand in for:\n"
            + "\n".join(sorted(offenders))
            + f"\n\nThe real signature is create(self, {', '.join(self.sdk_named)}, **params). "
            "Write the stub to match it -- not just to accept the one argument that "
            "happens to break today. A narrower stub validates a smaller API than "
            "the one that ships.",
        )


# ===========================================================================
# 4. Readers with no writer across a string-key boundary
# ===========================================================================
#
# SCOPE, stated narrowly on purpose. A general "reader with no writer" check
# over arbitrary dicts is not tractable without unacceptable false positives:
# most dicts in this code are decoded JSON from Mollie or a posted web form, so
# the writer is out of the repo entirely and every read would be reported.
#
# What IS tractable is the boundary where BOTH ends live here: the Mollie
# payment ``metadata`` dict. We write it when creating a payment and read it
# back, in a different process, at webhook time -- a pure string-key contract
# with no compiler, no schema and no validator. That is exactly the boundary
# #341 (``subscription_interval``) and #343 crossed. Measured on this branch the
# check yields three orphans and no false positives, so it is ratchetable.
#
# ``form_data`` -- the ORIGINAL #341 surface -- is scanned too, by
# ``TestDonateFormKeysHaveWriters`` below. Its writers are not Python, but they
# are plain files in this repo: ``name="..."`` attributes in donate.html and
# ``formData.X`` / ``getElementById('X')`` in donation_form.js. "The writer is
# not Python" is a reason the scan cannot be AST-only, not a reason it cannot
# exist -- and this is the boundary that actually shipped the bug.
# ---------------------------------------------------------------------------

KNOWN_ORPHAN_METADATA_READS = {
    # Read as a first-choice hint before falling back to parsing the payment
    # description. Nothing in this app ever writes it, so the branch is dead.
    "invoice_id": "verenigingen_payments/utils/bank_transaction_reconciliation.py",
    # PaymentContextResolver._resolve_from_metadata and
    # PaymentService.process_payment_by_type both dispatch on it; no producer
    # exists, so both dispatches always fall through.
    "payment_type": "payment_context_resolver.py / payment_service.py",
    # Read as a fallback for payment_data["subscription_id"] (which IS produced,
    # from Mollie's own subscriptionId). The metadata fallback itself has no
    # producer -- this is the #343 shape, still present.
    "subscription_id": "webhook_wrapper_service_unified.py / subscription_service.py",
}


def _is_metadata_expression(node) -> bool:
    """True if ``node`` syntactically evaluates to a Mollie metadata dict."""
    if isinstance(node, ast.Name):
        return node.id == "metadata"
    if isinstance(node, ast.Attribute):
        return node.attr == "metadata"
    if isinstance(node, ast.Subscript):
        return _const_str(node.slice) == "metadata"
    if isinstance(node, ast.Call):
        # payment_data.get("metadata", {})
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "get" and node.args:
            return _const_str(node.args[0]) == "metadata"
    if isinstance(node, ast.BoolOp):
        # payment_data.get("metadata") or {}
        return any(_is_metadata_expression(value) for value in node.values)
    return False


class _MetadataKeyVisitor(ast.NodeVisitor):
    def __init__(self, rel):
        self.rel = rel
        self.reads = {}
        self.writes = {}

    def _record(self, bucket, key, lineno):
        if key:
            bucket.setdefault(key, []).append(f"{self.rel}:{lineno}")

    def _record_dict_keys(self, dict_node, bucket):
        for key_node in dict_node.keys:
            self._record(bucket, _const_str(key_node), getattr(key_node, "lineno", 0))

    def visit_Call(self, node):
        func = node.func
        if isinstance(func, ast.Attribute) and node.args and _is_metadata_expression(func.value):
            if func.attr == "get":
                self._record(self.reads, _const_str(node.args[0]), node.lineno)
            elif func.attr == "update" and isinstance(node.args[0], ast.Dict):
                self._record_dict_keys(node.args[0], self.writes)
        self.generic_visit(node)

    def visit_Subscript(self, node):
        if _is_metadata_expression(node.value):
            self._record(self.reads, _const_str(node.slice), node.lineno)
        self.generic_visit(node)

    def visit_Compare(self, node):
        # `if "subscription_type" in payment.metadata:` is a read too.
        for op, comparator in zip(node.ops, node.comparators):
            if isinstance(op, ast.In) and _is_metadata_expression(comparator):
                self._record(self.reads, _const_str(node.left), node.lineno)
        self.generic_visit(node)

    def visit_Assign(self, node):
        for target in node.targets:
            if _is_metadata_expression(target) and isinstance(node.value, ast.Dict):
                self._record_dict_keys(node.value, self.writes)
            if isinstance(target, ast.Subscript) and _is_metadata_expression(target.value):
                self._record(self.writes, _const_str(target.slice), target.lineno)
        self.generic_visit(node)

    def visit_Dict(self, node):
        # {"metadata": {"donation_id": ...}} -- the literal form used when
        # building a payment payload.
        for key_node, value_node in zip(node.keys, node.values):
            if _const_str(key_node) == "metadata" and isinstance(value_node, ast.Dict):
                self._record_dict_keys(value_node, self.writes)
        self.generic_visit(node)


def _scan_metadata_keys():
    reads, writes = {}, {}
    for rel, path in _mollie_source_files():
        visitor = _MetadataKeyVisitor(rel)
        visitor.visit(_parse_module(path))
        for key, sites in visitor.reads.items():
            reads.setdefault(key, []).extend(sites)
        for key, sites in visitor.writes.items():
            writes.setdefault(key, []).extend(sites)
    return reads, writes


class TestMollieMetadataKeysHaveWriters(unittest.TestCase):
    """Defect class 4: a metadata key read in N places and written in zero."""

    @classmethod
    def setUpClass(cls):
        cls.reads, cls.writes = _scan_metadata_keys()

    def test_the_scanner_sees_both_ends_of_the_boundary(self):
        """CONTROL. If either half of the scan silently returned nothing, the
        orphan test below would pass (empty reads) or fail wholesale (empty
        writes). Pin a key that is demonstrably written AND read -- the #341
        interval, whose producer and consumer are both in this tree."""
        self.assertIn(
            "subscription_interval",
            self.writes,
            f"Scanner found no writer for subscription_interval; writers={sorted(self.writes)}",
        )
        self.assertIn(
            "subscription_interval",
            self.reads,
            f"Scanner found no reader for subscription_interval; readers={sorted(self.reads)}",
        )

    def test_no_new_metadata_key_is_read_without_a_writer(self):
        """A metadata key with readers and no producer is dead code that reads
        like live code -- the #341/#343 root cause. Nothing else detects it."""
        orphans = {key: sites for key, sites in self.reads.items() if key not in self.writes}
        new = set(orphans) - set(KNOWN_ORPHAN_METADATA_READS)
        self.assertEqual(
            new,
            set(),
            "Mollie payment metadata key(s) are READ but never WRITTEN anywhere "
            "in this app:\n"
            + "\n".join(f"  {key!r} read at {orphans[key]}" for key in sorted(new))
            + "\n\nEvery reader of these is permanently dead: the value is always "
            "None. Either write the key where the payment is created, or delete "
            "the reader. (This is issue #341/#343: a string key crossing a "
            "process boundary has no compiler.)",
        )

    def test_the_orphan_ratchet_has_not_rotted(self):
        """A fixed orphan must be removed from the list, or the list stops
        describing the code."""
        orphans = {key for key in self.reads if key not in self.writes}
        stale = set(KNOWN_ORPHAN_METADATA_READS) - orphans
        self.assertEqual(
            stale,
            set(),
            f"KNOWN_ORPHAN_METADATA_READS lists keys that now have writers: "
            f"{sorted(stale)}. Remove them from the ratchet.",
        )


# ===========================================================================
# 2 + 3. The normalised payment dict, and the branch production really takes
# ===========================================================================

# A canonical Mollie payment payload, camelCase exactly as the API returns it.
# Fed to the REAL SDK object rather than to a hand-written fake, so this test
# cannot drift onto a branch production never takes (defect class 3).
CANONICAL_MOLLIE_PAYMENT = {
    "resource": "payment",
    "id": "tr_INVARIANTTEST",
    "mode": "test",
    "status": "paid",
    "amount": {"value": "25.00", "currency": "EUR"},
    "description": "Donation INVARIANT-TEST",
    "method": "ideal",
    "createdAt": "2025-04-10T09:00:00+00:00",
    "paidAt": "2025-04-10T09:00:05+00:00",
    "sequenceType": "first",
    "customerId": "cst_INVARIANTTEST",
    "subscriptionId": "sub_INVARIANTTEST",
    # Carried so the branch-parity tests below compare a VALUE and not two Nones:
    # without it, a dict branch that mistakenly read "mandate_id" instead of
    # "mandateId" would agree with the object branch on None and pass.
    "mandateId": "mdt_INVARIANTTEST",
    "metadata": {"donation_id": "DON-INVARIANT", "subscription_setup": "true"},
}


def _real_sdk_payment():
    """Construct a genuine ``mollie.api.objects.Payment`` offline.

    ``ObjectBase.__init__(data, client)`` only wraps the dict -- no HTTP -- so
    this is the real production class with no network involved.
    """
    from mollie.api.objects.payment import Payment

    return Payment(dict(CANONICAL_MOLLIE_PAYMENT), None)


def _object_style_payment():
    """A payment exposed as attributes only (no dict interface).

    This is the shape the SDK would have if ``ObjectBase`` stopped subclassing
    dict, and the shape every fake in this repo used to have. It exists so the
    two branches of ``_fetch_payment_from_mollie`` can be compared.
    """
    return SimpleNamespace(
        id=CANONICAL_MOLLIE_PAYMENT["id"],
        status=CANONICAL_MOLLIE_PAYMENT["status"],
        amount=dict(CANONICAL_MOLLIE_PAYMENT["amount"]),
        description=CANONICAL_MOLLIE_PAYMENT["description"],
        method=CANONICAL_MOLLIE_PAYMENT["method"],
        created_at=CANONICAL_MOLLIE_PAYMENT["createdAt"],
        paid_at=CANONICAL_MOLLIE_PAYMENT["paidAt"],
        sequence_type=CANONICAL_MOLLIE_PAYMENT["sequenceType"],
        customer_id=CANONICAL_MOLLIE_PAYMENT["customerId"],
        subscription_id=CANONICAL_MOLLIE_PAYMENT["subscriptionId"],
        mandate_id=CANONICAL_MOLLIE_PAYMENT["mandateId"],
        metadata=dict(CANONICAL_MOLLIE_PAYMENT["metadata"]),
    )


class _FakeSDKClient:
    """Stand-in for the Mollie SDK Client -- the HTTP boundary, nothing else."""

    def __init__(self, payment):
        self.payments = SimpleNamespace(get=lambda payment_id: payment)

    def set_api_key(self, _key):
        return None


def _payment_data_reader_keys():
    """Every string key read off a ``payment_data`` dict inside
    ``UnifiedWebhookWrapperService``.

    Extracted from the source rather than hand-listed, so it cannot rot: a
    reader added tomorrow is picked up without anyone remembering to update a
    list.
    """
    path = os.path.join(
        PACKAGE_ROOT,
        "verenigingen_payments",
        "mollie",
        "services",
        "webhook_wrapper_service_unified.py",
    )
    tree = _parse_module(path)
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "UnifiedWebhookWrapperService"
    )

    keys = {}
    for node in ast.walk(class_node):
        target = None
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "payment_data"
        ):
            target = _const_str(node.args[0])
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "payment_data"
            and isinstance(node.ctx, ast.Load)
        ):
            target = _const_str(node.slice)
        if target:
            keys.setdefault(target, []).append(node.lineno)
    return keys


class TestNormalisedPaymentDictContract(EnhancedTestCase):
    """Defect classes 2 and 3, on ``_fetch_payment_from_mollie``.

    That method is a hand-written whitelist, duplicated across two branches, and
    the only thing standing between Mollie's camelCase payload and every reader
    downstream. Dropping a key from it is silent: readers see ``None`` forever.
    """

    def setUp(self):
        super().setUp()
        self.service = object.__new__(UnifiedWebhookWrapperService)
        self.service.logger = frappe.logger("test_mollie_invariants")
        self.service._debug_mode = False

    def _normalise(self, payment):
        with patch(
            "verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings."
            "MollieSettings.get_mollie_client",
            return_value=_FakeSDKClient(payment),
        ):
            return self.service._fetch_payment_from_mollie(CANONICAL_MOLLIE_PAYMENT["id"])

    # -------------------------------------------------- defect class 3
    def test_the_real_sdk_payment_is_a_dict_so_production_takes_the_dict_branch(self):
        """Pins WHICH branch production runs.

        ``_fetch_payment_from_mollie`` switches on ``isinstance(payment, dict)``.
        A real Mollie Payment subclasses dict, so the camelCase branch is the
        live one and the attribute branch is dead in production. Every fake in
        this repo used to be a plain object, so the live branch's key names --
        ``sequenceType``/``customerId``/``subscriptionId`` -- were covered by
        nothing at all. If an SDK upgrade changes this, the coverage silently
        swaps branches again, so assert it directly.
        """
        from mollie.api.objects.payment import Payment

        self.assertTrue(
            issubclass(Payment, dict),
            f"mollie.api.objects.Payment no longer subclasses dict (MRO: {Payment.__mro__}). "
            "_fetch_payment_from_mollie's isinstance(payment, dict) branch is now the "
            "DEAD one and the attribute branch is live -- the camelCase key handling "
            "this suite exercises no longer reflects production.",
        )
        self.assertIsInstance(_real_sdk_payment(), dict)

    def test_camelcase_keys_survive_normalisation_from_a_real_sdk_payment(self):
        """The #343 instance, driven through the actual SDK class.

        ``sequenceType``/``customerId``/``subscriptionId`` were absent from the
        whitelist, so the donation Recurring/One-time stamp, the donor's
        subscription id and the history entry type all saw None on every payment.
        """
        normalised = self._normalise(_real_sdk_payment())
        self.assertEqual(normalised["sequence_type"], "first")
        self.assertEqual(normalised["customer_id"], "cst_INVARIANTTEST")
        self.assertEqual(normalised["subscription_id"], "sub_INVARIANTTEST")
        # Same defect, found later: a recurring charge's Donation stores
        # mollie_mandate_id, and this dict is what the webhook hands the booking
        # path, so the missing key made it None on every charge.
        self.assertEqual(normalised["mandate_id"], "mdt_INVARIANTTEST")
        self.assertEqual(normalised["paid_at"], "2025-04-10T09:00:05+00:00")
        self.assertEqual(normalised["created_at"], "2025-04-10T09:00:00+00:00")
        self.assertEqual(normalised["amount"], {"value": "25.00", "currency": "EUR"})
        self.assertEqual(normalised["metadata"]["subscription_setup"], "true")

    # -------------------------------------------------- defect class 2
    def test_both_branches_emit_identical_key_sets(self):
        """The whitelist is written twice; the two copies must not drift.

        A key added to one branch and forgotten in the other is invisible until
        the day the other branch runs. Comparing the key SETS closes the whole
        class -- it does not matter which key someone forgets next.
        """
        dict_branch = self._normalise(_real_sdk_payment())
        object_branch = self._normalise(_object_style_payment())
        self.assertEqual(
            set(dict_branch),
            set(object_branch),
            "The dict and object branches of _fetch_payment_from_mollie emit "
            "different keys.\n"
            f"  only in dict branch:   {sorted(set(dict_branch) - set(object_branch))}\n"
            f"  only in object branch: {sorted(set(object_branch) - set(dict_branch))}\n"
            "Both branches produce the SAME normalised payment for downstream "
            "readers; a key present in only one is None whenever the other runs.",
        )

    def test_both_branches_emit_identical_values(self):
        """Same keys is not enough -- the camelCase lookups must actually land.

        A dict branch that reads ``payment.get("sequence_type")`` on a Mollie
        payload emits the right KEY with a None VALUE, which the key-set test
        above cannot see.
        """
        dict_branch = self._normalise(_real_sdk_payment())
        object_branch = self._normalise(_object_style_payment())
        self.assertEqual(
            dict_branch,
            object_branch,
            "The two branches of _fetch_payment_from_mollie disagree on values "
            "for the same Mollie payment. Production only ever runs the dict "
            "branch, so a wrong lookup there is invisible to any test that "
            "exercises the object branch.",
        )

    def test_every_key_read_from_payment_data_is_produced(self):
        """No reader may ask for a key the normaliser does not emit.

        This is the defect-4 shape localised to the one dict where both ends are
        in this file: ``_fetch_payment_from_mollie`` is the sole producer, and
        ``UnifiedWebhookWrapperService`` is the consumer. The reader list is
        extracted from the source, so it cannot go stale.
        """
        produced = set(self._normalise(_real_sdk_payment()))
        # No hand-carved exemptions here. `subscription_id` IS produced by the
        # normaliser (that was the #343 fix); adding it manually would keep this
        # test green if someone removed it again -- re-opening the exact hole the
        # test exists to close, in the module that argues exemptions rot.
        readers = _payment_data_reader_keys()
        self.assertTrue(
            readers,
            "CONTROL: found no payment_data reads at all -- the extractor is "
            "broken and this assertion is vacuous.",
        )
        missing = {key: lines for key, lines in readers.items() if key not in produced}
        self.assertEqual(
            missing,
            {},
            "UnifiedWebhookWrapperService reads key(s) that "
            "_fetch_payment_from_mollie never produces:\n"
            + "\n".join(
                f"  payment_data[{key!r}] at line(s) {lines}" for key, lines in sorted(missing.items())
            )
            + f"\n\nProduced keys: {sorted(produced)}.\n"
            "Every such reader sees None on every payment, forever. This is "
            "issue #343.",
        )


# ===========================================================================
# 4b. The donate form's own string-key boundary -- the original #341 surface
# ===========================================================================
DONATE_TEMPLATE = os.path.join(PACKAGE_ROOT, "templates", "pages", "donate.html")
DONATE_JS = os.path.join(PACKAGE_ROOT, "public", "js", "donation_form.js")
DONATION_READER_FILES = (
    os.path.join(PACKAGE_ROOT, "services", "donation", "public_donation_service.py"),
    os.path.join(PACKAGE_ROOT, "templates", "pages", "donate.py"),
)

# Keys the server reads from form_data that the browser is not expected to post:
# the service synthesises them internally before handing form_data onward.
FORM_DATA_NOT_POSTED_BY_THE_BROWSER = frozenset(
    {
        # built by process_mollie_payment / process_payment_method themselves
        "amount",
        "currency",
        "return_url",
        "description",
        "donor_email",
        "donor_name",
        "locale",
        "metadata",
        "method",
        "sequenceType",
        "subscription_interval",
        "success_url",
        "cancel_url",
    }
)

# The known orphan. Ratcheted rather than fixed here because removing a reader is
# a behaviour change, not a test change -- see #341.
KNOWN_ORPHAN_FORM_DATA_READS = {
    # #341: the donate form posts `subscription_interval`; nothing anywhere
    # posts `recurring_interval`. The fix for #341 put it behind an `or` rather
    # than deleting it, so the dead read is still here.
    "recurring_interval": "services/donation/public_donation_service.py:210,623",
    # These three are read as FALLBACKS behind the key the form really posts
    # (donor_email / donor_name). Reading them alone was a live bug -- the Mollie
    # customer got an empty email and an empty name on every recurring donation --
    # fixed in this branch; the fallback is kept for non-form callers of the
    # public submit_donation endpoint.
    "email": "fallback behind donor_email",
    "first_name": "fallback behind donor_name",
    "last_name": "fallback behind donor_name",
    # Read by the PaymentHook (non-Mollie) branch, which serves SEPA/Bank
    # Transfer. donate.html does not collect them today, so those branches are
    # unreachable FROM THIS FORM -- but submit_donation is a public endpoint and
    # other callers may supply them. Listed rather than deleted for that reason.
    "donor_iban": "PaymentHook payer_info (SEPA); not collected by donate.html",
    "account_holder": "PaymentHook payer_info (SEPA); not collected by donate.html",
    "is_recurring": "PaymentHook recurring flag; the form posts donation_status instead",
    "payment_method_preference": "Mollie method hint; not collected by donate.html",
    "anbi_agreement_number": "ANBI fields; not collected by donate.html",
    "anbi_agreement_date": "ANBI fields; not collected by donate.html",
}


def _read_text(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _donate_form_writers():
    """Keys the browser actually posts, read from the two files that post them.

    Not AST-parseable, which is exactly why this boundary went unchecked and
    why #341 shipped. A regex over two known files is cruder than an AST walk
    and still strictly better than no check at all.
    """
    writers = set()
    template = _read_text(DONATE_TEMPLATE)
    writers |= set(re.findall(r"""\bname=["']([A-Za-z_][\w]*)["']""", template))
    writers |= set(re.findall(r"""\bid=["']([A-Za-z_][\w]*)["']""", template))
    js = _read_text(DONATE_JS)
    writers |= set(re.findall(r"""formData\.([A-Za-z_][\w]*)""", js))
    writers |= set(re.findall(r"""formData\[["']([A-Za-z_][\w]*)["']\]""", js))
    writers |= set(re.findall(r"""getElementById\(["']([A-Za-z_][\w]*)["']\)""", js))
    writers |= set(re.findall(r"""["']([A-Za-z_][\w]*)["']\s*:""", js))
    return writers


class _FormDataReadVisitor(_EnclosingFunctionVisitor):
    """Collect ``form_data.get("key")`` / ``form_data["key"]`` reads."""

    def __init__(self, rel):
        super().__init__(rel)
        self.reads = {}

    def _record(self, key, lineno):
        self.reads.setdefault(key, []).append(f"{self.rel}:{lineno}")

    def visit_Call(self, node):
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "get"
            and isinstance(func.value, ast.Name)
            and func.value.id == "form_data"
            and node.args
        ):
            key = _const_str(node.args[0])
            if key:
                self._record(key, node.lineno)
        self.generic_visit(node)

    def visit_Subscript(self, node):
        if isinstance(node.value, ast.Name) and node.value.id == "form_data":
            key = _const_str(node.slice)
            if key:
                self._record(key, node.lineno)
        self.generic_visit(node)


class TestDonateFormKeysHaveWriters(unittest.TestCase):
    """Defect class 4, applied to the boundary that actually shipped the bug.

    #341: ``form_data["recurring_interval"]`` had two readers and zero writers,
    because the form posts ``subscription_interval``. Every recurring donation
    was billed monthly whatever the donor chose. No compiler, validator or test
    saw it -- a reviewer did.
    """

    @classmethod
    def setUpClass(cls):
        cls.writers = _donate_form_writers()
        cls.reads = {}
        for path in DONATION_READER_FILES:
            rel = os.path.relpath(path, PACKAGE_ROOT).replace(os.sep, "/")
            visitor = _FormDataReadVisitor(rel)
            visitor.visit(_parse_module(path))
            for key, sites in visitor.reads.items():
                cls.reads.setdefault(key, []).extend(sites)

    def test_the_scanner_sees_both_ends_of_the_boundary(self):
        """CONTROL. Pin the key from #341 itself: the one the form really posts
        and the server really reads. If either half of the scan silently found
        nothing, the orphan test below would be vacuous."""
        self.assertIn(
            "subscription_interval",
            self.writers,
            f"Scanner found no writer for subscription_interval in donate.html / "
            f"donation_form.js; writers={sorted(self.writers)[:40]}",
        )
        self.assertIn(
            "subscription_interval",
            self.reads,
            f"Scanner found no form_data reader for subscription_interval; " f"readers={sorted(self.reads)}",
        )

    def test_no_new_form_data_key_is_read_without_a_writer(self):
        orphans = {
            key: sites
            for key, sites in self.reads.items()
            if key not in self.writers and key not in FORM_DATA_NOT_POSTED_BY_THE_BROWSER
        }
        new = set(orphans) - set(KNOWN_ORPHAN_FORM_DATA_READS)
        self.assertEqual(
            new,
            set(),
            "The donation code reads form_data key(s) that nothing in donate.html "
            "or donation_form.js ever posts:\n"
            + "\n".join(f"  {key!r} read at {orphans[key]}" for key in sorted(new))
            + "\n\nEvery such reader is permanently dead -- the value is always the "
            "default. This is #341 exactly: a string key crossing the browser/server "
            "boundary has no compiler. Either post the key, or delete the reader.",
        )

    def test_the_form_data_orphan_ratchet_has_not_rotted(self):
        fixed = {key for key in KNOWN_ORPHAN_FORM_DATA_READS if key in self.writers or key not in self.reads}
        self.assertEqual(
            fixed,
            set(),
            "KNOWN_ORPHAN_FORM_DATA_READS lists key(s) that now have a writer, or "
            f"are no longer read: {sorted(fixed)}. Remove them so the ratchet keeps "
            "describing the code.",
        )


# ===========================================================================
# 5. Unconditional network calls on a path that needs none
# ===========================================================================
class _MollieWasTouched(BaseException):
    """Deliberately NOT an Exception subclass.

    This codebase's recurring defect is over-broad handlers. If the sentinel
    raised `AssertionError`, a newly added `_fetch_payment_from_mollie()` wrapped
    in the `try/except Exception: log; continue` this repo is full of would
    swallow it and leave the test green -- the invariant would report success
    precisely when it had been violated. Deriving from BaseException makes it
    unswallowable by any handler short of a bare `except:`.
    """


class _ExplodingMollieClient:
    """Any attempt to reach Mollie from this path is a defect, so make it loud."""

    MESSAGE = "_handle_fully_processed_payment must not fetch the payment from Mollie"

    def __getattr__(self, name):
        raise _MollieWasTouched(f"{self.MESSAGE} (tried to use client.{name})")


class TestFullyProcessedPathDoesNotFetch(EnhancedTestCase):
    """Defect class 5.

    ``_handle_fully_processed_payment`` handles refunds and chargebacks for a
    payment whose donation work is already done. It needs no payment data. An
    earlier attempt to retry subscription activation here added an unconditional
    ``_fetch_payment_from_mollie()`` -- which RAISES on any failure -- and so
    made refund handling depend on a Mollie round-trip that path never needed.
    That was caught only by a cross-module control run.

    The whole Mollie client is wired to explode here, so the invariant is
    "this path performs NO Mollie call", not "this path performs no *particular*
    Mollie call".
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._orig_company = frappe.db.get_single_value("Verenigingen Settings", "company")
        cls._orig_donation_account = frappe.db.get_single_value(
            "Verenigingen Settings", "unrestricted_donation_account"
        )
        cls._orig_ms_clearing = frappe.db.get_single_value("Mollie Settings", "mollie_clearing_account")
        cls._orig_ms_bank = frappe.db.get_single_value("Mollie Settings", "mollie_bank_account")
        cls._orig_ms_test_mode = frappe.db.get_single_value("Mollie Settings", "test_mode")

    @classmethod
    def tearDownClass(cls):
        frappe.db.set_single_value(
            "Verenigingen Settings", "unrestricted_donation_account", cls._orig_donation_account
        )
        frappe.db.set_single_value("Verenigingen Settings", "company", cls._orig_company)
        frappe.db.set_single_value("Mollie Settings", "mollie_clearing_account", cls._orig_ms_clearing)
        frappe.db.set_single_value("Mollie Settings", "mollie_bank_account", cls._orig_ms_bank)
        frappe.db.set_single_value("Mollie Settings", "test_mode", cls._orig_ms_test_mode)
        frappe.db.commit()
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
            MollieConfigurationService,
        )

        MollieConfigurationService.clear_cache()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.service = UnifiedWebhookWrapperService()
        frappe.db.set_single_value("Verenigingen Settings", "company", COMPANY)

        self.clearing_account = self._setup_clearing_account()
        self.bank_account = self._setup_bank_account(self.clearing_account)
        self.income_account = self._setup_income_account()
        self._setup_mollie_settings(self.clearing_account)

        self.payment_id = f"tr_{frappe.generate_hash(length=12)}"
        self.amount = 25.00
        self.donation_name = self._setup_donation(self._setup_donor(), self.payment_id, self.amount)

    # ------------------------------------------------------------------ setup
    def _setup_clearing_account(self):
        name = frappe.get_value(
            "Account", {"company": COMPANY, "account_name": "Mollie Clearing Invariant Test"}, "name"
        )
        if name:
            return name
        parent = frappe.get_value(
            "Account", {"company": COMPANY, "account_type": "Bank", "is_group": 1}, "name"
        ) or frappe.get_value("Account", {"company": COMPANY, "is_group": 1}, "name")
        account = frappe.new_doc("Account")
        account.account_name = "Mollie Clearing Invariant Test"
        account.company = COMPANY
        account.parent_account = parent
        account.account_type = "Bank"
        account.account_currency = frappe.get_value("Company", COMPANY, "default_currency")
        account.insert(ignore_permissions=True)
        return account.name

    def _setup_bank_account(self, gl_account):
        existing = frappe.get_value("Bank Account", {"account": gl_account}, "name")
        if existing:
            return existing
        bank_name = frappe.get_value("Bank", {}, "name")
        if not bank_name:
            bank = frappe.new_doc("Bank")
            bank.bank_name = "Invariant Test Bank"
            bank.insert(ignore_permissions=True)
            bank_name = bank.name
        bank_account = frappe.new_doc("Bank Account")
        bank_account.account_name = "Mollie Invariant Test"
        bank_account.bank = bank_name
        bank_account.account = gl_account
        bank_account.company = COMPANY
        bank_account.is_company_account = 1
        bank_account.insert(ignore_permissions=True)
        return bank_account.name

    def _setup_income_account(self):
        name = frappe.get_value(
            "Account", {"company": COMPANY, "account_name": "Donation Income Invariant Test"}, "name"
        )
        if not name:
            parent = frappe.get_value(
                "Account", {"company": COMPANY, "root_type": "Income", "is_group": 1}, "name"
            )
            account = frappe.new_doc("Account")
            account.account_name = "Donation Income Invariant Test"
            account.company = COMPANY
            account.parent_account = parent
            account.account_type = "Income Account"
            account.account_currency = frappe.get_value("Company", COMPANY, "default_currency")
            account.insert(ignore_permissions=True)
            name = account.name
        frappe.db.set_single_value("Verenigingen Settings", "unrestricted_donation_account", name)
        return name

    def _setup_mollie_settings(self, clearing_account):
        frappe.db.set_single_value("Mollie Settings", "mollie_clearing_account", clearing_account)
        frappe.db.set_single_value("Mollie Settings", "mollie_bank_account", clearing_account)
        frappe.db.set_single_value("Mollie Settings", "test_mode", 1)
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
            MollieConfigurationService,
        )

        MollieConfigurationService.clear_cache()

    def _setup_donor(self):
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Invariant Donor {frappe.generate_hash(length=6)}"
        donor.donor_email = f"invariant.{frappe.generate_hash(length=6)}@example.org"
        donor.donor_type = "Individual"
        donor.preferred_communication_method = "Email"
        donor.flags.ignore_validate = True
        donor.insert(ignore_permissions=True)
        self.track_test_record("Donor", donor.name)
        return donor.name

    def _setup_donation(self, donor_name, payment_id, amount):
        donation = frappe.new_doc("Donation")
        donation.donor = donor_name
        donation.donation_date = "2025-04-10"
        donation.amount = amount
        donation.mode_of_payment = "Mollie"
        donation.status = "One-time"
        donation.company = COMPANY
        donation.payment_id = payment_id
        donation.paid = 1
        donation.flags.ignore_validate = True
        donation.insert(ignore_permissions=True)
        self.track_test_record("Donation", donation.name)
        return donation.name

    def _fully_processed_state(self, refunds):
        """The state the unified idempotency manager reports for a payment whose
        donation work is complete but whose refunds are not yet booked."""
        state = PaymentIdempotencyCheckResult(self.payment_id)
        state.payment_entry_exists = True
        state.payment_entry_name = "JV-INVARIANT-TEST"
        state.payment_history_updated = True
        state.donation_status_updated = True
        state.pending_refunds = refunds
        return state

    # ------------------------------------------------------------------ tests
    def test_refund_work_completes_with_the_mollie_client_unreachable(self):
        """The real refund chain must run end to end without any Mollie call.

        Note this asserts the refund actually SUCCEEDED, not merely that nothing
        raised: a misconfigured fixture would make ``_process_pending_refunds``
        bail early and the test would otherwise pass while proving nothing.
        """
        refund_id = f"re_{frappe.generate_hash(length=10)}"
        state = self._fully_processed_state(
            [{"refund_id": refund_id, "amount": 5.00, "refund_date": "2025-04-12"}]
        )

        with patch(
            "verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings."
            "MollieSettings.get_mollie_client",
            return_value=_ExplodingMollieClient(),
        ):
            with self.set_user("Administrator"):
                result = self.service._handle_fully_processed_payment(self.payment_id, state, 0.0)

        self.assertEqual(
            result["status"],
            "success",
            "Refund handling on the already-processed path must not depend on a "
            f"Mollie payment fetch. Result: {result}",
        )
        refund_results = result.get("refund_processing") or []
        self.assertEqual(len(refund_results), 1, f"Expected one refund result, got {refund_results}")
        self.assertEqual(
            refund_results[0]["status"],
            "success",
            f"The refund must actually have been booked, not skipped: {refund_results[0]}",
        )
        self.assertTrue(
            frappe.db.exists(
                "Bank Transaction", {"reference_number": f"{self.payment_id}_refund_{refund_id}"}
            ),
            "A refund Bank Transaction should have been created without touching Mollie",
        )

    def test_the_exploding_client_really_would_be_noticed(self):
        """CONTROL for the test above.

        If ``_ExplodingMollieClient`` were inert -- or the patch target wrong --
        the test above would pass no matter what the handler did. Prove the wiring
        by taking the same client down the path that DOES fetch.
        """
        with patch(
            "verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings."
            "MollieSettings.get_mollie_client",
            return_value=_ExplodingMollieClient(),
        ):
            # BaseException, not Exception: _fetch_payment_from_mollie wraps
            # failures in MolliePaymentError, but the sentinel is deliberately
            # unswallowable, so catch the broadest thing.
            with self.assertRaises(BaseException) as caught:
                self.service._fetch_payment_from_mollie(self.payment_id)
        self.assertIn(
            _ExplodingMollieClient.MESSAGE,
            str(caught.exception),
            "The exploding Mollie client is not actually wired into the fetch path, "
            "so the no-fetch assertion above proves nothing.",
        )
