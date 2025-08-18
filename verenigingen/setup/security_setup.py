#!/usr/bin/env python3
"""
Security setup for Verenigingen application
Ensures proper security configuration during installation
"""

import secrets
import string
import time
from functools import wraps

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

# Import and initialize the security logger configuration
try:
    from verenigingen.utils.logger_config import get_security_logger

    # Initialize the logger with proper file path configuration
    security_logger = get_security_logger()
except ImportError:
    # Fallback to standard Frappe logger if config not available
    security_logger = frappe.logger("verenigingen.security")


def security_rate_limit(limit=5, seconds=60):
    """
    Custom rate limiter for security endpoints with enhanced logging.
    Default: 5 attempts per minute per user.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Use Frappe's built-in rate limiting
            key = f"security_rate_limit:{frappe.session.user}:{func.__name__}"

            # Check rate limit
            from frappe.cache import cache
            from frappe.utils import cint

            # Get current count
            count = cint(cache().get(key) or 0)

            if count >= limit:
                # Log rate limit exceeded
                log_security_audit(
                    "Rate Limit Exceeded",
                    {
                        "function": func.__name__,
                        "user": frappe.session.user,
                        "limit": limit,
                        "seconds": seconds,
                    },
                )

                frappe.throw(
                    _("Too many security configuration attempts. Please wait before trying again."),
                    frappe.RateLimitExceededError,
                )

            # Increment counter
            cache().setex(key, seconds, count + 1)

            # Execute function
            return func(*args, **kwargs)

        return wrapper

    return decorator


def validate_csrf_token():
    """
    Validate CSRF token for security operations.
    """
    if not frappe.conf.get("ignore_csrf", 0):
        # CSRF is enabled, validate token
        csrf_token = frappe.local.form_dict.get("csrf_token") or frappe.get_request_header(
            "X-Frappe-CSRF-Token"
        )

        if not csrf_token:
            frappe.throw(_("CSRF token missing"), frappe.CSRFTokenError)

        # Validate token using Frappe's built-in validation
        from frappe.sessions import validate_csrf_token as frappe_validate_csrf

        try:
            frappe_validate_csrf(csrf_token)
        except Exception:
            frappe.throw(_("Invalid CSRF token"), frappe.CSRFTokenError)


def setup_csrf_protection():
    """
    Setup CSRF protection for the site during app installation.

    This function ensures:
    1. CSRF protection is enabled (ignore_csrf = 0)
    2. A secure CSRF token is generated if needed
    3. Session security settings are properly configured
    """
    try:
        print("🔒 Setting up CSRF protection...")

        # Get site config
        site = frappe.local.site

        # Load current site config
        site_config = frappe.get_site_config()

        # Check current CSRF setting
        ignore_csrf = site_config.get("ignore_csrf", 0)

        if ignore_csrf:
            print("   ⚠️  CSRF protection is currently disabled (ignore_csrf=1)")

            # In development mode, we might want to keep it disabled
            # but warn the user
            if site_config.get("developer_mode"):
                print("   ℹ️  Developer mode detected. CSRF protection remains disabled for development.")
                print("   ⚠️  WARNING: Enable CSRF protection in production!")
                print("   💡 To enable CSRF protection, run:")
                print("      bench --site {} set-config ignore_csrf 0".format(site))

                # Add a comment to site config about this
                return {
                    "status": "skipped",
                    "message": "CSRF protection skipped in developer mode",
                    "recommendation": "Enable CSRF protection before deploying to production",
                }
            else:
                # Production mode - enable CSRF protection
                print("   ✅ Enabling CSRF protection for production...")
                frappe.conf.ignore_csrf = 0

                # Update site config
                from frappe.installer import update_site_config

                update_site_config("ignore_csrf", 0)

                print("   ✅ CSRF protection enabled")

                return {"status": "enabled", "message": "CSRF protection enabled successfully"}
        else:
            print("   ✅ CSRF protection is already enabled")
            return {"status": "already_enabled", "message": "CSRF protection was already enabled"}

    except Exception as e:
        print(f"   ❌ Error setting up CSRF protection: {str(e)}")
        return {"status": "error", "message": str(e)}


def generate_session_secret():
    """
    Generate a secure session secret if not already present.
    This is used for signing session cookies.
    """
    try:
        site_config = frappe.get_site_config()

        # Check if secret key already exists
        if not site_config.get("secret_key"):
            # Generate a secure random secret
            alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
            secret_key = "".join(secrets.choice(alphabet) for _ in range(64))

            # Update site config
            from frappe.installer import update_site_config

            update_site_config("secret_key", secret_key)

            print("   ✅ Generated new session secret key")
            return True
        else:
            print("   ✅ Session secret key already exists")
            return False

    except Exception as e:
        print(f"   ⚠️  Could not generate session secret: {str(e)}")
        return False


def setup_security_headers():
    """
    Configure recommended security headers for the application.
    These are suggestions that can be added to nginx configuration.
    """
    security_recommendations = {
        "X-Frame-Options": "SAMEORIGIN",
        "X-Content-Type-Options": "nosniff",
        "X-XSS-Protection": "1; mode=block",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "Content-Security-Policy": "default-src 'self' 'unsafe-inline' 'unsafe-eval'; img-src 'self' data: https:; font-src 'self' data:;",
    }

    print("   ℹ️  Recommended security headers for nginx configuration:")
    for header, value in security_recommendations.items():
        print(f'      add_header {header} "{value}";')

    return security_recommendations


def setup_password_policy():
    """
    Configure password policy settings for the verenigingen app.
    """
    try:
        # Get or create System Settings
        system_settings = frappe.get_single("System Settings")

        # Set recommended password policy (enhanced based on security review)
        password_policy = {
            "minimum_password_score": 3,  # 0-4 scale, 3 is strong (increased from 2)
            "enable_password_policy": 1,
            "force_user_to_reset_password": 90,  # Days
        }

        updated = False
        for field, value in password_policy.items():
            if hasattr(system_settings, field):
                current_value = getattr(system_settings, field)
                if current_value != value:
                    setattr(system_settings, field, value)
                    updated = True

        if updated:
            system_settings.save(ignore_permissions=True)
            print("   ✅ Password policy configured")
        else:
            print("   ✅ Password policy already configured")

        return True

    except Exception as e:
        print(f"   ⚠️  Could not configure password policy: {str(e)}")
        return False


def check_security_status():
    """
    Check the current security configuration status.
    Returns a dict with security status information.
    """
    site_config = frappe.get_site_config()

    status = {
        "csrf_protection": not site_config.get("ignore_csrf", 0),
        "developer_mode": site_config.get("developer_mode", 0),
        "encryption_key": bool(site_config.get("encryption_key")),
        "secret_key": bool(site_config.get("secret_key")),
        "session_expiry": site_config.get("session_expiry", "06:00:00"),
        "session_expiry_mobile": site_config.get("session_expiry_mobile", "720:00:00"),
        "allow_tests": site_config.get("allow_tests", False),
    }

    # Calculate security score
    score = 0
    max_score = 0

    # CSRF protection (critical)
    max_score += 3
    if status["csrf_protection"]:
        score += 3

    # Encryption key (critical)
    max_score += 2
    if status["encryption_key"]:
        score += 2

    # Secret key (important)
    max_score += 2
    if status["secret_key"]:
        score += 2

    # Developer mode off (important for production)
    max_score += 2
    if not status["developer_mode"]:
        score += 2

    # Tests disabled (minor)
    max_score += 1
    if not status["allow_tests"]:
        score += 1

    status["security_score"] = f"{score}/{max_score}"
    status["security_percentage"] = (score / max_score * 100) if max_score > 0 else 0

    # Add recommendations
    recommendations = []
    if not status["csrf_protection"]:
        recommendations.append("Enable CSRF protection (set ignore_csrf to 0)")
    if status["developer_mode"]:
        recommendations.append("Disable developer mode in production")
    if status["allow_tests"]:
        recommendations.append("Disable test mode in production")
    if not status["encryption_key"]:
        recommendations.append("Generate an encryption key for sensitive data")
    if not status["secret_key"]:
        recommendations.append("Generate a secret key for session security")

    status["recommendations"] = recommendations

    return status


def log_security_audit(action, details, user=None):
    """
    Log security-related actions for audit purposes.

    Args:
        action: The security action taken
        details: Dictionary with action details
        user: User performing the action (defaults to current user)
    """
    try:
        user = user or frappe.session.user

        # Create comment for audit trail (more flexible than Activity Log)
        frappe.get_doc(
            {
                "doctype": "Comment",
                "comment_type": "Info",
                "reference_doctype": "System Settings",
                "reference_name": "System Settings",
                "subject": f"Security Configuration: {action}",
                "content": f"<b>Security Action:</b> {action}<br>"
                f"<b>User:</b> {user}<br>"
                f"<b>Details:</b> <pre>{frappe.as_json(details, indent=2)}</pre>",
                "comment_by": user,
                "ip_address": frappe.local.request_ip if hasattr(frappe.local, "request_ip") else None,
            }
        ).insert(ignore_permissions=True)

        # Also log to security-specific log file using configured logger
        security_logger.info(f"SECURITY AUDIT: {action} by {user} - {frappe.as_json(details)}")

    except Exception as e:
        # Don't fail the main operation if logging fails
        security_logger.error(f"Failed to log security audit: {str(e)}")


def setup_all_security():
    """
    Main function to set up all security configurations.
    Called during app installation.
    """
    print("🔐 Setting up security configurations...")

    # Log the security setup initiation
    log_security_audit(
        "Security Setup Started",
        {"triggered_by": "app_installation", "timestamp": frappe.utils.now_datetime()},
    )

    results = {
        "csrf": setup_csrf_protection(),
        "session_secret": generate_session_secret(),
        "password_policy": setup_password_policy(),
        "security_headers": setup_security_headers(),
    }

    # Check final status
    final_status = check_security_status()
    results["final_status"] = final_status

    print(
        f"   📊 Security Score: {final_status['security_score']} ({final_status['security_percentage']:.0f}%)"
    )

    if final_status["recommendations"]:
        print("   ⚠️  Security Recommendations:")
        for rec in final_status["recommendations"]:
            print(f"      - {rec}")

    # Log the completion with results
    log_security_audit(
        "Security Setup Completed",
        {
            "results": results,
            "security_score": final_status["security_score"],
            "recommendations": final_status.get("recommendations", []),
        },
    )

    print("✅ Security setup completed")

    return results


# API Endpoints for manual security management


@frappe.whitelist()
@rate_limit(limit=5, seconds=60)  # 5 attempts per minute
@security_rate_limit(limit=3, seconds=300)  # Additional: 3 attempts per 5 minutes
def enable_csrf_protection():
    """Manually enable CSRF protection."""
    # Validate CSRF token if protection is enabled
    validate_csrf_token()

    # Check permissions
    if not frappe.has_permission("System Settings", "write"):
        frappe.throw(_("Insufficient permissions"), frappe.PermissionError)

    try:
        # Log the attempt
        log_security_audit(
            "CSRF Protection Enable Attempted",
            {"user": frappe.session.user, "timestamp": frappe.utils.now_datetime()},
        )

        from frappe.installer import update_site_config

        update_site_config("ignore_csrf", 0)

        frappe.clear_cache()

        # Log success
        log_security_audit("CSRF Protection Enabled", {"user": frappe.session.user, "success": True})

        return {
            "success": True,
            "message": "CSRF protection enabled successfully",
            "note": "You may need to restart the bench for changes to take full effect",
        }
    except Exception as e:
        # Log failure
        log_security_audit("CSRF Protection Enable Failed", {"user": frappe.session.user, "error": str(e)})

        return {"success": False, "message": str(e)}


@frappe.whitelist()
@rate_limit(limit=10, seconds=60)  # 10 attempts per minute (read-only, less restrictive)
def check_current_security_status():
    """Check current security configuration status."""
    # No CSRF validation needed for read-only operation
    try:
        # Log the security status check for audit purposes
        # Even read operations should be logged for reconnaissance detection
        log_security_audit(
            "Security Status Check",
            {
                "user": frappe.session.user,
                "timestamp": frappe.utils.now_datetime(),
                "ip_address": frappe.local.request_ip if hasattr(frappe.local, "request_ip") else None,
            },
        )

        status = check_security_status()

        # Log if any critical security issues are found
        if status.get("security_percentage", 100) < 50:
            log_security_audit(
                "Low Security Score Detected",
                {
                    "user": frappe.session.user,
                    "score": status.get("security_score"),
                    "percentage": status.get("security_percentage"),
                },
            )

        return {"success": True, "status": status}
    except Exception as e:
        # Log failed attempts as well
        log_security_audit("Security Status Check Failed", {"user": frappe.session.user, "error": str(e)})
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def apply_production_security():
    """Apply recommended security settings for production."""
    # Check permissions
    if not frappe.has_permission("System Settings", "write"):
        frappe.throw(_("Insufficient permissions"), frappe.PermissionError)

    try:
        # Log the attempt
        log_security_audit(
            "Production Security Apply Attempted",
            {
                "user": frappe.session.user,
                "timestamp": frappe.utils.now_datetime(),
                "current_mode": "developer" if frappe.conf.developer_mode else "production",
            },
        )

        from frappe.installer import update_site_config

        changes = []

        # Disable developer mode
        if frappe.conf.developer_mode:
            update_site_config("developer_mode", 0)
            changes.append("Disabled developer mode")

        # Enable CSRF protection
        if frappe.conf.get("ignore_csrf"):
            update_site_config("ignore_csrf", 0)
            changes.append("Enabled CSRF protection")

        # Disable tests
        if frappe.conf.get("allow_tests"):
            update_site_config("allow_tests", 0)
            changes.append("Disabled test mode")

        # Generate session secret if missing
        if not frappe.conf.get("secret_key"):
            if generate_session_secret():
                changes.append("Generated session secret")

        # Clear cache
        frappe.clear_cache()

        # Log success with changes
        log_security_audit(
            "Production Security Applied", {"user": frappe.session.user, "changes": changes, "success": True}
        )

        return {
            "success": True,
            "message": f"Applied {len(changes)} security changes",
            "changes": changes,
            "note": "Restart bench for all changes to take effect",
        }

    except Exception as e:
        # Log failure
        log_security_audit("Production Security Apply Failed", {"user": frappe.session.user, "error": str(e)})

        return {"success": False, "message": str(e)}


if __name__ == "__main__":
    # Run security setup
    setup_all_security()
