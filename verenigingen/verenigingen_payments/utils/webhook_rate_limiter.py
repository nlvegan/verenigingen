"""
Webhook Rate Limiting and DDoS Protection

Provides comprehensive rate limiting specifically designed for payment webhook endpoints
to prevent volumetric attacks and resource exhaustion.
"""

import threading
import time
from collections import defaultdict, deque
from typing import Dict, Optional, Tuple

import frappe
from frappe.utils import cint


class WebhookRateLimitExceeded(frappe.ValidationError):
    """Raised when webhook rate limit is exceeded"""

    pass


class WebhookRateLimiter:
    """
    Multi-tier rate limiting for webhook endpoints with DDoS protection

    Implements:
    - IP-based rate limiting (prevents IP flooding)
    - Webhook ID-based rate limiting (prevents duplicate webhook spam)
    - Global rate limiting (prevents total system overload)
    - Progressive penalties for repeat offenders
    """

    def __init__(self):
        self._lock = threading.RLock()

        # IP-based rate limiting (sliding window)
        self.ip_requests = defaultdict(deque)  # IP -> deque of timestamps
        self.ip_penalties = defaultdict(int)  # IP -> penalty multiplier

        # Webhook ID-based rate limiting
        self.webhook_requests = defaultdict(deque)  # webhook_id -> timestamps

        # Global rate limiting
        self.global_requests = deque()  # Global request timestamps

        # Configuration (can be overridden in site_config.json)
        webhook_config = frappe.conf.get("webhook_rate_limiting", {})

        # Limits per minute
        self.ip_limit = cint(webhook_config.get("ip_limit_per_minute", 20))
        self.webhook_id_limit = cint(webhook_config.get("webhook_id_limit_per_minute", 5))
        self.global_limit = cint(webhook_config.get("global_limit_per_minute", 200))

        # Time windows
        self.time_window = 60  # 1 minute in seconds

        # Progressive penalty settings
        self.penalty_threshold = 3  # Number of violations before penalties start
        self.max_penalty_multiplier = 10

        # Cleanup interval (remove old entries every 5 minutes)
        self.last_cleanup = time.time()
        self.cleanup_interval = 300

    def check_rate_limit(self, ip_address: str, webhook_id: Optional[str] = None) -> Tuple[bool, str]:
        """
        Check if request should be rate limited

        Args:
            ip_address: Source IP address
            webhook_id: Webhook identifier (optional)

        Returns:
            Tuple[bool, str]: (is_allowed, reason_if_blocked)
        """
        with self._lock:
            current_time = time.time()

            # Cleanup old entries periodically
            self._cleanup_old_entries(current_time)

            # Check global rate limit first (most critical)
            if not self._check_global_limit(current_time):
                frappe.log_error(
                    f"Global webhook rate limit exceeded: {len(self.global_requests)} requests in last minute",
                    "Webhook DDoS Protection",
                )
                return False, f"System overloaded. Global rate limit exceeded ({self.global_limit}/min)"

            # Check IP-based rate limit with penalties
            ip_allowed, ip_reason = self._check_ip_limit(ip_address, current_time)
            if not ip_allowed:
                return False, ip_reason

            # Check webhook ID rate limit (if provided)
            if webhook_id:
                webhook_allowed, webhook_reason = self._check_webhook_id_limit(webhook_id, current_time)
                if not webhook_allowed:
                    return False, webhook_reason

            # All checks passed - record the request
            self._record_request(ip_address, webhook_id, current_time)

            return True, "Request allowed"

    def _check_global_limit(self, current_time: float) -> bool:
        """Check global rate limit across all webhooks"""
        # Remove requests older than time window
        while self.global_requests and current_time - self.global_requests[0] > self.time_window:
            self.global_requests.popleft()

        return len(self.global_requests) < self.global_limit

    def _check_ip_limit(self, ip_address: str, current_time: float) -> Tuple[bool, str]:
        """Check IP-based rate limit with progressive penalties"""
        requests = self.ip_requests[ip_address]

        # Remove old requests
        while requests and current_time - requests[0] > self.time_window:
            requests.popleft()

        # Apply progressive penalties for repeat offenders
        penalty_multiplier = min(self.ip_penalties[ip_address], self.max_penalty_multiplier)
        effective_limit = max(1, self.ip_limit // (1 + penalty_multiplier))

        if len(requests) >= effective_limit:
            # Increase penalty for this IP
            self.ip_penalties[ip_address] += 1

            frappe.log_error(
                f"IP rate limit exceeded: {ip_address} made {len(requests)} requests "
                f"(limit: {effective_limit}, penalty: {penalty_multiplier}x)",
                "Webhook Rate Limiting",
            )

            penalty_note = f" (penalty: {penalty_multiplier}x)" if penalty_multiplier > 0 else ""
            return (
                False,
                f"IP rate limit exceeded: {len(requests)}/{effective_limit} per minute{penalty_note}",
            )

        return True, "IP rate limit check passed"

    def _check_webhook_id_limit(self, webhook_id: str, current_time: float) -> Tuple[bool, str]:
        """Check webhook ID-based rate limit (prevents duplicate webhook spam)"""
        requests = self.webhook_requests[webhook_id]

        # Remove old requests
        while requests and current_time - requests[0] > self.time_window:
            requests.popleft()

        if len(requests) >= self.webhook_id_limit:
            frappe.log_error(
                f"Webhook ID rate limit exceeded: {webhook_id} processed {len(requests)} times in last minute",
                "Webhook Duplicate Protection",
            )
            return (
                False,
                f"Webhook processed too frequently: {len(requests)}/{self.webhook_id_limit} per minute",
            )

        return True, "Webhook ID rate limit check passed"

    def _record_request(self, ip_address: str, webhook_id: Optional[str], current_time: float):
        """Record successful request for rate limiting tracking"""
        # Record for global limit
        self.global_requests.append(current_time)

        # Record for IP limit
        self.ip_requests[ip_address].append(current_time)

        # Record for webhook ID limit
        if webhook_id:
            self.webhook_requests[webhook_id].append(current_time)

        # Reset penalty if IP is behaving well
        if len(self.ip_requests[ip_address]) < self.ip_limit // 2:
            if self.ip_penalties[ip_address] > 0:
                self.ip_penalties[ip_address] = max(0, self.ip_penalties[ip_address] - 1)

    def _cleanup_old_entries(self, current_time: float):
        """Clean up old entries to prevent memory leaks"""
        if current_time - self.last_cleanup < self.cleanup_interval:
            return

        # Clean up IP requests older than 2 time windows
        cleanup_threshold = current_time - (2 * self.time_window)

        # Clean IP requests
        for ip, requests in list(self.ip_requests.items()):
            while requests and requests[0] < cleanup_threshold:
                requests.popleft()
            if not requests:
                del self.ip_requests[ip]
                # Also clean up penalties for IPs with no recent requests
                if ip in self.ip_penalties:
                    del self.ip_penalties[ip]

        # Clean webhook requests
        for webhook_id, requests in list(self.webhook_requests.items()):
            while requests and requests[0] < cleanup_threshold:
                requests.popleft()
            if not requests:
                del self.webhook_requests[webhook_id]

        # Clean global requests
        while self.global_requests and self.global_requests[0] < cleanup_threshold:
            self.global_requests.popleft()

        self.last_cleanup = current_time

        # Log cleanup stats
        frappe.logger().info(
            f"Webhook rate limiter cleanup: {len(self.ip_requests)} IPs tracked, "
            f"{len(self.webhook_requests)} webhook IDs tracked, "
            f"{len(self.global_requests)} global requests in window"
        )

    def get_stats(self) -> Dict:
        """Get current rate limiting statistics for monitoring"""
        with self._lock:
            current_time = time.time()

            # Count recent requests
            recent_global = sum(1 for ts in self.global_requests if current_time - ts <= self.time_window)
            recent_ips = len(
                [
                    ip
                    for ip, requests in self.ip_requests.items()
                    if any(current_time - ts <= self.time_window for ts in requests)
                ]
            )

            return {
                "global_requests_per_minute": recent_global,
                "global_limit": self.global_limit,
                "active_ips": recent_ips,
                "total_tracked_ips": len(self.ip_requests),
                "penalized_ips": len(self.ip_penalties),
                "tracked_webhook_ids": len(self.webhook_requests),
                "utilization_percent": (
                    (recent_global / self.global_limit) * 100 if self.global_limit > 0 else 0
                ),
            }

    def reset_ip_penalty(self, ip_address: str):
        """Reset penalty for a specific IP (for admin use)"""
        with self._lock:
            if ip_address in self.ip_penalties:
                del self.ip_penalties[ip_address]
                frappe.logger().info(f"Reset rate limit penalty for IP: {ip_address}")


# Global rate limiter instance
_webhook_rate_limiter = None
_limiter_lock = threading.Lock()


def get_webhook_rate_limiter() -> WebhookRateLimiter:
    """Get or create global webhook rate limiter instance"""
    global _webhook_rate_limiter

    if _webhook_rate_limiter is None:
        with _limiter_lock:
            if _webhook_rate_limiter is None:
                _webhook_rate_limiter = WebhookRateLimiter()

    return _webhook_rate_limiter


def reset_rate_limiter():
    """Reset rate limiter (for testing)"""
    global _webhook_rate_limiter
    with _limiter_lock:
        _webhook_rate_limiter = None


@frappe.whitelist(allow_guest=True)
def get_webhook_rate_limit_stats():
    """API endpoint to get rate limiting statistics"""
    # Only allow this for system managers
    if not frappe.has_permission("System Settings", "read"):
        frappe.throw("Insufficient permissions to view rate limit statistics")

    limiter = get_webhook_rate_limiter()
    return limiter.get_stats()
