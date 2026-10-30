"""Short membership application: landing page (/word-lid) and per-door form (/word-lid/<door>)."""

import frappe
from frappe import _

DOOR_DOCTYPE = "Membership Application Door"
FREQUENCIES = ("Monthly", "Annual")


def get_context(context):
    context.no_cache = 1
    context.show_sidebar = False
    _apply_branding(context)
    door_slug = frappe.form_dict.get("door")
    if door_slug:
        _load_door(context, door_slug)
    else:
        _load_landing(context)
    return context


def _apply_branding(context):
    brand_settings = frappe.get_single("Brand Settings")
    context.organization_logo = getattr(brand_settings, "logo", None)
    context.primary_color = getattr(brand_settings, "primary_color", None) or "#cf3131"
    context.secondary_color = getattr(brand_settings, "secondary_color", None) or "#01796f"


def _load_landing(context):
    context.title = _("Become a member")
    context.door = None
    context.doors = frappe.get_all(
        DOOR_DOCTYPE,
        filters={"enabled": 1},
        fields=["title", "slug", "card_text"],
        order_by="sort_order asc, title asc",
    )


def _load_door(context, door_slug):
    # Missing and disabled doors answer alike, so the page does not reveal which slugs exist.
    if not frappe.db.get_value(DOOR_DOCTYPE, door_slug, "enabled"):
        raise frappe.PageDoesNotExistError
    door = frappe.get_doc(DOOR_DOCTYPE, door_slug)
    context.door = door
    context.title = door.title
    context.hidden = door.hidden()
    context.amount_options = [{"frequency": o.frequency, "amount": o.amount} for o in door.amount_options]
    context.frequencies = [f for f in FREQUENCIES if door.get_template_for(f)]
    context.minimums = {f: _minimums(door, f) for f in context.frequencies}
    context.countries = _available_countries()
    context.join_reasons = _enabled_names("Membership Join Reason", "reason")
    context.referral_sources = _enabled_names("Membership Referral Source", "source")


def _minimums(door, frequency):
    return {"base": door.minimum_for(frequency, False), "postal": door.minimum_for(frequency, True)}


def _enabled_names(doctype, label_field):
    return frappe.get_all(doctype, filters={"enabled": 1}, pluck="name", order_by=f"{label_field} asc")


def _available_countries():
    """Only countries that exist as Country docs (the validator refuses others); Netherlands by default."""
    settings = frappe.get_single("Verenigingen Settings")
    raw = getattr(settings, "available_countries", None) or "Netherlands"
    wanted = [c.strip() for c in raw.split(",") if c.strip()]
    existing = set(frappe.get_all("Country", filters={"name": ["in", wanted]}, pluck="name"))
    return [c for c in wanted if c in existing] or ["Netherlands"]
