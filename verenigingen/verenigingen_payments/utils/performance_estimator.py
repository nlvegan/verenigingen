# Copyright (c) 2025, Your Name and contributors
# For license information, please see license.txt

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List

import frappe


class ProcessingMode(Enum):
    """Processing mode enumeration"""

    IMMEDIATE = "immediate"
    BACKGROUND = "background"
    REJECTED = "rejected"


@dataclass
class PerformanceEstimate:
    """Performance estimation with user communication"""

    operation_count: int
    estimated_duration: float
    processing_mode: ProcessingMode
    user_message: str
    technical_details: Dict[str, Any]
    recommendations: List[str]


class SEPAPerformanceEstimatorClean:
    """
    Clean performance estimation without fake learning

    Provides honest estimates based on known Frappe Framework limitations
    without claiming machine learning capabilities that don't persist.
    """

    # Static performance baselines based on Frappe Framework research
    BASE_PERFORMANCE = {"create": 2.5, "update": 3.0, "cancel": 3.5}

    # Frappe framework limits (from research)
    SYNC_LIMIT = 20
    BACKGROUND_LIMIT = 500

    def estimate_processing(self, operations: List[Dict[str, Any]]) -> PerformanceEstimate:
        """Generate performance estimate based on static analysis"""

        operation_count = len(operations)

        # Determine processing mode
        mode = self._determine_processing_mode(operation_count)

        # Calculate time estimation
        estimated_duration = self._calculate_duration(operations)

        # Generate user-friendly message
        user_message = self._generate_user_message(operation_count, estimated_duration, mode)

        # Create recommendations
        recommendations = self._generate_recommendations(operation_count, mode)

        # Technical details for developers/admins
        technical_details = self._generate_technical_details(operations, estimated_duration)

        return PerformanceEstimate(
            operation_count=operation_count,
            estimated_duration=estimated_duration,
            processing_mode=mode,
            user_message=user_message,
            technical_details=technical_details,
            recommendations=recommendations,
        )

    def estimate_processing_performance(
        self, operation_count: int, complexity_factors: Dict[str, Any] = None
    ) -> PerformanceEstimate:
        """Backward compatibility alias for estimate_processing"""
        # Convert to expected format
        operations = [{"operation_type": "create"} for _ in range(operation_count)]
        return self.estimate_processing(operations)

    def _determine_processing_mode(self, operation_count: int) -> ProcessingMode:
        """Determine processing mode based on Frappe Framework limits"""
        if operation_count <= self.SYNC_LIMIT:
            return ProcessingMode.IMMEDIATE
        elif operation_count <= self.BACKGROUND_LIMIT:
            return ProcessingMode.BACKGROUND
        else:
            return ProcessingMode.REJECTED

    def _calculate_duration(self, operations: List[Dict[str, Any]]) -> float:
        """Calculate estimated duration based on operation types"""
        if not operations:
            return 0.0

        # Group operations by type
        operation_types = {}
        for op in operations:
            op_type = op.get("operation_type", "create")
            operation_types[op_type] = operation_types.get(op_type, 0) + 1

        # Calculate duration for each type using static rates
        total_duration = 0.0
        for op_type, count in operation_types.items():
            rate = self.BASE_PERFORMANCE.get(op_type, 2.0)
            total_duration += count / rate

        # Add overhead for batch processing
        overhead = min(len(operations) * 0.1, 30)  # Max 30 seconds overhead

        return total_duration + overhead

    def _generate_user_message(self, count: int, duration: float, mode: ProcessingMode) -> str:
        """Generate user-friendly performance message"""

        if mode == ProcessingMode.REJECTED:
            return f"500 operations maximum. Cannot process {count} operations."

        duration_text = self._format_duration(duration)

        if mode == ProcessingMode.IMMEDIATE:
            return (
                f"✅ Processing {count} operations immediately. "
                f"Estimated time: {duration_text}. You'll see real-time progress updates."
            )

        if mode == ProcessingMode.BACKGROUND:
            return (
                f"⏳ Processing {count} operations in background. "
                f"Estimated time: {duration_text}. You'll receive a notification when complete."
            )

        return f"Processing {count} operations (estimated: {duration_text})"

    def _format_duration(self, duration: float) -> str:
        """Format duration in user-friendly format"""
        if duration < 60:
            return f"{int(duration)} seconds"
        elif duration < 3600:
            minutes = int(duration / 60)
            seconds = int(duration % 60)
            return f"{minutes}m {seconds}s"
        else:
            hours = int(duration / 3600)
            minutes = int((duration % 3600) / 60)
            return f"{hours}h {minutes}m"

    def _generate_recommendations(self, count: int, mode: ProcessingMode) -> List[str]:
        """Generate performance recommendations"""
        recommendations = []

        if mode == ProcessingMode.REJECTED:
            optimal_batch_size = self.BACKGROUND_LIMIT
            batch_count = (count + optimal_batch_size - 1) // optimal_batch_size
            recommendations.extend(
                [
                    f"Split into {batch_count} batches of ~{optimal_batch_size} operations each",
                    "Process batches sequentially to avoid system overload",
                    "Consider filtering operations to reduce total count if possible",
                ]
            )

        elif mode == ProcessingMode.BACKGROUND:
            if count > 100:
                recommendations.append("Large batch - consider running during off-peak hours")
            recommendations.append("Background processing allows you to continue other work")

        elif mode == ProcessingMode.IMMEDIATE:
            if count > 10:
                recommendations.append("Small batch - perfect for immediate processing")

        return recommendations

    def _generate_technical_details(
        self, operations: List[Dict[str, Any]], duration: float
    ) -> Dict[str, Any]:
        """Generate technical details for developers/admins"""

        operation_breakdown = {}
        for op in operations:
            op_type = op.get("operation_type", "unknown")
            operation_breakdown[op_type] = operation_breakdown.get(op_type, 0) + 1

        return {
            "total_operations": len(operations),
            "operation_breakdown": operation_breakdown,
            "estimated_total_duration": round(duration, 2),
            "average_rate_per_operation": round(duration / len(operations) if operations else 0, 2),
            "framework_limits": {"synchronous_max": self.SYNC_LIMIT, "background_max": self.BACKGROUND_LIMIT},
            "performance_baselines": self.BASE_PERFORMANCE,
            "note": "Estimates based on Frappe Framework research, not historical data",
        }


# Simple factory function without singleton complexity
def get_clean_performance_estimator() -> SEPAPerformanceEstimatorClean:
    """Get clean performance estimator instance"""
    return SEPAPerformanceEstimatorClean()


def estimate_sepa_operation_performance_clean(operations: List[Dict[str, Any]]) -> PerformanceEstimate:
    """Convenience function for performance estimation"""
    estimator = get_clean_performance_estimator()
    return estimator.estimate_processing(operations)
