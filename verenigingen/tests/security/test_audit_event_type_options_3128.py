"""
#3128: every event type handed to the security audit logger must be one the logger can store.

SEPAAuditLogger.log_event stores an event in SEPA Audit Log when the type is in
SEPA_EVENT_TYPES, otherwise in API Audit Log, whose ``event_type`` is a Select. A type that is in
neither is refused by the Select; the broad ``except`` in the store path turns that into an Error
Log row, the caller sees success, and the audit row is silently missing.

Run on test_site_12:
    bench --site test_site_12 run-tests --app verenigingen \
        --module verenigingen.tests.security.test_audit_event_type_options_3128
"""

import ast
import json
import os
import tempfile

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.security.audit_logging import SEPAAuditLogger, log_sepa_event
from verenigingen.utils.security.types import AuditEventType

# Callables that feed the SEPAAuditLogger -> API/SEPA Audit Log pipeline. A bare ``log_event`` is
# also the name of other, unrelated loggers (migration trail, Mollie audit, payments compliance
# trail with its own AuditEventType), so those files are told apart by the import check below.
_PIPELINE_CALLS = {
    "log_event",
    "log_sepa_event",
    "log_security_event",
    "audit_log",
    "record_application_security_event",
}
_PIPELINE_IMPORT_MARKERS = (
    "verenigingen.utils.security.audit_logging",
    "verenigingen.utils.security.types",
    "verenigingen.utils.security.audit_emitter",
    "verenigingen.services.chapter.chapter_security",
)


def _api_audit_event_type_options():
    path = frappe.get_app_path("verenigingen", "verenigingen", "doctype", "api_audit_log")
    with open(os.path.join(path, "api_audit_log.json")) as fh:
        fields = json.load(fh)["fields"]
    options = next(f["options"] for f in fields if f["fieldname"] == "event_type")
    return set(options.split("\n"))


def _audit_event_type_literals_3128(app_root):
    """Yield (event_type, "path:line") for every literal event type passed to the pipeline.

    Resolves ``AuditEventType.X`` and ``AuditEventType.X.value`` to the enum's value. Skips the
    test tree; a dynamic argument (a variable) cannot be resolved and is not reported.
    """
    for dirpath, _dirs, files in os.walk(app_root):
        if os.sep + "tests" in dirpath or "node_modules" in dirpath:
            continue
        for filename in files:
            if filename.endswith(".py"):
                yield from _file_audit_event_literals_3128(os.path.join(dirpath, filename), app_root)


def _file_audit_event_literals_3128(path, app_root):
    with open(path) as fh:
        source = fh.read()
    if not any(marker in source for marker in _PIPELINE_IMPORT_MARKERS):
        return
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
        if name not in _PIPELINE_CALLS:
            continue
        arg = node.args[0] if node.args else None
        for kw in node.keywords:
            if kw.arg == "event_type":
                arg = kw.value
        value = _resolve_event_type_3128(arg)
        if value is not None:
            yield value, f"{os.path.relpath(path, app_root)}:{node.lineno}"


def _resolve_event_type_3128(arg):
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.Attribute) and arg.attr == "value":
        arg = arg.value
    if isinstance(arg, ast.Attribute) and getattr(arg.value, "id", None) == "AuditEventType":
        return AuditEventType[arg.attr].value
    return None


class TestAuditEventTypesAreStorable(VereningingenTestCase):
    def _storable(self):
        return _api_audit_event_type_options() | SEPAAuditLogger.SEPA_EVENT_TYPES

    def test_every_literal_event_type_is_storable(self):
        storable = self._storable()
        app_root = frappe.get_app_path("verenigingen")
        found = list(_audit_event_type_literals_3128(app_root))
        self.assertGreater(len(found), 40, "the scan found almost nothing; it is looking in the wrong place")
        unstorable = sorted((value, where) for value, where in found if value not in storable)
        self.assertEqual(
            unstorable,
            [],
            "event types that are neither an API Audit Log option nor in SEPA_EVENT_TYPES; the audit "
            "write is refused and only an Error Log row remains",
        )

    def test_control_the_scan_catches_an_unstorable_literal(self):
        """The scan must see a bad literal; without this a blind scan reads as green."""
        sample = (
            "from verenigingen.utils.security.audit_logging import log_sepa_event\n"
            "log_sepa_event('not_a_real_event_type_3128')\n"
            "log_sepa_event('sepa_batch_created')\n"
        )
        with tempfile.TemporaryDirectory() as root:
            sample_path = os.path.join(root, "sample.py")
            with open(sample_path, "w") as fh:
                fh.write(sample)
            found = [v for v, _where in _file_audit_event_literals_3128(sample_path, root)]
        self.assertEqual(found, ["not_a_real_event_type_3128", "sepa_batch_created"])
        self.assertEqual([v for v in found if v not in self._storable()], ["not_a_real_event_type_3128"])

    def test_refused_batch_creation_is_audited(self):
        """The endpoint's own refusal path (#3128): the audit row must land, with no store failure."""
        from verenigingen.verenigingen_payments.api.sepa_batch_ui_secure import (
            create_sepa_batch_validated_secure,
        )

        before = frappe.db.count("SEPA Audit Log", {"action": "sepa_batch_creation_validation_failed"})
        store_failures = frappe.db.count("Error Log", {"method": "API Audit Database Error"})

        response = create_sepa_batch_validated_secure(batch_date="not-a-date")

        self.assertFalse(response["success"])
        self.assertEqual(response["message"], "Input validation failed")
        self.assertEqual(
            frappe.db.count("SEPA Audit Log", {"action": "sepa_batch_creation_validation_failed"}),
            before + 1,
        )
        self.assertEqual(frappe.db.count("Error Log", {"method": "API Audit Database Error"}), store_failures)

    def test_every_sepa_batch_ui_event_type_lands_in_sepa_audit_log(self):
        for event_type in (
            "sepa_batch_creation_validation_failed",
            "sepa_batch_creation_duplicate_date",
            "sepa_batch_creation_invoice_validation_failed",
            "sepa_batch_creation_system_error",
            "sepa_invoice_validation_json_error",
            "sepa_validation_constraints_retrieved",
        ):
            with self.subTest(event_type=event_type):
                event_id = log_sepa_event(event_type, details={"probe": 3128})
                self.assertTrue(
                    frappe.db.exists("SEPA Audit Log", {"event_id": event_id, "action": event_type}),
                    f"{event_type} did not land in SEPA Audit Log",
                )
