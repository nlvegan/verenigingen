# verenigingen/hooks/portal.py
"""Portal and website configuration.

Portal navigation is rendered by this app's own role-based templates
(templates/includes/portal_nav.html and templates/includes/web_sidebar.html), which
read context["user_roles"]. Frappe's Portal Settings menu is deliberately not used:
its sync_menu() drops any item whose reference_doctype is not an existing DocType, so
route-only entries for custom template pages cannot survive a migrate.
"""

# Website context update hooks - modify context for all web pages
update_website_context = ["verenigingen.utils.portal_customization.add_portal_user_roles"]
