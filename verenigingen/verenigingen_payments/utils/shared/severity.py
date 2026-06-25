"""Canonical severity / priority enums shared across the SEPA monitoring cluster.

Historically the Week-4 monitoring modules each defined their own near-identical
severity enum:

- ``sepa_alerting_system.AlertSeverity``  -> info / warning / critical / emergency
- ``sepa_notification_manager.NotificationPriority`` -> low / medium / high / critical
- ``sepa_conflict_detector.ConflictSeverity`` -> critical / warning / info

This module hosts the two canonical enums so the definitions live in one place.
The string ``.value`` of every member is preserved exactly, because whitelisted
API endpoints and tests compare against these literal values (e.g.
``AlertSeverity(severity)`` round-trips a ``"critical"`` query parameter, and
``get_active_alerts`` sorts on ``x["severity"]``).

``AlertSeverity`` and ``NotificationPriority`` in the consuming modules are
aliases of ``Severity`` and ``PriorityLevel`` defined here, so ``isinstance``
checks, dict lookups keyed by enum members, and ``Enum(value)`` reconstruction
all continue to behave identically.

NOTE: ``ConflictSeverity`` lives in ``sepa_conflict_detector.py`` which is outside
this task's file set; it shares the info/warning/critical values with ``Severity``
and is a follow-up candidate for consolidation here.
"""

from enum import Enum


class Severity(Enum):
    """Alerting severity levels (canonical home for ``AlertSeverity``)."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class PriorityLevel(Enum):
    """Notification priority levels (canonical home for ``NotificationPriority``)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
