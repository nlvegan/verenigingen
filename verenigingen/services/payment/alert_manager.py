"""
Alert Manager Service

Provides monitoring and alerting functionality for payment operations.
This service handles reconciliation backlog monitoring and threshold-based alerts
as part of the SEPA audit remediation (P2.2).

Key Features:
- Reconciliation threshold monitoring
- Configurable warning and critical thresholds
- Structured alert results for downstream processing

Author: Verenigingen Development Team
"""

from dataclasses import dataclass

from frappe import _

from verenigingen.services.infrastructure.base_service import StatelessService


@dataclass
class ReconciliationAlertResult:
    """
    Result of a reconciliation status check.

    Attributes:
        alert_triggered: Whether an alert condition was detected
        severity: Alert severity level ("info", "warning", "critical")
        message: Human-readable description of the alert status
        unreconciled_count: Number of unreconciled items checked
    """

    alert_triggered: bool
    severity: str
    message: str
    unreconciled_count: int


class AlertManager(StatelessService):
    """
    Alert management service for payment operations.

    Provides threshold-based monitoring for reconciliation backlogs
    and other payment-related alerts.

    Example:
        >>> manager = AlertManager()
        >>> result = manager.check_reconciliation_status(unreconciled_count=50)
        >>> if result.alert_triggered:
        ...     print(f"Alert: {result.severity} - {result.message}")
    """

    # Default thresholds for reconciliation monitoring
    DEFAULT_WARNING_THRESHOLD = 25
    DEFAULT_CRITICAL_THRESHOLD = 75

    def __init__(self) -> None:
        """Initialize the AlertManager service."""
        super().__init__(service_name="AlertManager")

    def check_reconciliation_status(
        self,
        unreconciled_count: int,
        threshold: int = None,
        critical_threshold: int = None,
    ) -> ReconciliationAlertResult:
        """
        Check reconciliation backlog against thresholds.

        Evaluates the number of unreconciled items against configurable
        warning and critical thresholds to determine alert status.

        Args:
            unreconciled_count: Number of unreconciled payment items
            threshold: Warning threshold (default: 25)
            critical_threshold: Critical threshold (default: 75)

        Returns:
            ReconciliationAlertResult with alert status and details

        Examples:
            >>> manager = AlertManager()
            >>> # Below threshold - no alert
            >>> result = manager.check_reconciliation_status(10)
            >>> result.alert_triggered
            False
            >>> result.severity
            'info'

            >>> # Above warning threshold
            >>> result = manager.check_reconciliation_status(50)
            >>> result.alert_triggered
            True
            >>> result.severity
            'warning'

            >>> # Above critical threshold
            >>> result = manager.check_reconciliation_status(100)
            >>> result.severity
            'critical'
        """
        # Apply defaults if not specified
        warning_threshold = threshold if threshold is not None else self.DEFAULT_WARNING_THRESHOLD
        crit_threshold = (
            critical_threshold if critical_threshold is not None else self.DEFAULT_CRITICAL_THRESHOLD
        )

        # Determine severity based on thresholds
        if unreconciled_count >= crit_threshold:
            return self._create_critical_alert(unreconciled_count, crit_threshold)
        elif unreconciled_count >= warning_threshold:
            return self._create_warning_alert(unreconciled_count, warning_threshold)
        else:
            return self._create_info_result(unreconciled_count, warning_threshold)

    def _create_critical_alert(
        self, unreconciled_count: int, critical_threshold: int
    ) -> ReconciliationAlertResult:
        """Create a critical alert result."""
        message = _(
            "Critical: {0} unreconciled items exceeds critical threshold of {1}. "
            "Immediate attention required."
        ).format(unreconciled_count, critical_threshold)

        self.logger.warning(f"Critical reconciliation alert: {unreconciled_count} items unreconciled")

        return ReconciliationAlertResult(
            alert_triggered=True,
            severity="critical",
            message=message,
            unreconciled_count=unreconciled_count,
        )

    def _create_warning_alert(
        self, unreconciled_count: int, warning_threshold: int
    ) -> ReconciliationAlertResult:
        """Create a warning alert result."""
        message = _(
            "Warning: {0} unreconciled items exceeds warning threshold of {1}. " "Review recommended."
        ).format(unreconciled_count, warning_threshold)

        self.logger.info(f"Warning reconciliation alert: {unreconciled_count} items unreconciled")

        return ReconciliationAlertResult(
            alert_triggered=True,
            severity="warning",
            message=message,
            unreconciled_count=unreconciled_count,
        )

    def _create_info_result(
        self, unreconciled_count: int, warning_threshold: int
    ) -> ReconciliationAlertResult:
        """Create an info result when no alert is triggered."""
        message = _("Reconciliation status normal: {0} unreconciled items (threshold: {1}).").format(
            unreconciled_count, warning_threshold
        )

        return ReconciliationAlertResult(
            alert_triggered=False,
            severity="info",
            message=message,
            unreconciled_count=unreconciled_count,
        )


# Factory function for service access
def get_alert_manager() -> AlertManager:
    """
    Get AlertManager instance.

    Returns:
        AlertManager instance
    """
    return AlertManager()
