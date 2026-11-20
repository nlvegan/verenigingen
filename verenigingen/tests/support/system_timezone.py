"""Pin ``System Settings.time_zone`` for a block of a test (#2162)."""

from contextlib import contextmanager

import frappe


@contextmanager
def system_timezone(zone):
    """Pin System Settings.time_zone to ``zone`` for the block; restored on exit.

    Test sites are Asia/Kolkata, CI is UTC and the association's site is
    Europe/Amsterdam, so a date that depends on the site zone has to name its zone.
    ``frappe.clear_cache()`` inside the block would drop the pin.
    """
    original = getattr(frappe.local, "system_settings", None)
    try:
        settings = frappe.get_doc("System Settings")
        settings.time_zone = zone
        frappe.local.system_settings = settings
        if frappe.utils.get_system_timezone() != zone:
            raise RuntimeError(f"could not pin the system timezone to {zone}")
        yield
    finally:
        frappe.local.system_settings = original
