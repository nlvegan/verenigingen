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
verenigingen.utils.security.audit_logging.log_security_event -- i.e. a bare
`log_security_event(...)` call in a file where that exact name is bound via
`from verenigingen.utils.security.audit_logging import log_security_event`
(module-level or local to a function; several call sites import it lazily).
Matching is done by which name is actually bound, not by substring, which is
exactly what let #1417's own census over-count.
"""

import ast
import json
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


def _event_type_arg(call):
    for kw in call.keywords:
        if kw.arg == "event_type":
            return kw.value
    if call.args:
        return call.args[0]
    return None


def _find_target_calls(tree):
    """Calls that are bare `name(...)` where `name` is bound to the real
    log_security_event via an ImportFrom in this file. Deliberately does NOT
    match attribute calls (`self.log_security_event(...)`,
    `PaymentLogger.log_security_event(...)`) -- those are different,
    same-named functions, not this one."""
    bound = _bound_names(tree, TARGET_MODULE, TARGET_FUNC)
    if not bound:
        return []
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in bound
    ]


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
