"""
#1417 structural ratchet: every log_security_event() call site must use a
valid event_type.

log_security_event(event_type, ...) (verenigingen/utils/security/audit_logging.py)
passes event_type straight through to the API Audit Log doctype's event_type
Select field (or, for the SEPA-specific subset, routes to SEPA Audit Log
instead -- see SEPAAuditLogger.SEPA_EVENT_TYPES / _is_sepa_event). _store_audit_event
catches the resulting ValidationError with its own `except Exception` and only
logs it via frappe.log_error -- so a literal event_type outside both of those
sets silently drops the audit row from the database entirely, with nothing
raised to the caller. #1417 found 14 such literals across what its own census
called "6 production files"; only 3 of those files actually call THIS
function -- the other 3 (document_portal_service.py's private
`_log_security_event`, PaymentLogger.log_security_event, and
WebhookSecurityManager.log_security_event) are same-named but unrelated
methods that never reach _store_audit_event, which is why they are
deliberately excluded below rather than "fixed".

This walks every production .py file under the verenigingen package
(excluding tests/) and statically resolves the event_type argument of every
call that actually reaches
verenigingen.utils.security.audit_logging.log_security_event. Two call shapes
are matched, both by which name/module is actually bound -- never by
substring, which is exactly what let #1417's own census over-count:

1. A bare `log_security_event(...)` call, where that exact name is bound via
   `from verenigingen.utils.security.audit_logging import log_security_event
   [as alias]` (module-level or local to a function; several real call sites
   import it lazily).
2. A module-attribute call, `audit_logging.log_security_event(...)`, where
   `audit_logging` resolves to the audit_logging module itself -- via
   `from verenigingen.utils.security import audit_logging [as alias]`,
   `import verenigingen.utils.security.audit_logging as alias`, or the fully
   qualified dotted expression
   `verenigingen.utils.security.audit_logging.log_security_event(...)`
   written out after a bare `import verenigingen.utils.security.audit_logging`.

An attribute call is matched ONLY when its base resolves to this exact
module. `self._log_security_event(...)`, `PaymentLogger.log_security_event(...)`
and `WebhookSecurityManager.log_security_event(...)` are same-named but
genuinely different functions -- their base (`self`, `PaymentLogger`,
`security_manager`) never resolves to `audit_logging`, so they are correctly
left unmatched, not because "attribute calls are unrelated" in general.
"""

import ast
import json
import textwrap
import unittest
from pathlib import Path

from verenigingen.utils.security.audit_logging import SEPAAuditLogger
from verenigingen.utils.security.types import AuditEventType

# verenigingen/tests/security/<this file> -> parents[2] is the inner
# `verenigingen` package (the app's Python module root), matching the layout
# used by test_except_order_validator.py's APP_ROOT convention one level up.
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DOCTYPE_JSON = PACKAGE_ROOT / "verenigingen" / "doctype" / "api_audit_log" / "api_audit_log.json"

TARGET_MODULE = "verenigingen.utils.security.audit_logging"
TARGET_FUNC = "log_security_event"

_ENUM_VALUES = {member.name: member.value for member in AuditEventType}


def _load_valid_event_types():
    """Ground truth: read the Select options directly from the DocType JSON
    (never hand-copied) and union in the SEPA event types, which route to a
    different doctype entirely and are equally valid arguments to
    log_security_event()."""
    doctype = json.loads(DOCTYPE_JSON.read_text(encoding="utf-8"))
    for field in doctype["fields"]:
        if field.get("fieldname") == "event_type":
            select_options = {line for line in field["options"].splitlines() if line}
            break
    else:
        raise AssertionError("API Audit Log.event_type field not found in its DocType JSON")
    return select_options | set(SEPAAuditLogger.SEPA_EVENT_TYPES)


def _resolve_event_type_literal(node):
    """Best-effort static resolution of an event_type expression to its
    string value. Returns None for anything that isn't a plain string
    literal or a recognised AuditEventType enum access (e.g. a runtime
    variable) -- such call sites are skipped, not failed, since this is a
    static (not dynamic) check."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Attribute):
        # AuditEventType.X.value
        if node.attr == "value" and isinstance(node.value, ast.Attribute):
            base = node.value
            if isinstance(base.value, ast.Name) and base.value.id == "AuditEventType":
                return _ENUM_VALUES.get(base.attr)
        # AuditEventType.X passed bare -- log_event() coerces enums via .value
        elif isinstance(node.value, ast.Name) and node.value.id == "AuditEventType":
            return _ENUM_VALUES.get(node.attr)
    return None


def _bound_names(tree, module, target):
    """Every local name `target` is bound to via
    `from module import target [as alias]`, anywhere in the file (module
    level or inside a function body -- several real call sites import
    log_security_event lazily)."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            for alias in node.names:
                if alias.name == target:
                    names.add(alias.asname or alias.name)
    return names


def _module_aliases(tree, target_module):
    """Every local name bound to the whole `target_module` (not one function
    inside it), via `import target_module as alias` or
    `from <parent> import <leaf> [as alias]` where `<parent>.<leaf> ==
    target_module`. Deliberately excludes a bare `import target_module`
    (no `as`) -- that binds only the top-level package name (e.g.
    `verenigingen`), which would false-match any unrelated
    `verenigingen.log_security_event(...)`; that unaliased shape is instead
    matched by `_dotted_name` against the full literal dotted path."""
    aliases = set()
    parent, _, leaf = target_module.rpartition(".")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == target_module and alias.asname:
                    aliases.add(alias.asname)
        elif isinstance(node, ast.ImportFrom) and node.module == parent:
            for alias in node.names:
                if alias.name == leaf:
                    aliases.add(alias.asname or alias.name)
    return aliases


def _dotted_name(node):
    """Reconstruct a plain dotted-attribute chain (`a.b.c`) back to a string,
    or None if `node` isn't purely Name/Attribute nodes."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _event_type_arg(call):
    for kw in call.keywords:
        if kw.arg == "event_type":
            return kw.value
    if call.args:
        return call.args[0]
    return None


def _find_target_calls(tree):
    """Calls that reach the real log_security_event, in either of two shapes:

    - bare `name(...)` where `name` is bound to it via an ImportFrom in this
      file (`_bound_names`);
    - `base.log_security_event(...)` where `base` resolves to the
      audit_logging module itself (`_module_aliases`), or the full literal
      dotted expression `verenigingen.utils.security.audit_logging.
      log_security_event(...)` (`_dotted_name`).

    Deliberately does NOT match an attribute call whose base is anything
    else (`self._log_security_event(...)`,
    `PaymentLogger.log_security_event(...)`,
    `security_manager.log_security_event(...)`) -- those bases never resolve
    to the audit_logging module, so they are different, same-named
    functions, not this one.
    """
    bound_names = _bound_names(tree, TARGET_MODULE, TARGET_FUNC)
    module_aliases = _module_aliases(tree, TARGET_MODULE)
    full_dotted_target = f"{TARGET_MODULE}.{TARGET_FUNC}"

    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in bound_names:
            calls.append(node)
        elif isinstance(func, ast.Attribute) and func.attr == TARGET_FUNC:
            if isinstance(func.value, ast.Name) and func.value.id in module_aliases:
                calls.append(node)
            elif _dotted_name(func) == full_dotted_target:
                calls.append(node)
    return calls


def _scan_package():
    """Returns (offenders, unresolved, total_calls_found).

    offenders: (relpath, lineno, literal) for a resolved event_type NOT in
    the valid set.
    unresolved: (relpath, lineno) where the argument could not be statically
    resolved (dynamic expression) -- reported for visibility, not failed.
    """
    offenders = []
    unresolved = []
    total_calls = 0

    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        rel = path.relative_to(PACKAGE_ROOT)
        if "tests" in rel.parts or "node_modules" in rel.parts:
            continue

        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(rel))
        except SyntaxError:
            continue

        for call in _find_target_calls(tree):
            total_calls += 1
            arg = _event_type_arg(call)
            lineno = getattr(call, "lineno", "?")
            if arg is None:
                unresolved.append((str(rel), lineno))
                continue
            literal = _resolve_event_type_literal(arg)
            if literal is None:
                unresolved.append((str(rel), lineno))
                continue
            if literal not in _load_valid_event_types():
                offenders.append((str(rel), lineno, literal))

    return offenders, unresolved, total_calls


class TestLogSecurityEventTypesAreValidSelectOptions(unittest.TestCase):
    def test_every_resolvable_call_site_uses_a_valid_event_type(self):
        offenders, unresolved, total_calls = _scan_package()

        # Control: prove the scan is actually walking real files and matching
        # real calls, not silently finding nothing (see #1417's own
        # over-broad census for what an unanchored scan looks like). As of
        # this fix there are at least 20 genuine call sites across
        # membership_application_review.py, background_approval_api.py,
        # member_duplicate_detection_service.py, security_setup.py,
        # personal_details.py, authorization.py and audit_logging.py itself.
        self.assertGreaterEqual(
            total_calls,
            20,
            f"expected to find at least 20 real log_security_event() call sites, found "
            f"{total_calls} (unresolved: {unresolved}); the scan may no longer be matching "
            "real call sites",
        )

        self.assertEqual(
            [],
            offenders,
            "log_security_event() called with an event_type that is not a valid API Audit "
            f"Log.event_type Select option (nor a SEPA event type): {offenders}",
        )


class TestFindTargetCallsMatchesEveryRealCallShape(unittest.TestCase):
    """Planted-case coverage for `_find_target_calls`/`_dotted_name`/
    `_module_aliases` themselves, independent of what the real tree currently
    contains. `_scan_package` alone would stay green forever if a NEW call
    shape were introduced and simply never matched -- these snippets pin the
    matcher's behaviour directly, including the module-attribute shape a
    review of this file's first version flagged as an unhandled blind spot.
    """

    def _calls_and_literals(self, source):
        tree = ast.parse(textwrap.dedent(source))
        literals = []
        for call in _find_target_calls(tree):
            arg = _event_type_arg(call)
            literals.append(_resolve_event_type_literal(arg) if arg is not None else None)
        return literals

    def test_bare_call_via_direct_import(self):
        literals = self._calls_and_literals(
            """
            from verenigingen.utils.security.audit_logging import log_security_event

            def f():
                log_security_event("bad_literal", {}, severity="error")
            """
        )
        self.assertEqual(["bad_literal"], literals)

    def test_bare_call_via_aliased_direct_import(self):
        literals = self._calls_and_literals(
            """
            from verenigingen.utils.security.audit_logging import log_security_event as lse

            def f():
                lse("bad_literal", {})
            """
        )
        self.assertEqual(["bad_literal"], literals)

    def test_attribute_call_via_submodule_import(self):
        """The blind spot flagged in review: `from ... import audit_logging`
        then `audit_logging.log_security_event(...)`."""
        literals = self._calls_and_literals(
            """
            from verenigingen.utils.security import audit_logging

            def f():
                audit_logging.log_security_event("bad_literal", {})
            """
        )
        self.assertEqual(["bad_literal"], literals)

    def test_attribute_call_via_aliased_submodule_import(self):
        literals = self._calls_and_literals(
            """
            from verenigingen.utils.security import audit_logging as al

            def f():
                al.log_security_event("bad_literal", {})
            """
        )
        self.assertEqual(["bad_literal"], literals)

    def test_attribute_call_via_aliased_dotted_import(self):
        literals = self._calls_and_literals(
            """
            import verenigingen.utils.security.audit_logging as aal

            def f():
                aal.log_security_event("bad_literal", {})
            """
        )
        self.assertEqual(["bad_literal"], literals)

    def test_attribute_call_via_unaliased_dotted_import(self):
        literals = self._calls_and_literals(
            """
            import verenigingen.utils.security.audit_logging

            def f():
                verenigingen.utils.security.audit_logging.log_security_event("bad_literal", {})
            """
        )
        self.assertEqual(["bad_literal"], literals)

    def test_unrelated_same_named_method_on_self_is_not_matched(self):
        """document_portal_service.py's actual shape: a private method of the
        same name, no audit_logging import anywhere in the file."""
        literals = self._calls_and_literals(
            """
            class DocumentPortalService:
                def _log_security_event(self, event_type, details=None):
                    pass

                def f(self):
                    self._log_security_event("upload_failed", {})
            """
        )
        self.assertEqual([], literals)

    def test_unrelated_same_named_staticmethod_call_is_not_matched(self):
        """payment_services/logging_utils.py's actual shape: an unrelated
        class attribute call, no audit_logging import anywhere in the file."""
        literals = self._calls_and_literals(
            """
            class PaymentLogger:
                @staticmethod
                def log_security_event(event_type, details, severity="warning"):
                    pass

            def f():
                PaymentLogger.log_security_event("concurrent_refund_detected", {})
            """
        )
        self.assertEqual([], literals)

    def test_unaliased_module_import_without_the_full_dotted_call_is_not_matched(self):
        """`import verenigingen.utils.security.audit_logging` alone binds only
        the top-level `verenigingen` name; a call through some OTHER
        attribute path off that name must not be mistaken for the target."""
        literals = self._calls_and_literals(
            """
            import verenigingen.utils.security.audit_logging

            def f():
                verenigingen.log_security_event("not_the_real_one", {})
            """
        )
        self.assertEqual([], literals)
