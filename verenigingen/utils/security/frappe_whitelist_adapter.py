"""
Frappe Whitelist Adapter for API Security Framework

Façade for Frappe whitelist registration. Encapsulates the complex logic
for registering decorated functions with Frappe's whitelist system.

DEPENDENCY RULES:
- MAY use Frappe for whitelist registration
- MUST NOT import from api_security_framework.py (to avoid circular imports)
- MUST NOT import from other security modules (standalone adapter)
"""

from typing import Callable, List, Optional

import frappe


def _safe_debug_log(message: str) -> None:
    """Safely log debug messages, handling cases where Frappe isn't fully initialized.

    This is needed because decorators execute at import time, before Frappe has
    a site context. frappe.logger() fails without a site context.
    """
    try:
        # Check if we have a valid site context
        if hasattr(frappe.local, "site") and frappe.local.site:
            frappe.logger("verenigingen.security").debug(message)
    except Exception:
        # Silently ignore logging failures during import
        pass


class FrappeWhitelistAdapter:
    """
    Façade for Frappe whitelist registration.

    This class encapsulates the complex logic for registering decorated
    functions with Frappe's whitelist system. It handles:
    - Attribute preservation through decorator chains
    - Adding wrappers to frappe.whitelisted collection
    - Registering HTTP methods in allowed_http_methods_for_whitelisted_func

    INVARIANTS:
    - Never adds non-whitelisted functions to Frappe's whitelist (fail-closed)
    - Preserves HTTP method restrictions from inner function
    - Defaults to POST-only when no methods specified (security default)
    """

    def preserve_whitelist_attribute(self, wrapper: Callable, func: Callable) -> None:
        """
        Preserve __func_is_whitelisted__ attribute from inner function to wrapper.

        This handles the complex chain of decorators and wrapped functions
        that may occur in real-world usage.
        """
        # First, check direct attribute
        if hasattr(func, "__func_is_whitelisted__"):
            wrapper.__func_is_whitelisted__ = func.__func_is_whitelisted__
            _safe_debug_log(f"Preserved __func_is_whitelisted__ from func: {func.__func_is_whitelisted__}")
            return

        # Check for allow_guest attribute (legacy pattern)
        if hasattr(func, "allow_guest") and func.allow_guest:
            wrapper.__func_is_whitelisted__ = True
            _safe_debug_log("Set __func_is_whitelisted__ from allow_guest")
            return

        # Check wrapped function if exists
        if hasattr(func, "__wrapped__"):
            wrapped_func = func.__wrapped__
            if hasattr(wrapped_func, "__func_is_whitelisted__"):
                wrapper.__func_is_whitelisted__ = wrapped_func.__func_is_whitelisted__
                _safe_debug_log(
                    f"Preserved __func_is_whitelisted__ from wrapped: {wrapped_func.__func_is_whitelisted__}"
                )
                return

            # Go deeper if needed
            if hasattr(wrapped_func, "__wrapped__") and hasattr(
                wrapped_func.__wrapped__, "__func_is_whitelisted__"
            ):
                wrapper.__func_is_whitelisted__ = wrapped_func.__wrapped__.__func_is_whitelisted__
                _safe_debug_log(
                    f"Preserved __func_is_whitelisted__ from deep wrapped: "
                    f"{wrapped_func.__wrapped__.__func_is_whitelisted__}"
                )
                return

        # Fallback: check if function is in Frappe's whitelist registry
        if not hasattr(wrapper, "__func_is_whitelisted__"):
            method_path = f"{func.__module__}.{func.__name__}"
            if method_path in getattr(frappe, "_whitelisted_methods", set()):
                wrapper.__func_is_whitelisted__ = True
                _safe_debug_log(f"Set __func_is_whitelisted__ from whitelist registry for {method_path}")
            else:
                # SECURITY FIX: Fail-closed behavior - do NOT assume whitelisted
                frappe.logger("verenigingen.api_security").warning(
                    f"Security decorator applied to function {method_path} which is not in "
                    f"Frappe's whitelist registry. Function will NOT be treated as whitelisted. "
                    f"Ensure @frappe.whitelist() is applied BEFORE security decorators."
                )
                _safe_debug_log(f"Fail-closed: NOT setting __func_is_whitelisted__ for {method_path}")

    def preserve_common_attributes(self, wrapper: Callable, func: Callable) -> None:
        """Preserve other common Frappe attributes from inner function."""
        for attr in ["allow_guest", "_original_func_name"]:
            if hasattr(func, attr):
                setattr(wrapper, attr, getattr(func, attr))

    def is_inner_whitelisted(self, func: Callable) -> bool:
        """Check if the inner function was whitelisted."""
        if not hasattr(frappe, "whitelisted"):
            return False
        return (
            func in frappe.whitelisted
            or getattr(func, "__func_is_whitelisted__", False)
            or (hasattr(func, "__wrapped__") and func.__wrapped__ in frappe.whitelisted)
        )

    def register_wrapper_in_whitelist(self, wrapper: Callable, func: Callable) -> None:
        """
        Add wrapper to Frappe's whitelist collection.

        Frappe's is_whitelisted() checks `if method not in whitelisted`,
        NOT function attributes. We must explicitly add our wrapper.
        """
        if not hasattr(frappe, "whitelisted"):
            return

        if self.is_inner_whitelisted(func):
            # Handle both set and list types (Frappe version differences)
            if isinstance(frappe.whitelisted, set):
                frappe.whitelisted.add(wrapper)
            elif isinstance(frappe.whitelisted, list):
                if wrapper not in frappe.whitelisted:
                    frappe.whitelisted.append(wrapper)
            _safe_debug_log(f"Added wrapper to frappe.whitelisted for {func.__name__}")

    def get_allowed_http_methods(self, func: Callable) -> Optional[List[str]]:
        """Get allowed HTTP methods for a function from Frappe's registry."""
        if not hasattr(frappe, "allowed_http_methods_for_whitelisted_func"):
            return None

        http_methods_dict = frappe.allowed_http_methods_for_whitelisted_func

        if func in http_methods_dict:
            return http_methods_dict[func]
        if hasattr(func, "__wrapped__") and func.__wrapped__ in http_methods_dict:
            return http_methods_dict[func.__wrapped__]

        return None

    def register_http_methods(self, wrapper: Callable, func: Callable) -> None:
        """
        Register allowed HTTP methods for wrapper in Frappe's dict.

        SECURITY: Defaults to POST-only when no methods are specified.
        """
        if not hasattr(frappe, "allowed_http_methods_for_whitelisted_func"):
            return

        http_methods_dict = frappe.allowed_http_methods_for_whitelisted_func
        allowed_methods = self.get_allowed_http_methods(func)

        if allowed_methods is not None:
            http_methods_dict[wrapper] = allowed_methods
            _safe_debug_log(
                f"Added wrapper to allowed_http_methods_for_whitelisted_func for {func.__name__}: {allowed_methods}"
            )
        elif self.is_inner_whitelisted(func):
            # SECURITY FIX: Default to POST only for stricter security
            http_methods_dict[wrapper] = ["POST"]
            _safe_debug_log(
                f"Added wrapper to allowed_http_methods_for_whitelisted_func with "
                f"security default (POST only) for {func.__name__}"
            )

    def register_wrapper(self, wrapper: Callable, func: Callable) -> None:
        """
        Complete registration of wrapper with Frappe's whitelist system.

        This is the main entry point that performs all registration steps.
        """
        self.preserve_whitelist_attribute(wrapper, func)
        self.preserve_common_attributes(wrapper, func)
        self.register_wrapper_in_whitelist(wrapper, func)
        self.register_http_methods(wrapper, func)


# Singleton instance for convenience
_frappe_whitelist_adapter: Optional[FrappeWhitelistAdapter] = None


def get_frappe_whitelist_adapter() -> FrappeWhitelistAdapter:
    """Get singleton FrappeWhitelistAdapter instance."""
    global _frappe_whitelist_adapter
    if _frappe_whitelist_adapter is None:
        _frappe_whitelist_adapter = FrappeWhitelistAdapter()
    return _frappe_whitelist_adapter
