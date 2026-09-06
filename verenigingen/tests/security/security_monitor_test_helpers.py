"""Shared test doubles for ``verenigingen.utils.security.security_monitoring``.

``SecurityMonitor`` (see ``get_security_monitor()``) is a process-wide singleton:
``incidents`` is an unbounded list, ``sliding_windows`` are bounded deques, and
``active_threats`` only ever shrinks via a manual ``resolve_incident()`` or the
LOW-severity auto-resolve path. Any test that drives the *shared* singleton past
its thresholds leaves HIGH/CRITICAL incidents sitting in ``active_threats`` and
``incidents`` for the rest of the worker process -- a later test anywhere in the
same shard that reads the shared monitor (e.g. ``_calculate_security_score``,
which deducts per active CRITICAL/HIGH incident) observes the pollution (#630).

Tests that exercise threat detection, incident creation, or score/metrics
computation must build a FRESH, isolated ``SecurityMonitor`` via
``make_isolated_security_monitor()`` instead of ``get_security_monitor()``, so
state is deterministic and never leaks across test classes or modules.
"""

from verenigingen.utils.security.security_monitoring import SecurityMonitor


class RecordingAuditLogger:
    """A thin collaborator stand-in for the audit logger.

    Creating a HIGH/CRITICAL ``SecurityIncident`` intentionally calls
    ``audit_logger.log_event("suspicious_activity", ...)``. The REAL audit
    logger's alert path recurses unbounded for a ``suspicious_activity`` event
    (audit_logging._check_alert_conditions -> _trigger_security_alert ->
    log_event -> ...; threshold is count=1/1min) -- a genuine production bug
    reported separately. We do NOT want security-monitoring incident tests
    held hostage by that subsystem bug, and the audit-logging *side effect*
    (not its internals) is what matters here: we assert the monitor calls the
    logger with the right event type/severity.

    This is a collaborator double injected onto the monitor's plain
    ``audit_logger`` attribute -- it is NOT a Frappe auth/permission primitive
    and NOT the function under test, so it is allowed by the test-quality rules.
    """

    def __init__(self):
        self.events = []

    def log_event(self, event_type, severity=None, **kwargs):
        self.events.append({"event_type": event_type, "severity": severity, **kwargs})
        return f"audit_stub_{len(self.events)}"


def make_isolated_security_monitor():
    """A fresh SecurityMonitor whose audit logger is the recording double."""
    monitor = SecurityMonitor()
    monitor.audit_logger = RecordingAuditLogger()
    return monitor
