# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class BrandSettings(Document):
    def validate(self):
        """Validate brand settings"""
        self.validate_colors()
        self.validate_active_settings()

    def validate_colors(self):
        """Validate that all colors are valid hex colors"""
        color_fields = [
            "primary_color",
            "primary_hover_color",
            "secondary_color",
            "secondary_hover_color",
            "accent_color",
            "accent_hover_color",
            "success_color",
            "warning_color",
            "error_color",
            "info_color",
            "text_primary_color",
            "text_secondary_color",
            "background_primary_color",
            "background_secondary_color",
        ]

        for field in color_fields:
            color = self.get(field)
            if color and not self.is_valid_hex_color(color):
                frappe.throw(
                    _("Invalid color format for {0}. Please use hex format like #ff0000").format(
                        self.meta.get_field(field).label
                    )
                )

    def validate_active_settings(self):
        """No longer needed for Single doctype"""

    def is_valid_hex_color(self, color):
        """Check if color is a valid hex color"""
        if not color or not color.startswith("#"):
            return False

        # Remove # and check if remaining characters are valid hex
        hex_part = color[1:]
        if len(hex_part) not in [3, 6]:
            return False

        try:
            int(hex_part, 16)
            return True
        except ValueError:
            return False

    def get_color_brightness(self, hex_color):
        """Calculate brightness of a hex color (0-255 scale)"""
        if not hex_color or not hex_color.startswith("#"):
            return 128  # Default medium brightness

        hex_part = hex_color[1:]

        # Convert 3-digit hex to 6-digit
        if len(hex_part) == 3:
            hex_part = "".join([c * 2 for c in hex_part])

        try:
            r = int(hex_part[0:2], 16)
            g = int(hex_part[2:4], 16)
            b = int(hex_part[4:6], 16)

            # Calculate perceived brightness using standard formula
            brightness = (r * 299 + g * 587 + b * 114) / 1000
            return brightness
        except (ValueError, IndexError):
            return 128  # Default medium brightness

    def get_contrasting_text_color(self, background_color):
        """Get white or black text color based on background brightness"""
        brightness = self.get_color_brightness(background_color)
        return "#fffff" if brightness < 128 else "#000000"

    def on_update(self):
        """Clear cache when settings are updated"""
        frappe.cache().delete_key("active_brand_settings")
        frappe.cache().delete_key("brand_settings_css")
        frappe.cache().delete_key("organization_logo")

        # Clear website cache to rebuild portal pages
        frappe.clear_cache()

        # Trigger CSS rebuild for brand changes
        frappe.publish_realtime(
            "brand_settings_updated", {"message": "Brand settings updated", "settings_name": "Brand Settings"}
        )

        # Sync with Owl Theme Settings if available
        self.sync_to_owl_theme()

    def sync_to_owl_theme(self):
        """Sync Brand Settings to Owl Theme Settings if owl_theme app is installed"""
        try:
            # Check if owl_theme app is installed
            if not frappe.db.exists("DocType", "Owl Theme Settings"):
                return

            # Get or create Owl Theme Settings
            owl_settings = frappe.get_single("Owl Theme Settings")

            # Map Brand Settings colors to Owl Theme fields
            owl_settings.primary_buttons_background_color = self.primary_color
            owl_settings.primary_buttons_text_color = self.get_contrasting_text_color(self.primary_color)
            owl_settings.secondary_buttons_background_color = self.secondary_color
            owl_settings.secondary_buttons_text_color = self.get_contrasting_text_color(self.secondary_color)

            # Set navbar colors
            owl_settings.navbar_background_color = self.primary_color
            owl_settings.navbar_text_color = self.get_contrasting_text_color(self.primary_color)

            # Set sidebar colors
            owl_settings.sidebar_background_color = self.background_secondary_color
            owl_settings.sidebar_text_color = self.text_primary_color

            # Set page background colors
            owl_settings.main_page_background_color = self.background_primary_color
            owl_settings.main_page_card_container_background_color = self.background_secondary_color

            # Set card colors
            owl_settings.cards_background_color = self.background_primary_color
            owl_settings.cards_title_text_color = self.text_primary_color
            owl_settings.cards_text_color = self.text_secondary_color

            # Set form and list page backgrounds
            owl_settings.form_background_color = self.background_primary_color
            owl_settings.list_page_background_color = self.background_primary_color

            # Set general background and app name colors
            owl_settings.background_color = self.background_primary_color
            owl_settings.app_name_color = self.primary_color

            # Sync logo if available
            if self.logo:
                owl_settings.app_logo = self.logo

            # Save the Owl Theme Settings
            owl_settings.save(ignore_permissions=True)

            frappe.msgprint(_("Successfully synced brand settings to Owl Theme"))

        except Exception as e:
            frappe.log_error(f"Error syncing to Owl Theme: {str(e)}", "Brand Settings Sync")
            # Don't throw error, just log it - brand settings should still work


@frappe.whitelist()
def get_active_brand_settings():
    """Get the brand settings (now a Single doctype)"""
    # Try to get from cache first
    cached_settings = frappe.cache().get_value("active_brand_settings")
    if cached_settings:
        return cached_settings

    try:
        # Get Brand Settings as a Single doctype
        settings_doc = frappe.get_single("Brand Settings")
        settings = settings_doc.as_dict()

        # Cache for 1 hour
        frappe.cache().set_value("active_brand_settings", settings, expires_in_sec=3600)
        return settings

    except Exception:
        # Return default settings if Brand Settings doesn't exist yet
        default_settings = {
            "logo": None,
            "primary_color": "#cf3131",
            "primary_hover_color": "#b82828",
            "secondary_color": "#01796f",
            "secondary_hover_color": "#015a52",
            "accent_color": "#663399",
            "accent_hover_color": "#4d2673",
            "success_color": "#28a745",
            "warning_color": "#ffc107",
            "error_color": "#dc3545",
            "info_color": "#17a2b8",
            "text_primary_color": "#333333",
            "text_secondary_color": "#666666",
            "background_primary_color": "#ffffff",
            "background_secondary_color": "#f8f9fa",
        }

        return default_settings


@frappe.whitelist()
def generate_brand_css():
    """Generate CSS with brand colors"""
    # Try to get from cache first
    cached_css = frappe.cache().get_value("brand_settings_css")
    if cached_css:
        return cached_css

    settings = get_active_brand_settings()

    # Calculate contrasting text colors for smart styling
    def get_color_brightness(hex_color):
        """Calculate brightness of a hex color (0-255 scale)"""
        if not hex_color or not hex_color.startswith("#"):
            return 128  # Default medium brightness

        hex_part = hex_color[1:]

        # Convert 3-digit hex to 6-digit
        if len(hex_part) == 3:
            hex_part = "".join([c * 2 for c in hex_part])

        try:
            r = int(hex_part[0:2], 16)
            g = int(hex_part[2:4], 16)
            b = int(hex_part[4:6], 16)

            # Calculate perceived brightness using standard formula
            brightness = (r * 299 + g * 587 + b * 114) / 1000
            return brightness
        except (ValueError, IndexError):
            return 128  # Default medium brightness

    def get_contrasting_text_color(background_color):
        """Get white or black text color based on background brightness"""
        brightness = get_color_brightness(background_color)
        return "#fffff" if brightness < 128 else "#000000"

    get_contrasting_text_color(settings["primary_color"])
    get_contrasting_text_color(settings["secondary_color"])
    get_contrasting_text_color(settings["accent_color"])

    css = f"""
/* Brand Settings CSS - Auto-generated */
:root {{
    --brand-primary: {settings['primary_color']};
    --brand-primary-hover: {settings['primary_hover_color']};
    --brand-secondary: {settings['secondary_color']};
    --brand-secondary-hover: {settings['secondary_hover_color']};
    --brand-accent: {settings['accent_color']};
    --brand-accent-hover: {settings['accent_hover_color']};
    --brand-success: {settings['success_color']};
    --brand-warning: {settings['warning_color']};
    --brand-error: {settings['error_color']};
    --brand-info: {settings['info_color']};
    --brand-text-primary: {settings['text_primary_color']};
    --brand-text-secondary: {settings['text_secondary_color']};
    --brand-bg-primary: {settings['background_primary_color']};
    --brand-bg-secondary: {settings['background_secondary_color']};
    --brand-primary-text: {primary_text};
    --brand-secondary-text: {secondary_text};
    --brand-accent-text: {accent_text};
}}

/* Portal-specific brand colors - only applied to portal pages, not Frappe desk */
/* Using body class selectors that are present on portal pages */
body.portal-page {{
    /* Override Tailwind CSS custom properties for portal pages only */
    --color-primary-500: {settings['primary_color']};
    --color-primary-600: {settings['primary_hover_color']};
    --color-secondary-500: {settings['secondary_color']};
    --color-secondary-600: {settings['secondary_hover_color']};
    --color-accent-500: {settings['accent_color']};
    --color-accent-600: {settings['accent_hover_color']};
}}

/* Override Tailwind classes with brand colors - ONLY for portal pages */
/* Multiple selectors to ensure proper scoping */
body.portal-page .bg-red-600,
.verenigingen-portal .bg-red-600,
[data-portal-page] .bg-red-600 {{ background-color: var(--brand-primary) !important; }}

body.portal-page .bg-red-700,
.verenigingen-portal .bg-red-700,
[data-portal-page] .bg-red-700 {{ background-color: var(--brand-primary-hover) !important; }}

body.portal-page .hover\\:bg-red-700:hover,
.verenigingen-portal .hover\\:bg-red-700:hover,
[data-portal-page] .hover\\:bg-red-700:hover {{ background-color: var(--brand-primary-hover) !important; }}

body.portal-page .bg-teal-600,
.verenigingen-portal .bg-teal-600,
[data-portal-page] .bg-teal-600 {{ background-color: var(--brand-secondary) !important; }}

body.portal-page .bg-teal-700,
.verenigingen-portal .bg-teal-700,
[data-portal-page] .bg-teal-700 {{ background-color: var(--brand-secondary-hover) !important; }}

body.portal-page .hover\\:bg-teal-700:hover,
.verenigingen-portal .hover\\:bg-teal-700:hover,
[data-portal-page] .hover\\:bg-teal-700:hover {{ background-color: var(--brand-secondary-hover) !important; }}

body.portal-page .bg-purple-600,
.verenigingen-portal .bg-purple-600,
[data-portal-page] .bg-purple-600 {{ background-color: var(--brand-accent) !important; }}

body.portal-page .bg-purple-700,
.verenigingen-portal .bg-purple-700,
[data-portal-page] .bg-purple-700 {{ background-color: var(--brand-accent-hover) !important; }}

body.portal-page .hover\\:bg-purple-700:hover,
.verenigingen-portal .hover\\:bg-purple-700:hover,
[data-portal-page] .hover\\:bg-purple-700:hover {{ background-color: var(--brand-accent-hover) !important; }}

body.portal-page .text-red-600,
.verenigingen-portal .text-red-600,
[data-portal-page] .text-red-600 {{ color: var(--brand-primary) !important; }}

body.portal-page .text-teal-600,
.verenigingen-portal .text-teal-600,
[data-portal-page] .text-teal-600 {{ color: var(--brand-secondary) !important; }}

body.portal-page .text-purple-600,
.verenigingen-portal .text-purple-600,
[data-portal-page] .text-purple-600 {{ color: var(--brand-accent) !important; }}

body.portal-page .border-red-500,
.verenigingen-portal .border-red-500,
[data-portal-page] .border-red-500 {{ border-color: var(--brand-primary) !important; }}

body.portal-page .border-teal-500,
.verenigingen-portal .border-teal-500,
[data-portal-page] .border-teal-500 {{ border-color: var(--brand-secondary) !important; }}

body.portal-page .border-purple-500,
.verenigingen-portal .border-purple-500,
[data-portal-page] .border-purple-500 {{ border-color: var(--brand-accent) !important; }}

body.portal-page .focus\\:ring-red-500:focus,
.verenigingen-portal .focus\\:ring-red-500:focus,
[data-portal-page] .focus\\:ring-red-500:focus {{ --tw-ring-color: var(--brand-primary) !important; }}

body.portal-page .focus\\:border-red-500:focus,
.verenigingen-portal .focus\\:border-red-500:focus,
[data-portal-page] .focus\\:border-red-500:focus {{ border-color: var(--brand-primary) !important; }}

/* Gradient overrides - scoped to portal pages */
body.portal-page .from-purple-600,
.verenigingen-portal .from-purple-600,
[data-portal-page] .from-purple-600 {{ --tw-gradient-from: var(--brand-accent) !important; }}

body.portal-page .from-purple-700,
.verenigingen-portal .from-purple-700,
[data-portal-page] .from-purple-700 {{ --tw-gradient-from: var(--brand-accent-hover) !important; }}

body.portal-page .to-red-600,
.verenigingen-portal .to-red-600,
[data-portal-page] .to-red-600 {{ --tw-gradient-to: var(--brand-primary) !important; }}

body.portal-page .to-purple-800,
.verenigingen-portal .to-purple-800,
[data-portal-page] .to-purple-800 {{ --tw-gradient-to: var(--brand-accent-hover) !important; }}

/* Custom brand utility classes */
.btn-brand-primary {{
    background-color: var(--brand-primary);
    color: white;
    border-color: var(--brand-primary);
}}

.btn-brand-primary:hover {{
    background-color: var(--brand-primary-hover);
    border-color: var(--brand-primary-hover);
}}

.btn-brand-secondary {{
    background-color: var(--brand-secondary);
    color: white;
    border-color: var(--brand-secondary);
}}

.btn-brand-secondary:hover {{
    background-color: var(--brand-secondary-hover);
    border-color: var(--brand-secondary-hover);
}}

.text-brand-primary {{ color: var(--brand-primary); }}
.text-brand-secondary {{ color: var(--brand-secondary); }}
.text-brand-accent {{ color: var(--brand-accent); }}

.bg-brand-primary {{ background-color: var(--brand-primary); }}
.bg-brand-secondary {{ background-color: var(--brand-secondary); }}
.bg-brand-accent {{ background-color: var(--brand-accent); }}

.border-brand-primary {{ border-color: var(--brand-primary); }}
.border-brand-secondary {{ border-color: var(--brand-secondary); }}
.border-brand-accent {{ border-color: var(--brand-accent); }}

/* Existing CSS overrides for custom pages */
.btn-primary {{
    background-color: var(--brand-primary) !important;
    border-color: var(--brand-primary) !important;
}}

.btn-primary:hover {{
    background-color: var(--brand-primary-hover) !important;
    border-color: var(--brand-primary-hover) !important;
}}

/* Text primary overrides for existing pages */
.text-primary {{
    color: var(--brand-primary) !important;
}}

/* Form focus states */
.form-control:focus {{
    border-color: var(--brand-primary) !important;
    box-shadow: 0 0 0 2px rgba(207, 49, 49, 0.25) !important;
}}

/* Compact section styling for better space utilization */
.page-header {{
    padding: 1.25rem 1.5rem !important;
    margin-bottom: 1.5rem !important;
}}

.page-header h1 {{
    margin: 0 0 0.25rem 0 !important;
    font-size: 2rem !important;
    color: var(--brand-primary-text) !important;
}}

.page-header p {{
    margin: 0 !important;
    font-size: 1rem !important;
    opacity: 0.85 !important;
}}

/* Compact info boxes */
.bg-teal-50, .bg-blue-50, .bg-yellow-50, .bg-green-50, .bg-red-50 {{
    padding: 0.875rem 1rem !important;
    margin-bottom: 1rem !important;
}}

/* Brand-colored headers with smart text colors */
.bg-red-600, .bg-teal-600, .bg-purple-600 {{
    color: var(--brand-primary-text) !important;
}}

.bg-red-600 h1, .bg-red-600 h2, .bg-red-600 h3, .bg-red-600 h4 {{
    color: var(--brand-primary-text) !important;
}}

.bg-teal-600 h1, .bg-teal-600 h2, .bg-teal-600 h3, .bg-teal-600 h4 {{
    color: var(--brand-secondary-text) !important;
}}

.bg-purple-600 h1, .bg-purple-600 h2, .bg-purple-600 h3, .bg-purple-600 h4 {{
    color: var(--brand-accent-text) !important;
}}

/* Compact button styling */
.btn-primary, .btn-brand-primary {{
    color: var(--brand-primary-text) !important;
}}

.btn-secondary, .btn-brand-secondary {{
    color: var(--brand-secondary-text) !important;
}}

/* More compact card spacing */
.rounded-xl {{
    padding: 1.25rem !important;
}}

.rounded-xl h3, .rounded-xl h4 {{
    margin-bottom: 0.75rem !important;
}}

/* Expense form button override */
.bg-green-600, .bg-green-500 {{
    background-color: var(--brand-primary) !important;
    color: var(--brand-primary-text) !important;
}}

.bg-green-600:hover, .bg-green-500:hover {{
    background-color: var(--brand-primary-hover) !important;
}}

/* Logo integration styles */
.organization-logo {{
    max-height: 60px;
    max-width: 200px;
    object-fit: contain;
    margin-bottom: 1rem;
}}

.header-with-logo {{
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-bottom: 2rem;
}}

.header-with-logo .organization-logo {{
    margin-bottom: 0;
}}

/* Responsive logo adjustments */
@media (max-width: 768px) {{
    .header-with-logo {{
        flex-direction: column;
        text-align: center;
        gap: 0.5rem;
    }}

    .organization-logo {{
        max-height: 40px;
        margin-bottom: 0.5rem;
    }}
}}
"""

    # Cache for 5 minutes to allow for quicker updates during development
    frappe.cache().set_value("brand_settings_css", css, expires_in_sec=300)

    return css


@frappe.whitelist()
def get_organization_logo():
    """Get the currently active organization logo"""
    # Try to get from cache first
    cached_logo = frappe.cache().get_value("organization_logo")
    if cached_logo:
        return cached_logo

    settings = get_active_brand_settings()
    logo_url = settings.get("logo")

    # Cache for 1 hour
    if logo_url:
        frappe.cache().set_value("organization_logo", logo_url, expires_in_sec=3600)

    return logo_url


@frappe.whitelist()
def create_default_brand_settings():
    """Create default brand settings if none exist"""
    existing = frappe.get_all("Brand Settings", limit=1)
    if existing:
        return False

    default_settings = frappe.get_doc(
        {
            "doctype": "Brand Settings",
            "settings_name": "Default Brand Settings",
            "description": "Default brand colors for the organization",
            "is_active": 1,
            "primary_color": "#cf3131",
            "primary_hover_color": "#b82828",
            "secondary_color": "#01796f",
            "secondary_hover_color": "#015a52",
            "accent_color": "#663399",
            "accent_hover_color": "#4d2673",
            "success_color": "#28a745",
            "warning_color": "#ffc107",
            "error_color": "#dc3545",
            "info_color": "#17a2b8",
            "text_primary_color": "#333333",
            "text_secondary_color": "#666666",
            "background_primary_color": "#ffffff",
            "background_secondary_color": "#f8f9fa",
        }
    )

    default_settings.insert(ignore_permissions=True)
    return True


@frappe.whitelist()
def sync_brand_settings_to_owl_theme():
    """Manual function to sync active Brand Settings to Owl Theme"""
    try:
        # Get active brand settings
        active_settings = frappe.get_all("Brand Settings", filters={"is_active": 1}, limit=1)

        if not active_settings:
            return {"success": False, "message": "No active Brand Settings found"}

        # Get the brand settings document
        brand_doc = frappe.get_doc("Brand Settings", active_settings[0].name)

        # Sync to owl theme
        brand_doc.sync_to_owl_theme()

        return {"success": True, "message": "Successfully synced Brand Settings to Owl Theme"}

    except Exception as e:
        frappe.log_error(f"Error in manual sync to Owl Theme: {str(e)}", "Brand Settings Manual Sync")
        return {"success": False, "message": f"Error: {str(e)}"}


@frappe.whitelist()
def check_owl_theme_integration():
    """Check if Owl Theme is installed and working"""
    try:
        # Check if owl_theme app is installed
        owl_theme_installed = frappe.db.exists("DocType", "Owl Theme Settings")

        if not owl_theme_installed:
            return {"installed": False, "message": "Owl Theme app is not installed"}

        # Check if Owl Theme Settings document exists
        owl_settings = frappe.get_single("Owl Theme Settings")

        # Get active brand settings
        active_brand = frappe.get_all(
            "Brand Settings", filters={"is_active": 1}, fields=["name", "settings_name"], limit=1
        )

        return {
            "installed": True,
            "owl_settings_exists": bool(owl_settings),
            "active_brand_settings": active_brand[0] if active_brand else None,
            "message": "Owl Theme integration is available",
        }

    except Exception as e:
        return {
            "installed": False,
            "error": str(e),
            "message": f"Error checking Owl Theme integration: {str(e)}",
        }


@frappe.whitelist()
def test_owl_theme_integration():
    """Test the complete Owl Theme integration"""
    results = {}

    try:
        # Test 1: Check Owl Theme detection
        status = check_owl_theme_integration()
        results["owl_theme_detection"] = {"success": status.get("installed", False), "details": status}

        # Test 2: Test sync functionality
        sync_result = sync_brand_settings_to_owl_theme()
        results["sync_functionality"] = {
            "success": sync_result.get("success", False),
            "message": sync_result.get("message", "Unknown error"),
        }

        # Test 3: Verify sync actually changed Owl Theme Settings
        if sync_result.get("success"):
            owl_settings = frappe.get_single("Owl Theme Settings")
            brand_settings = frappe.get_all(
                "Brand Settings", filters={"is_active": 1}, fields=["primary_color"], limit=1
            )

            if brand_settings:
                brand_primary = brand_settings[0].get("primary_color")
                owl_navbar = getattr(owl_settings, "navbar_background_color", None)

                results["sync_verification"] = {
                    "success": brand_primary == owl_navbar,
                    "brand_primary_color": brand_primary,
                    "owl_navbar_color": owl_navbar,
                    "colors_match": brand_primary == owl_navbar,
                }
            else:
                results["sync_verification"] = {"success": False, "message": "No active brand settings found"}

        # Test 4: Test automatic sync trigger
        if results["owl_theme_detection"]["success"]:
            brand_doc = frappe.get_all("Brand Settings", filters={"is_active": 1}, limit=1)

            if brand_doc:
                doc = frappe.get_doc("Brand Settings", brand_doc[0].name)
                try:
                    doc.sync_to_owl_theme()
                    results["auto_sync_trigger"] = {
                        "success": True,
                        "message": "Auto-sync method executed successfully",
                    }
                except Exception as e:
                    results["auto_sync_trigger"] = {"success": False, "error": str(e)}

        # Overall test result
        all_tests_passed = all(
            test.get("success", False) for test in results.values() if isinstance(test, dict)
        )

        results["overall_success"] = all_tests_passed
        results["summary"] = {
            "owl_theme_installed": results["owl_theme_detection"]["success"],
            "sync_works": results["sync_functionality"]["success"],
            "colors_sync_correctly": results.get("sync_verification", {}).get("success", False),
            "auto_sync_works": results.get("auto_sync_trigger", {}).get("success", False),
        }

    except Exception as e:
        results["error"] = str(e)
        results["overall_success"] = False

    return results


@frappe.whitelist()
def get_brand_css_inline():
    """Get brand CSS for inline inclusion in pages - bypasses route caching issues"""
    try:
        css = generate_brand_css()
        return {"success": True, "css": css, "timestamp": frappe.utils.now()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def force_rebuild_css():
    """Force rebuild and clear all brand-related caches"""
    try:
        # Clear all brand-related cache keys
        frappe.cache().delete_key("active_brand_settings")
        frappe.cache().delete_key("brand_settings_css")
        frappe.cache().delete_key("organization_logo")

        # Clear all website cache
        frappe.clear_cache()

        # Regenerate CSS
        css = generate_brand_css()

        return {"success": True, "message": "CSS cache cleared and regenerated", "css_length": len(css)}
    except Exception as e:
        return {"success": False, "message": f"Error rebuilding CSS: {str(e)}"}
