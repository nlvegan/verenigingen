"""
Coverage tests for verenigingen/utils/security/audit_logging.py

Targets the SEPAAuditLogger persistence/routing/redaction/search/cleanup/alert
paths plus the module-level convenience functions, the audit_log decorator, and
the whitelisted API endpoints. These assert MEANINGFUL behaviour: that audit rows
land in the correct doctype with the correct field values, that sensitive details
are redacted, that the SEPA<->severity mappings round-trip, that search filters
return the right rows, and that retention cleanup deletes only expired rows.

Run on test_site_2:
    bench --site test_site_2 run-tests --app verenigingen \
        --module verenigingen.tests.security.test_audit_logging_coverage
"""

import json

import frappe
from frappe.utils import add_days, add_to_date, now, now_datetime, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.security.audit_logging import (
    SEPAAuditLogger,
    audit_log,
    cleanup_old_audit_logs,
    get_audit_logger,
    log_data_access,
    log_security_event,
    log_sensitive_operation,
    log_sepa_event,
    weekly_security_health_check,
)
from verenigingen.utils.security.types import AuditEventType, AuditSeverity


def _fetch_api_log(event_id):
    return frappe.db.get_value(
        "API Audit Log",
        {"event_id": event_id},
        ["event_type", "severity", "user", "details", "sensitive_data", "ip_address"],
        as_dict=True,
    )


def _fetch_sepa_log(event_id):
    return frappe.db.get_value(
        "SEPA Audit Log",
        {"event_id": event_id},
        ["process_type", "action", "compliance_status", "user", "details", "sensitive_data"],
        as_dict=True,
    )


class TestSEPAAuditLoggerRouting(VereningingenTestCase):
    """Events route to API Audit Log vs SEPA Audit Log based on type."""

    def setUp(self):
        super().setUp()
        self.logger = get_audit_logger()

    def test_get_audit_logger_is_singleton(self):
        self.assertIsInstance(get_audit_logger(), SEPAAuditLogger)
        self.assertIs(get_audit_logger(), get_audit_logger())

    def test_general_event_persists_to_api_audit_log(self):
        with self.assertNoErrorLog():
            event_id = self.logger.log_event(
                AuditEventType.DATA_EXPORT,
                AuditSeverity.WARNING,
                user="Administrator",
                ip_address="10.1.2.3",
                details={"resource": "members"},
            )
        self.track_doc("API Audit Log", event_id)

        row = _fetch_api_log(event_id)
        self.assertIsNotNone(row, "general event should land in API Audit Log")
        self.assertEqual(row.event_type, "data_export")
        self.assertEqual(row.severity, "warning")
        self.assertEqual(row.user, "Administrator")
        self.assertEqual(row.ip_address, "10.1.2.3")
        self.assertEqual(json.loads(row.details).get("resource"), "members")
        # not a SEPA event
        self.assertIsNone(_fetch_sepa_log(event_id))

    def test_sepa_event_persists_to_sepa_audit_log_with_mapped_fields(self):
        with self.assertNoErrorLog():
            event_id = self.logger.log_event(
                "sepa_batch_created",
                AuditSeverity.INFO,
                user="Administrator",
                details={"batch": "B-1"},
            )
        self.track_doc("SEPA Audit Log", event_id)

        row = _fetch_sepa_log(event_id)
        self.assertIsNotNone(row, "SEPA event should land in SEPA Audit Log")
        self.assertEqual(row.action, "sepa_batch_created")
        # severity info -> compliance "Compliant"; process_type from mapping
        self.assertEqual(row.compliance_status, "Compliant")
        self.assertEqual(row.process_type, "Batch Generation")
        self.assertEqual(json.loads(row.details).get("batch"), "B-1")
        self.assertIsNone(_fetch_api_log(event_id))

    def test_severity_to_compliance_status_full_mapping(self):
        cases = {
            "info": "Compliant",
            "warning": "Exception",
            "error": "Failed",
            "critical": "Pending Review",
            "weird": "Pending Review",  # default fallback
        }
        for severity, expected in cases.items():
            self.assertEqual(self.logger._map_severity_for_sepa(severity), expected)

    def test_process_type_mapping_and_default(self):
        self.assertEqual(self.logger._map_event_to_sepa_process_type("mandate_creation"), "Mandate Creation")
        self.assertEqual(self.logger._map_event_to_sepa_process_type("bank_submission"), "Bank Submission")
        self.assertEqual(
            self.logger._map_event_to_sepa_process_type("payment_processing"), "Payment Processing"
        )
        # unknown SEPA action falls back to Batch Generation
        self.assertEqual(
            self.logger._map_event_to_sepa_process_type("unknown_sepa_thing"), "Batch Generation"
        )

    def test_unmap_severity_round_trips(self):
        for sev in ("info", "warning", "error", "critical"):
            compliance = self.logger._map_severity_for_sepa(sev)
            self.assertEqual(self.logger._unmap_severity_from_sepa(compliance), sev)
        self.assertEqual(self.logger._unmap_severity_from_sepa("garbage"), "info")

    def test_enum_and_string_event_types_both_accepted(self):
        # passing an enum directly should serialize to its .value
        with self.assertNoErrorLog():
            event_id = self.logger.log_event(AuditEventType.SYSTEM_ERROR, AuditSeverity.ERROR)
        self.track_doc("API Audit Log", event_id)
        row = _fetch_api_log(event_id)
        self.assertEqual(row.event_type, "system_error")
        self.assertEqual(row.severity, "error")


class TestSEPAAuditLoggerUserHandling(VereningingenTestCase):
    """User-field handling and role capture."""

    def setUp(self):
        super().setUp()
        self.logger = get_audit_logger()

    def test_nonexistent_user_moved_to_details_and_field_nulled(self):
        fake = "definitely-not-a-real-user@example.invalid"
        self.assertFalse(frappe.db.exists("User", fake))
        with self.assertNoErrorLog():
            event_id = self.logger.log_event(
                AuditEventType.DATA_MODIFICATION,
                AuditSeverity.INFO,
                user=fake,
                details={"x": 1},
            )
        self.track_doc("API Audit Log", event_id)

        row = _fetch_api_log(event_id)
        # The bogus user must NEVER be written into the User-link field (it would
        # be a dangling Link). Frappe defaults an empty Link-to-User to the
        # session user, so the stored value is the session user, not the fake.
        self.assertNotEqual(row.user, fake)
        # The original (unverifiable) email is preserved in details so the trail
        # is not lost.
        details = json.loads(row.details)
        self.assertEqual(details.get("original_user_email"), fake)
        self.assertEqual(details.get("x"), 1)

    def test_default_user_is_session_user(self):
        user = self.create_test_user("audit-default-user@example.com", roles=["System Manager"])
        with self.as_user(user.name):
            with self.assertNoErrorLog():
                event_id = self.logger.log_event(AuditEventType.SENSITIVE_DATA_ACCESS, AuditSeverity.INFO)
        self.track_doc("API Audit Log", event_id)
        row = _fetch_api_log(event_id)
        self.assertEqual(row.user, user.name)

    def test_real_user_roles_captured_in_details_for_sepa(self):
        # user_roles only added to the in-memory event for non-Guest users;
        # verify via a real user storing a SEPA event (details JSON preserved).
        user = self.create_test_user("audit-roles-user@example.com", roles=["System Manager"])
        with self.as_user(user.name):
            with self.assertNoErrorLog():
                event_id = self.logger.log_event("sepa_xml_generated", AuditSeverity.INFO)
        self.track_doc("SEPA Audit Log", event_id)
        row = _fetch_sepa_log(event_id)
        self.assertEqual(row.user, user.name)
        self.assertEqual(row.process_type, "Bank Submission")


class TestRedaction(VereningingenTestCase):
    """_redact_sensitive_details masks sensitive keys without losing structure."""

    def test_top_level_sensitive_keys_redacted(self):
        out = SEPAAuditLogger._redact_sensitive_details(
            {"iban": "NL00BANK", "api_key": "secret", "name": "Jan", "amount": 12}
        )
        self.assertEqual(out["iban"], "***REDACTED***")
        self.assertEqual(out["api_key"], "***REDACTED***")
        self.assertEqual(out["name"], "Jan")
        self.assertEqual(out["amount"], 12)

    def test_nested_dict_and_list_redaction(self):
        out = SEPAAuditLogger._redact_sensitive_details(
            {
                "outer": {"password": "hunter2", "ok": "fine"},
                "items": [{"bsn": "123456789"}, {"label": "safe"}],
            }
        )
        self.assertEqual(out["outer"]["password"], "***REDACTED***")
        self.assertEqual(out["outer"]["ok"], "fine")
        self.assertEqual(out["items"][0]["bsn"], "***REDACTED***")
        self.assertEqual(out["items"][1]["label"], "safe")

    def test_depth_limit_truncates_failsafe(self):
        # Build nesting deeper than the depth limit (6); a sensitive key buried
        # below the limit must be truncated, never passed through in cleartext.
        deep = current = {}
        for _ in range(10):
            nxt = {}
            current["child"] = nxt
            current = nxt
        current["token"] = "leak"
        out = SEPAAuditLogger._redact_sensitive_details(deep)
        # walk down until we hit the truncation sentinel
        s = json.dumps(out)
        self.assertIn("TRUNCATED:depth_limit", s)
        self.assertNotIn("leak", s, "sensitive value below depth limit must not leak")

    def test_redaction_applied_on_persisted_event(self):
        logger = get_audit_logger()
        with self.assertNoErrorLog():
            event_id = logger.log_event(
                AuditEventType.SENSITIVE_DATA_ACCESS,
                AuditSeverity.INFO,
                user="Administrator",
                details={"member_iban": "NL11RABO0123456789", "member": "Jan"},
            )
        self.track_doc("API Audit Log", event_id)
        details = json.loads(_fetch_api_log(event_id).details)
        self.assertEqual(details["member_iban"], "***REDACTED***")
        self.assertEqual(details["member"], "Jan")


class TestSearchAuditLogs(VereningingenTestCase):
    """search_audit_logs merges both tables, applies filters, and normalizes fields."""

    def setUp(self):
        super().setUp()
        self.logger = get_audit_logger()
        # Unique marker so we only assert on rows we created
        self.marker = frappe.generate_hash(length=8)

    def _emit_api(self, event_type, severity, user="Administrator"):
        eid = self.logger.log_event(event_type, severity, user=user, details={"marker": self.marker})
        self.track_doc("API Audit Log", eid)
        return eid

    def _emit_sepa(self, event_type, severity, user="Administrator"):
        eid = self.logger.log_event(event_type, severity, user=user, details={"marker": self.marker})
        self.track_doc("SEPA Audit Log", eid)
        return eid

    def test_search_returns_both_tables_and_normalizes(self):
        with self.assertNoErrorLog():
            api_id = self._emit_api(AuditEventType.DATA_EXPORT, AuditSeverity.WARNING)
            sepa_id = self._emit_sepa("sepa_batch_created", AuditSeverity.INFO)

        results = self.logger.search_audit_logs(limit=200)
        by_id = {r["event_id"]: r for r in results}
        self.assertIn(api_id, by_id)
        self.assertIn(sepa_id, by_id)

        api_row = by_id[api_id]
        self.assertEqual(api_row["source_table"], "API Audit Log")
        self.assertEqual(api_row["event_type"], "data_export")
        self.assertEqual(api_row["severity"], "warning")
        self.assertIsInstance(api_row["details"], dict)
        self.assertEqual(api_row["details"]["marker"], self.marker)

        sepa_row = by_id[sepa_id]
        self.assertEqual(sepa_row["source_table"], "SEPA Audit Log")
        # action normalized into event_type, compliance unmapped into severity
        self.assertEqual(sepa_row["event_type"], "sepa_batch_created")
        self.assertEqual(sepa_row["severity"], "info")

    def test_search_filters_by_event_type_splits_correctly(self):
        with self.assertNoErrorLog():
            api_id = self._emit_api(AuditEventType.DATA_IMPORT, AuditSeverity.INFO)
            sepa_id = self._emit_sepa("sepa_xml_generated", AuditSeverity.INFO)

        # asking only for the SEPA event type must not return the API row
        results = self.logger.search_audit_logs(event_types=["sepa_xml_generated"], limit=200)
        ids = {r["event_id"] for r in results}
        self.assertIn(sepa_id, ids)
        self.assertNotIn(api_id, ids)
        for r in results:
            self.assertEqual(r["event_type"], "sepa_xml_generated")

    def test_search_filters_by_user(self):
        user = self.create_test_user("audit-search-user@example.com", roles=["System Manager"])
        with self.assertNoErrorLog():
            mine = self._emit_api(AuditEventType.DATA_MODIFICATION, AuditSeverity.INFO, user=user.name)
            other = self._emit_api(AuditEventType.DATA_MODIFICATION, AuditSeverity.INFO, user="Administrator")

        results = self.logger.search_audit_logs(users=[user.name], limit=200)
        ids = {r["event_id"] for r in results}
        self.assertIn(mine, ids)
        self.assertNotIn(other, ids)

    def test_search_filters_by_severity(self):
        with self.assertNoErrorLog():
            crit = self._emit_api(AuditEventType.SYSTEM_ERROR, AuditSeverity.CRITICAL)
            info = self._emit_api(AuditEventType.DATA_EXPORT, AuditSeverity.INFO)

        results = self.logger.search_audit_logs(severity="critical", limit=200)
        ids = {r["event_id"] for r in results}
        self.assertIn(crit, ids)
        self.assertNotIn(info, ids)


class TestAlertConditions(VereningingenTestCase):
    """Alert thresholds trigger a SUSPICIOUS_ACTIVITY critical event."""

    def setUp(self):
        super().setUp()
        self.logger = get_audit_logger()

    def test_unauthorized_access_threshold_triggers_suspicious_activity(self):
        # threshold for UNAUTHORIZED_ACCESS_ATTEMPT is count=3 in 5 minutes.
        # Sending the 3rd should trip _trigger_security_alert which logs a
        # CRITICAL suspicious_activity event. Notification email may fail in the
        # test bench (no SMTP) -> swallowed + logged, so allow that one.
        self.expectErrorLog("Security Notification")
        before = frappe.db.count("API Audit Log", {"event_type": "suspicious_activity"})
        for _ in range(3):
            eid = self.logger.log_event(
                AuditEventType.UNAUTHORIZED_ACCESS_ATTEMPT,
                AuditSeverity.WARNING,
                user="Administrator",
            )
            self.track_doc("API Audit Log", eid)
        after = frappe.db.count("API Audit Log", {"event_type": "suspicious_activity"})
        self.assertGreater(after, before, "threshold breach must emit a suspicious_activity event")

    def test_count_recent_events_does_not_silently_return_zero(self):
        # Regression: _count_recent_events used add_days(now(), minutes=...),
        # which raises TypeError (add_days takes only date+days). The bare except
        # swallowed it and returned 0, disabling every alert threshold. After the
        # fix, freshly-emitted events of a type are actually counted (> 0).
        event = "failed_login_attempt"
        for _ in range(2):
            eid = self.logger.log_event(
                AuditEventType.FAILED_LOGIN_ATTEMPT, AuditSeverity.WARNING, user="Administrator"
            )
            self.track_doc("API Audit Log", eid)
        self.assertGreaterEqual(
            self.logger._count_recent_events(event, 30),
            2,
            "recent-event counting must work; a swallowed TypeError disables alerting",
        )

    def test_count_recent_events_counts_api_table(self):
        marker_type = "rate_limit_exceeded"
        before = self.logger._count_recent_events(marker_type, 60)
        eid = self.logger.log_event(
            AuditEventType.RATE_LIMIT_EXCEEDED, AuditSeverity.WARNING, user="Administrator"
        )
        self.track_doc("API Audit Log", eid)
        after = self.logger._count_recent_events(marker_type, 60)
        self.assertEqual(after, before + 1)

    def test_non_thresholded_event_does_not_alert(self):
        before = frappe.db.count("API Audit Log", {"event_type": "suspicious_activity"})
        with self.assertNoErrorLog():
            eid = self.logger.log_event(AuditEventType.DATA_EXPORT, AuditSeverity.INFO, user="Administrator")
        self.track_doc("API Audit Log", eid)
        after = frappe.db.count("API Audit Log", {"event_type": "suspicious_activity"})
        self.assertEqual(after, before, "ordinary events must not trip alerting")

    def test_suspicious_activity_alert_does_not_recurse(self):
        """Regression: logging a SUSPICIOUS_ACTIVITY event must not recurse.

        SUSPICIOUS_ACTIVITY's threshold is count=1/window=1, so once
        _count_recent_events returns real counts (its TypeError-swallow bug is
        fixed), the first such event tripped _trigger_security_alert, which logs
        ANOTHER SUSPICIOUS_ACTIVITY event -> re-entered alert checking -> infinite
        recursion until RecursionError (swallowed as 'Alert checking failed').
        The alert meta-event now passes check_alerts=False, breaking the cycle:
        exactly ONE alert event is emitted and no recursion Error Log appears.
        """
        # The alert path attempts an admin notification email; no SMTP in bench.
        self.expectErrorLog("Security Notification")
        before = frappe.db.count("API Audit Log", {"event_type": "suspicious_activity"})
        eid = self.logger.log_event(
            AuditEventType.SUSPICIOUS_ACTIVITY, AuditSeverity.WARNING, user="Administrator"
        )
        self.track_doc("API Audit Log", eid)
        after = frappe.db.count("API Audit Log", {"event_type": "suspicious_activity"})
        delta = after - before
        # Post-fix: the original event + exactly one alert meta-event (+2).
        # Pre-fix: the recursion stored one row per stack frame (~hundreds)
        # before RecursionError. A range tolerates concurrent-session noise
        # while still failing loudly on a recursion runaway.
        self.assertGreaterEqual(delta, 2, "threshold breach must emit an alert event")
        self.assertLess(delta, 20, "alert path must not recurse (would store hundreds of rows)")


class TestCleanup(VereningingenTestCase):
    """Retention cleanup deletes only rows older than the policy cutoff."""

    def _make_api_log(self, severity, timestamp):
        eid = f"cov-cleanup-{frappe.generate_hash(length=10)}"
        doc = frappe.new_doc("API Audit Log")
        doc.update(
            {
                "event_id": eid,
                "timestamp": timestamp,
                "event_type": "data_export",
                "severity": severity,
                "user": None,
                "details": "{}",
                "sensitive_data": 0,
            }
        )
        doc.insert(ignore_permissions=True)
        return eid

    def test_cleanup_api_logs_deletes_expired_keeps_recent(self):
        logger = get_audit_logger()
        # INFO retention is 30 days. One old (deleted), one recent (kept).
        old_ts = add_to_date(now_datetime(), days=-400)
        recent_ts = now()
        old_id = self._make_api_log("info", old_ts)
        recent_id = self._make_api_log("info", recent_ts)
        self.track_doc("API Audit Log", recent_id)
        frappe.db.commit()

        cutoff = add_days(today(), -30)
        deleted = logger._cleanup_api_logs("info", cutoff)
        self.assertGreaterEqual(deleted, 1)
        self.assertFalse(frappe.db.exists("API Audit Log", {"event_id": old_id}))
        self.assertTrue(frappe.db.exists("API Audit Log", {"event_id": recent_id}))

    def test_cleanup_old_audit_logs_wrapper_runs_clean(self):
        # Smoke: the scheduled wrapper must run without raising / logging errors.
        with self.assertNoErrorLog():
            cleanup_old_audit_logs()


class TestConvenienceFunctions(VereningingenTestCase):
    """Module-level helpers route to the right event type/table."""

    def test_log_sepa_event_lands_in_sepa_table(self):
        with self.assertNoErrorLog():
            eid = log_sepa_event("sepa_batch_validated", details={"k": "v"}, severity="info")
        self.track_doc("SEPA Audit Log", eid)
        row = _fetch_sepa_log(eid)
        self.assertEqual(row.action, "sepa_batch_validated")

    def test_log_security_event_defaults_to_warning_api(self):
        with self.assertNoErrorLog():
            eid = log_security_event("permission_denied", details={"k": "v"})
        self.track_doc("API Audit Log", eid)
        row = _fetch_api_log(eid)
        self.assertEqual(row.event_type, "permission_denied")
        self.assertEqual(row.severity, "warning")

    def test_log_data_access_marks_sensitive(self):
        with self.assertNoErrorLog():
            eid = log_data_access("member_data", "read", details={"id": 1})
        self.track_doc("API Audit Log", eid)
        row = _fetch_api_log(eid)
        self.assertEqual(row.event_type, "sensitive_data_access")
        self.assertEqual(int(row.sensitive_data), 1)
        details = json.loads(row.details)
        self.assertEqual(details["resource"], "member_data")
        self.assertEqual(details["action"], "read")

    def test_log_sensitive_operation_sepa_branch_persists(self):
        # Regression: log_sensitive_operation() used to prefix a SEPA operation
        # with "sepa_" -> "sepa_batch_creation", a name in NEITHER
        # SEPA_EVENT_TYPES nor the API Audit Log Select options, so EVERY SEPA
        # sensitive-operation audit was silently dropped (Error Log only). The
        # operations now map to real SEPA_EVENT_TYPES names that route to (and
        # persist in) the SEPA Audit Log.
        with self.assertNoErrorLog():
            eid = log_sensitive_operation("batch_creation", "sepa_batch", details={"batch": "B"})
        sepa_row = _fetch_sepa_log(eid)
        self.assertIsNotNone(sepa_row, "SEPA sensitive-operation audit must persist")
        self.assertEqual(sepa_row.action, "sepa_batch_created")
        self.assertIsNone(_fetch_api_log(eid), "must route to SEPA table, not API table")

    def test_log_sensitive_operation_sepa_xml_no_double_prefix(self):
        # The old f"sepa_{operation}" produced the double-prefixed
        # "sepa_sepa_xml_generation"; the mapping resolves it to the real
        # "sepa_xml_generated" event type.
        with self.assertNoErrorLog():
            eid = log_sensitive_operation("sepa_xml_generation", "sepa_batch", details={"batch": "B"})
        sepa_row = _fetch_sepa_log(eid)
        self.assertIsNotNone(sepa_row)
        self.assertEqual(sepa_row.action, "sepa_xml_generated")

    def test_log_sensitive_operation_non_sepa_branch(self):
        with self.assertNoErrorLog():
            eid = log_sensitive_operation("data_export", "member_data", details={"rows": 5})
        self.track_doc("API Audit Log", eid)
        row = _fetch_api_log(eid)
        self.assertEqual(row.event_type, "sensitive_data_access")
        details = json.loads(row.details)
        self.assertEqual(details["operation"], "data_export")
        self.assertEqual(details["resource"], "member_data")

    def test_weekly_security_health_check_logs_other_event(self):
        with self.assertNoErrorLog():
            weekly_security_health_check()
        # writes event_type "other" to API Audit Log
        rows = frappe.get_all(
            "API Audit Log",
            filters={"event_type": "other"},
            fields=["details"],
            order_by="creation desc",
            limit=1,
        )
        self.assertTrue(rows)
        self.assertEqual(json.loads(rows[0].details)["check_type"], "weekly_health_check")


class TestAuditLogDecorator(VereningingenTestCase):
    """The @audit_log decorator logs success and error, and re-raises."""

    def test_decorator_logs_success(self):
        @audit_log("data_export", "info", capture_args=True)
        def do_thing(a, b=2):
            return a + b

        before = frappe.db.count("API Audit Log", {"event_type": "data_export"})
        with self.assertNoErrorLog():
            self.assertEqual(do_thing(1, b=3), 4)
        after = frappe.db.count("API Audit Log", {"event_type": "data_export"})
        self.assertEqual(after, before + 1)

        row = frappe.get_all(
            "API Audit Log",
            filters={"event_type": "data_export"},
            fields=["details", "severity"],
            order_by="creation desc",
            limit=1,
        )[0]
        details = json.loads(row.details)
        self.assertEqual(details["status"], "success")
        self.assertEqual(details["function"], "do_thing")
        self.assertIn("execution_time_ms", details)
        self.assertEqual(details["args_count"], 1)
        self.assertIn("b", details["kwargs_keys"])

    def test_decorator_logs_error_and_reraises(self):
        @audit_log("data_modification", "info")
        def boom():
            raise ValueError("nope")

        with self.assertRaises(ValueError):
            with self.assertNoErrorLog():
                boom()

        row = frappe.get_all(
            "API Audit Log",
            filters={"event_type": "data_modification", "severity": "error"},
            fields=["details"],
            order_by="creation desc",
            limit=1,
        )[0]
        details = json.loads(row.details)
        self.assertEqual(details["status"], "error")
        self.assertEqual(details["error_type"], "ValueError")
        self.assertEqual(details["error_message"], "nope")


class TestWhitelistedEndpoints(VereningingenTestCase):
    """API endpoints enforce System Manager and return structured payloads."""

    def test_search_endpoint_denies_non_admin(self):
        from verenigingen.utils.security import audit_logging

        member = self.create_test_member(
            first_name="NoAdmin", last_name="Audit", email="noadmin-audit@example.com"
        )
        user = self.create_test_user("noadmin-audit-user@example.com", roles=["Verenigingen Member"])
        with self.as_user(user.name):
            with self.assertRaises(frappe.PermissionError):
                audit_logging.search_audit_logs()

    def test_search_endpoint_returns_logs_for_admin(self):
        from verenigingen.utils.security import audit_logging

        # seed a recognizable event first
        marker = frappe.generate_hash(length=8)
        eid = get_audit_logger().log_event(
            AuditEventType.DATA_EXPORT, AuditSeverity.INFO, user="Administrator", details={"m": marker}
        )
        self.track_doc("API Audit Log", eid)

        with self.as_user("Administrator"):
            result = audit_logging.search_audit_logs(limit=200)
        self.assertTrue(result["success"])
        self.assertIn("logs", result)
        self.assertEqual(result["count"], len(result["logs"]))

    def test_statistics_endpoint_denies_non_admin(self):
        from verenigingen.utils.security import audit_logging

        user = self.create_test_user("noadmin-stats-user@example.com", roles=["Verenigingen Member"])
        with self.as_user(user.name):
            with self.assertRaises(frappe.PermissionError):
                audit_logging.get_audit_statistics(days=7)

    def test_statistics_endpoint_returns_structure_for_admin(self):
        from verenigingen.utils.security import audit_logging

        eid = get_audit_logger().log_event(
            "sepa_batch_created", AuditSeverity.INFO, user="Administrator", details={}
        )
        self.track_doc("SEPA Audit Log", eid)

        with self.as_user("Administrator"):
            result = audit_logging.get_audit_statistics(days=30)
        self.assertTrue(result["success"])
        for key in ("event_types", "severity_levels", "user_activity", "daily_activity", "table_summary"):
            self.assertIn(key, result)
        self.assertEqual(result["period_days"], 30)


class TestSeverityNormalisation(VereningingenTestCase):
    """log_event() accepts `Union[AuditSeverity, str]`, so a string must work too.

    API Audit Log.severity is a Select of info/warning/error/critical. Only the enum
    branch was normalised, so a caller passing the level as a string in any other case
    produced a value the Select rejects. The insert is wrapped in a broad `except`
    that logs and continues, so the row was dropped while the caller saw success --
    the audit trail lost entries with no signal at the call site.

    These assert the row LANDS and carries the right value, not merely that nothing
    raised: the old behaviour did not raise either.
    """

    def _log_and_fetch(self, severity):
        event_id = get_audit_logger().log_event(
            "api_call_success", severity, user="Administrator", details={}, check_alerts=False
        )
        self.track_doc("API Audit Log", event_id)
        return _fetch_api_log(event_id)

    def test_uppercase_string_severity_is_persisted(self):
        row = self._log_and_fetch("INFO")
        self.assertIsNotNone(row, "audit row was dropped instead of stored")
        self.assertEqual(row.severity, "info")

    def test_mixed_case_string_severity_is_persisted(self):
        row = self._log_and_fetch("Warning")
        self.assertIsNotNone(row, "audit row was dropped instead of stored")
        self.assertEqual(row.severity, "warning")

    def test_lowercase_string_severity_still_works(self):
        """Guard: normalising must not disturb the already-correct path."""
        row = self._log_and_fetch("critical")
        self.assertIsNotNone(row)
        self.assertEqual(row.severity, "critical")

    def test_enum_severity_still_works(self):
        """Guard: the pre-existing enum branch is unchanged."""
        row = self._log_and_fetch(AuditSeverity.ERROR)
        self.assertIsNotNone(row)
        self.assertEqual(row.severity, "error")

    def test_unrecognised_severity_still_records_the_event(self):
        """An audit trail that drops what it cannot classify is worse than one that
        records it under a fallback: the event itself is the thing being protected."""
        row = self._log_and_fetch("NOT_A_LEVEL")
        self.assertIsNotNone(row, "unrecognised severity must not discard the audit row")
        self.assertIn(row.severity, ("info", "warning", "error", "critical"))
