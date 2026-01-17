# verenigingen/hooks/portal.py
"""Portal and website configuration.

Defines portal menu items, website context processors, and
other web-facing customizations for member and volunteer portals.
"""

# Custom portal menu items for association members
# These override ERPNext defaults and provide role-based access
standard_portal_menu_items = [
    {
        "title": "Member Portal",
        "route": "/member_portal",
        "reference_doctype": "",
        "role": "Verenigingen Member",
    },
    {
        "title": "Volunteer Portal",
        "route": "/volunteer_portal",
        "reference_doctype": "",
        "role": "Verenigingen Volunteer",
    },
    {
        "title": "Upload Documents",
        "route": "/board/document_upload",
        "reference_doctype": "",
        "role": "Verenigingen Chapter Board Member",
    },
    {
        "title": "Browse Documents",
        "route": "/board/document_browser",
        "reference_doctype": "",
        "role": "Verenigingen Member",
    },
]

# Portal context processors - add data to portal page context
website_context = {"get_member_context": "verenigingen.utils.portal_customization.get_member_context"}

# Website context update hooks - modify context for all web pages
# Used to add body classes for brand styling
update_website_context = ["verenigingen.utils.portal_customization.add_brand_body_classes"]
