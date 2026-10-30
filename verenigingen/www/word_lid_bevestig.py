"""Confirm page of the short application. A GET only renders a button; the POST confirms."""

import frappe
from frappe import _


def get_context(context):
    # No confirm logic and no DB access here: mail scanners and link previewers issue GETs.
    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Confirm your application")
    context.submission = frappe.form_dict.get("submission") or ""
    context.token = frappe.form_dict.get("token") or ""
    brand_settings = frappe.get_single("Brand Settings")
    context.primary_color = getattr(brand_settings, "primary_color", None) or "#cf3131"
    return context
