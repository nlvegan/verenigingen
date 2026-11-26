"""Escape the typed rejection reason in the four stock rejection Email Templates (#2391).

frappe.render_template does not autoescape, so the bare `{{ reason }}` in these seeded templates put
reviewer-typed markup into the mail body (a reviewer can pick any of them as `email_template`). The
seeder now writes `{{ reason | e }}` (the form this patch also writes), but it only CREATES missing templates (#1984), so existing sites keep
the old rows. A row whose response still equals EXACTLY the old stock text (as STORED: Frappe's Email
Template save minifies inline styles, so this is not the seeder's source text) is updated; a template an
admin edited is left alone. The old texts are frozen here. Idempotent: after the first run nothing matches.
(membership_application_rejected is overridden by the |e fixture on most sites; it is included for sites without.)
"""

import frappe

OLD_STOCK = {
    "membership_application_rejected": """<h3>Membership Application Update</h3>

<p>Dear {{ first_name }},</p>

<p>Thank you for your interest in joining our association.</p>

<p>After careful review, we regret to inform you that your membership application has not been approved at this time.</p>

<div style="background:#fff3cd;border:1px solid #ffeaa7;padding:15px;border-radius:5px;margin:15px 0">
    <p><strong>Application ID:</strong> {{ application_id }}</p>
    <p><strong>Reason:</strong> {{ reason }}</p>
</div>

<p>If you have any questions or would like to discuss this decision, please don't hesitate to contact us.</p>

<p>Best regards,<br>The Membership Team<br>{{ company }}</p>""",
    "membership_rejection_incomplete": """<h3>Membership Application - Additional Information Required</h3>

<p>Dear {{ first_name }},</p>

<p>Thank you for your interest in joining our association.</p>

<p>We have reviewed your membership application, but unfortunately we need additional information to proceed with your application.</p>

<div style="background:#fff3cd;border:1px solid #ffeaa7;padding:15px;border-radius:5px;margin:15px 0">
    <p><strong>Application ID:</strong> {{ application_id }}</p>
    <p><strong>Missing Information:</strong> {{ reason }}</p>
</div>

<p>You are welcome to submit a new application with the complete information at any time. We encourage you to reapply once you have the required documentation or details.</p>

<p>If you have any questions about what information is needed, please don't hesitate to contact us.</p>

<p>Best regards,<br>The Membership Team<br>{{ company }}</p>""",
    "membership_rejection_ineligible": """<h3>Membership Application Update</h3>

<p>Dear {{ first_name }},</p>

<p>Thank you for your interest in joining our association.</p>

<p>After careful review of your application, we regret to inform you that you do not currently meet the eligibility requirements for membership.</p>

<div style="background:#fff3cd;border:1px solid #ffeaa7;padding:15px;border-radius:5px;margin:15px 0">
    <p><strong>Application ID:</strong> {{ application_id }}</p>
    <p><strong>Details:</strong> {{ reason }}</p>
</div>

<p>We encourage you to review our membership requirements and consider reapplying in the future if your circumstances change.</p>

<p>If you have any questions about our membership criteria, please don't hesitate to contact us.</p>

<p>Best regards,<br>The Membership Team<br>{{ company }}</p>""",
    "membership_rejection_duplicate": """<h3>Membership Application - Duplicate Application</h3>

<p>Dear {{ first_name }},</p>

<p>Thank you for your interest in joining our association.</p>

<p>We have detected that you have already submitted a membership application or are already a member of our association.</p>

<div style="background:#fff3cd;border:1px solid #ffeaa7;padding:15px;border-radius:5px;margin:15px 0">
    <p><strong>Application ID:</strong> {{ application_id }}</p>
    <p><strong>Details:</strong> {{ reason }}</p>
</div>

<p>If you believe this is an error or if you need assistance with your existing membership, please contact us immediately.</p>

<p>If you have any questions, please don't hesitate to reach out.</p>

<p>Best regards,<br>The Membership Team<br>{{ company }}</p>""",
}


# The seeder's own inline style. A row seeded while frappe.flags.in_install is set (setup_membership_
# application_system) skips Frappe's content sanitiser (document.py), so it is stored VERBATIM with this
# spaced style; only the admin-button path stores the minified form that OLD_STOCK holds.
MINIFIED_STYLE = "background:#fff3cd;border:1px solid #ffeaa7;padding:15px;border-radius:5px;margin:15px 0"
SPACED_STYLE = (
    "background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 15px 0;"
)


def _stored_forms(old):
    """The two shapes the old stock text can have on disk: minified, and install-seeded verbatim."""
    return (old, old.replace(MINIFIED_STYLE, SPACED_STYLE))


def execute():
    from verenigingen.services.communication.email_service import invalidate_template_cache

    for name, old in OLD_STOCK.items():
        stored = frappe.db.get_value("Email Template", name, "response")
        if stored not in _stored_forms(old):
            continue
        # response only: the subject and `modified` bookkeeping of an untouched row stay as they were
        new = stored.replace("{{ reason }}", "{{ reason | e }}")
        frappe.db.set_value("Email Template", name, "response", new, update_modified=False)
        invalidate_template_cache(name)
