"""Site-aware lazy loggers for the service layer.

Why this exists
---------------
`logging.getLogger("verenigingen.services.Foo")` returns a logger that Frappe
has never configured. Frappe attaches its `RotatingFileHandler`s inside
`frappe.logger()`, under the name `"{module}-{site}"` (see
`frappe/utils/logger.py:get_logger`), so a bare stdlib name matches nothing and
has no handler. Records then fall through to Python's `lastResort` handler,
which writes WARNING and above to stderr — captured by supervisor into
`logs/web.error.log` / `logs/worker.error.log`, unformatted and untimestamped,
and `.info()`/`.debug()` discarded entirely. That is how the failure behind
MijnRood Sync Event MR-SYNC-2026-00087 came to be near-invisible.

Note the consequence of fixing it: `frappe.logger()` sets `propagate = False`,
so records now go to `sites/<site>/logs/<name>.log` and STOP appearing in
`web.error.log` / `worker.error.log`.

Why lazy
--------
`frappe.logger()` binds its handler to `frappe.local.site`, but the services
that use it are module-level singletons that outlive a single request. Calling
`frappe.logger()` once in `__init__` would pin the first site's log file for
every later request on a multi-site bench. Resolving on each attribute access
keeps the logger correct per request; `frappe.logger()` memoises per site in
`frappe.loggers`, so the lookup is a dict hit.

Why one name per domain, not per class
--------------------------------------
`frappe.logger()` eagerly opens TWO `RotatingFileHandler`s per distinct name per
site (bench-level and site-level) and caches them for the process lifetime. One
name per service class would mean ~115 names, i.e. ~230 open file descriptors
per worker and ~115 mostly-empty files per site. So callers share a domain name
and pass `prefix=` to keep the per-service identity in the message text, which
matches Frappe's own one-logger-per-module convention.

Usage:
    from verenigingen.utils.service_logger import get_service_logger

    logger = get_service_logger("verenigingen.mijnrood_sync", prefix="polling")
    logger.error("run %s aborted", run_id)
    # -> sites/<site>/logs/verenigingen.mijnrood_sync.log
    #    "... ERROR verenigingen.mijnrood_sync polling: run abc aborted"

Levels: Frappe defaults these loggers to ERROR (WARNING on a dev server), so
`.info()`/`.debug()` stay invisible unless the site raises `log_level`. That is
Frappe's convention, not a limitation of this shim — do not rely on these for
audit trails.
"""

import logging
import warnings

import frappe

# Methods whose first positional argument is the message, so a prefix can be
# prepended without disturbing %-style args or keywords like exc_info.
_MESSAGE_FIRST = frozenset({"debug", "info", "warning", "warn", "error", "exception", "critical", "fatal"})

# Emit the "logging is broken" warning once per process, not once per call —
# a logger that cannot open its file would otherwise warn in a tight loop.
_fallback_warned = False


class LazyServiceLogger:
    """Proxies attribute access to `frappe.logger(name)`, resolved per call.

    `setLevel`/`addHandler` through this proxy mutate the process-global Frappe
    logger for the domain, not a private one. Nothing in the app does that; if
    you need per-service levels, this is the wrong tool.
    """

    __slots__ = ("_name", "_prefix")

    def __init__(self, name: str, prefix: str = "") -> None:
        self._name = name
        self._prefix = prefix

    def _resolve(self) -> logging.Logger:
        global _fallback_warned
        try:
            return frappe.logger(self._name)
        except Exception as exc:
            # Logging must never break the caller. frappe.logger() opens a
            # RotatingFileHandler eagerly against a path relative to the sites
            # directory, so it fails outside a site context or when logs/ is not
            # writable. Degrade to the bare stdlib logger — but say so once,
            # rather than silently reinstating the bug this module exists to fix.
            if not _fallback_warned:
                _fallback_warned = True
                warnings.warn(
                    f"frappe.logger({self._name!r}) failed ({exc}); service logging is "
                    "falling back to an unconfigured logger and will be discarded",
                    RuntimeWarning,
                    stacklevel=3,
                )
            return logging.getLogger(self._name)

    def __getattr__(self, attr: str):
        target = getattr(self._resolve(), attr)
        if self._prefix and attr in _MESSAGE_FIRST:
            return _with_prefix(target, self._prefix)
        return target

    def __repr__(self) -> str:
        suffix = f" prefix={self._prefix}" if self._prefix else ""
        return f"<LazyServiceLogger {self._name}{suffix}>"


def _with_prefix(log_method, prefix: str):
    """Wrap a logger method so `prefix` is prepended to the format string.

    Only the message is touched, so %-style args and keywords (exc_info,
    stacklevel, extra) pass through untouched.
    """

    def wrapper(msg, *args, **kwargs):
        return log_method(f"{prefix}: {msg}", *args, **kwargs)

    return wrapper


def get_service_logger(name: str, prefix: str = "") -> LazyServiceLogger:
    """Return a site-aware lazy logger for the domain `name`.

    Args:
        name: Domain-level logger name, e.g. "verenigingen.services". Shared by
            many callers on purpose — see the module docstring.
        prefix: Identifies the specific caller within the domain; prepended to
            every message.

    Safe to call at module import time — nothing touches `frappe.local` until
    the first log call.
    """
    return LazyServiceLogger(name, prefix)
