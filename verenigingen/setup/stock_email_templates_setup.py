"""Create the stock Email Templates that are missing, on every migrate (#1984).

Six stock templates used to ship as fixtures, which Frappe re-imports on EVERY migrate and so
overwrote staff edits (maintainer ruling 2026-11-26). They are seeded here instead: only rows
that do not exist are created, so a fresh site and an upgraded one both converge, and an
existing (possibly edited) row is never touched. Restoring stock text is the explicit
``reset_stock_email_templates`` action.
"""


def ensure_stock_email_templates():
    """after_migrate: create missing stock templates; never update an existing one."""
    from verenigingen.api.email_template_manager import _seed_comprehensive_email_templates

    result = _seed_comprehensive_email_templates(overwrite=False)
    if not result.success:
        # Not swallowed (#1880): a missing template is a silent skipped mail later.
        raise RuntimeError(f"Stock email templates could not be created: {result.errors}")
