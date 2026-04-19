# verenigingen/hooks/assets.py
"""Asset include configuration for CSS and JavaScript.

These assets are loaded globally across the application:
- app_include_css/js: Loaded in the Frappe Desk (backend UI)
- web_include_js: Loaded on website/portal pages
- email_css: Inlined into emails by Frappe's premailer
"""

# CSS files loaded in Frappe Desk
app_include_css = [
    "/assets/verenigingen/css/verenigingen_custom.css",
    "/assets/verenigingen/css/volunteer_portal.css",
    "/assets/verenigingen/css/iban-validation.css",
    # Note: brand_colors.css loaded per-template to avoid 404 errors
]

# JavaScript files loaded in Frappe Desk
app_include_js = [
    # OperationResult helpers - must load first for API response handling
    "/assets/verenigingen/js/utils/operation-result-helpers.js",
    "/assets/verenigingen/js/member_portal_redirect.js",
    "/assets/verenigingen/js/utils/iban-validator.js",
    "/assets/verenigingen/js/utils/iban-masking.js",
    "/assets/verenigingen/js/utils/password_autofill_suppression.js",
    "/assets/verenigingen/js/member_age_chart.js",
]

# JavaScript files loaded on web pages (www/ and templates/pages/)
web_include_js = [
    "/assets/verenigingen/js/utils/operation-result-helpers.js",
]

# Email CSS - Frappe's premailer inlines these at send time
# Uses literal hex values (not CSS variables) for email client compatibility
# Path must be in /assets/ for premailer to find it
email_css = ["/assets/verenigingen/css/email_brand.css"]
