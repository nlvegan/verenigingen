# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    high_security_api,
    public_api,
    standard_api,
)


class BrandSettings(Document):
    def before_save(self):
        """Auto-calculate derived colors before saving"""
        self.auto_calculate_derived_colors()

    def validate(self):
        """Validate brand settings"""
        self.validate_colors()
        self.validate_active_settings()

    def auto_calculate_derived_colors(self):
        """Auto-calculate all derived colors from primary, secondary, and accent colors

        This reduces the number of required fields from 20+ to just 3 main colors.
        All hover, text, and background colors are derived automatically.
        Users can still override any field if needed (read_only=0).
        """
        # Get previous values to detect manual changes
        doc_before_save = self.get_doc_before_save() if self.get("name") else None

        # Auto-calculate hover colors (15% darker than base colors)
        # Only auto-calculate if the field wasn't manually changed by the user
        if self.primary_color:
            # Calculate what the auto value would be
            auto_hover = self.mix_colors(self.primary_color, "#000000", 0.85)
            # If user hasn't manually set a different value, use auto value
            if not doc_before_save or self.primary_hover_color == doc_before_save.get("primary_hover_color"):
                self.primary_hover_color = auto_hover

        if self.secondary_color:
            auto_hover = self.mix_colors(self.secondary_color, "#000000", 0.85)
            if not doc_before_save or self.secondary_hover_color == doc_before_save.get(
                "secondary_hover_color"
            ):
                self.secondary_hover_color = auto_hover

        if self.accent_color:
            auto_hover = self.mix_colors(self.accent_color, "#000000", 0.85)
            if not doc_before_save or self.accent_hover_color == doc_before_save.get("accent_hover_color"):
                self.accent_hover_color = auto_hover

        # Auto-calculate button text colors based on brightness
        # These always auto-calculate unless user manually changed them
        if self.primary_color:
            auto_text = self.get_contrasting_text_color(self.primary_color)
            if not doc_before_save or self.primary_button_text_color == doc_before_save.get(
                "primary_button_text_color"
            ):
                self.primary_button_text_color = auto_text

        if self.secondary_color:
            auto_text = self.get_contrasting_text_color(self.secondary_color)
            if not doc_before_save or self.secondary_button_text_color == doc_before_save.get(
                "secondary_button_text_color"
            ):
                self.secondary_button_text_color = auto_text

        if self.accent_color:
            auto_text = self.get_contrasting_text_color(self.accent_color)
            if not doc_before_save or self.accent_button_text_color == doc_before_save.get(
                "accent_button_text_color"
            ):
                self.accent_button_text_color = auto_text

        # Semantic status colors - keep defaults unless manually changed
        # These use standard UI/UX color conventions
        if not self.success_color:
            self.success_color = "#28a745"  # Green
        if not self.warning_color:
            self.warning_color = "#ffc107"  # Amber
        if not self.error_color:
            self.error_color = "#dc3545"  # Red
        if not self.info_color:
            self.info_color = "#17a2b8"  # Blue

        # Text and background colors - use standard defaults
        if not self.text_primary_color:
            self.text_primary_color = "#333333"  # Dark gray
        if not self.text_secondary_color:
            self.text_secondary_color = "#666666"  # Medium gray
        if not self.background_primary_color:
            self.background_primary_color = "#ffffff"  # White
        if not self.background_secondary_color:
            self.background_secondary_color = "#f8f9fa"  # Light gray

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
        return "#ffffff" if brightness < 128 else "#000000"

    def mix_colors(self, color1, color2, ratio=0.5):
        """Mix two hex colors together at specified ratio (0.0 to 1.0)

        Args:
            color1: First hex color (e.g., '#ff0000')
            color2: Second hex color (e.g., '#0000ff')
            ratio: How much of color1 vs color2 (0.5 = 50/50 mix)

        Returns:
            Mixed hex color
        """
        if not color1 or not color1.startswith("#"):
            return color2
        if not color2 or not color2.startswith("#"):
            return color1

        # Convert hex to RGB
        def hex_to_rgb(hex_color):
            hex_part = hex_color[1:]
            if len(hex_part) == 3:
                hex_part = "".join([c * 2 for c in hex_part])
            return tuple(int(hex_part[i : i + 2], 16) for i in (0, 2, 4))

        # Mix RGB values
        rgb1 = hex_to_rgb(color1)
        rgb2 = hex_to_rgb(color2)

        mixed_rgb = tuple(int(rgb1[i] * ratio + rgb2[i] * (1 - ratio)) for i in range(3))

        # Convert back to hex
        return "#{:02x}{:02x}{:02x}".format(*mixed_rgb)

    def tint_color(self, base_color, tint_color, strength=0.05):
        """Add a subtle tint of brand color to a base color

        Args:
            base_color: Base color (e.g., white '#ffffff')
            tint_color: Brand color to tint with
            strength: How strong the tint (0.05 = 5% brand color)

        Returns:
            Tinted hex color
        """
        return self.mix_colors(tint_color, base_color, strength)

    def generate_background_layers(self):
        """Generate layered background colors with depth and subtle brand tinting

        Returns:
            dict with workspace, container, and card background colors
        """
        # Start with user-defined backgrounds or defaults
        base_bg = self.background_primary_color or "#ffffff"
        secondary_bg = self.background_secondary_color or "#f8f9fa"

        # Add subtle brand tint to workspace (5% primary color)
        workspace_bg = self.tint_color(base_bg, self.primary_color, 0.05)

        # Card container - noticeably darker/tinted (12% primary color)
        container_bg = self.tint_color(secondary_bg, self.primary_color, 0.12)

        # Individual cards - clean white with minimal tint (2% secondary color)
        # This creates clear separation from container
        card_bg = self.tint_color(base_bg, self.secondary_color, 0.02)

        return {"workspace": workspace_bg, "container": container_bg, "cards": card_bg}

    def on_update(self):
        """Clear cache when settings are updated"""
        frappe.cache().delete_key("active_brand_settings")
        frappe.cache().delete_key("brand_settings_css")
        frappe.cache().delete_key("organization_logo")

        # Clear website cache to rebuild portal pages
        frappe.clear_cache()

        # Generate static CSS file (moved from hooks.py)
        self.generate_static_css_file()

        # Export logo to public location for portal/web access
        self.export_logo_to_public()

        # Trigger CSS rebuild for brand changes
        frappe.publish_realtime(
            "brand_settings_updated", {"message": "Brand settings updated", "settings_name": "Brand Settings"}
        )

        # Sync with Owl Theme Settings if available
        self.sync_to_owl_theme()

    def generate_static_css_file(self):
        """Generate static CSS file for brand colors"""
        try:
            from verenigingen.utils.brand_css_generator import generate_brand_css_file

            generate_brand_css_file(doc=self)
        except Exception as e:
            frappe.log_error(f"Error generating static CSS file: {str(e)}", "Brand Settings CSS Generation")

    def export_logo_to_public(self):
        """Export logo to publicly accessible location for portal/web pages"""
        try:
            import os
            import shutil
            from pathlib import Path

            if not self.logo:
                # No logo set, remove existing public logo if it exists
                public_logo_path = Path(frappe.get_site_path("public", "files", "organization_logo.png"))
                if public_logo_path.exists():
                    public_logo_path.unlink()
                    frappe.cache().delete_key("organization_logo")
                return

            # Get the source logo file path
            from urllib.parse import unquote

            logo_file = frappe.get_doc("File", {"file_url": self.logo})
            if not logo_file:
                return

            # URL-decode the file name to handle spaces and special characters
            decoded_file_name = unquote(logo_file.file_name.lstrip("/"))
            source_path = Path(frappe.get_site_path()) / decoded_file_name
            if not source_path.exists():
                frappe.log_error(f"Source logo file not found: {source_path}", "Logo Export Error")
                return

            # Copy to public location with standard name
            public_dir = Path(frappe.get_site_path("public", "files"))
            public_dir.mkdir(parents=True, exist_ok=True)

            # Use .png extension for consistency, regardless of source format
            public_logo_path = public_dir / "organization_logo.png"

            shutil.copy2(source_path, public_logo_path)

            # Update cache with public URL
            public_url = "/files/organization_logo.png"
            frappe.cache().set_value("organization_logo", public_url, expires_in_sec=86400)  # 24 hours

            frappe.logger().info(f"Logo exported to public location: {public_logo_path}")

        except Exception as e:
            frappe.log_error(f"Error exporting logo to public location: {str(e)}", "Logo Export Error")

    def sync_to_owl_theme(self):
        """Sync Brand Settings to Owl Theme Settings if owl_theme app is installed

        Auto-Derivation Strategy:
        - 3 core brand colors: primary, secondary, accent
        - All text colors auto-calculated for optimal contrast
        - Background colors for depth/hierarchy
        - No manual text color configuration needed

        Field Mapping:
        - primary_color → navbar background, primary buttons
        - secondary_color → secondary buttons
        - accent_color → accent buttons
        - text_primary_color → sidebar, card titles (user can customize)
        - text_secondary_color → card descriptions (user can customize)
        - background_primary_color → workspace, forms, lists, cards
        - background_secondary_color → sidebar, card containers (depth)
        """
        try:
            # Check if owl_theme app is installed
            if not frappe.db.exists("DocType", "Owl Theme Settings"):
                return

            # Get or create Owl Theme Settings
            owl_settings = frappe.get_single("Owl Theme Settings")

            # BUTTON COLORS - Auto-calculate text colors for contrast
            owl_settings.primary_buttons_background_color = self.primary_color
            owl_settings.primary_buttons_text_color = self.get_contrasting_text_color(self.primary_color)

            owl_settings.secondary_buttons_background_color = self.secondary_color
            owl_settings.secondary_buttons_text_color = self.get_contrasting_text_color(self.secondary_color)

            # NAVBAR COLORS - Primary brand identity with auto-contrasting text
            owl_settings.navbar_background_color = self.primary_color
            owl_settings.navbar_text_color = self.get_contrasting_text_color(self.primary_color)

            # APP NAME COLOR - Auto-contrast against navbar background for breadcrumbs and workspace names
            # This ensures breadcrumb text is readable against the navbar, not the primary color
            owl_settings.app_name_color = self.get_contrasting_text_color(
                owl_settings.navbar_background_color or self.primary_color
            )

            # SIDEBAR COLORS - Use secondary background with user-defined text
            owl_settings.sidebar_background_color = self.background_secondary_color
            owl_settings.sidebar_text_color = self.text_primary_color

            # WORKSPACE/MAIN PAGE BACKGROUNDS - Generated with depth and brand tinting
            bg_layers = self.generate_background_layers()

            owl_settings.main_page_background_color = bg_layers["workspace"]
            owl_settings.main_page_card_container_background_color = bg_layers["container"]
            owl_settings.background_color = bg_layers["workspace"]

            # CARD COLORS - Workspace shortcut cards with subtle tinting
            owl_settings.cards_background_color = bg_layers["cards"]
            owl_settings.cards_title_text_color = self.text_primary_color
            owl_settings.cards_text_color = self.text_secondary_color

            # FORM AND LIST PAGE BACKGROUNDS - Use workspace background
            owl_settings.form_background_color = bg_layers["workspace"]
            owl_settings.list_page_background_color = bg_layers["workspace"]

            # LOGO SYNC - Use organization branding
            if self.logo:
                owl_settings.app_logo = self.logo

            # Save the Owl Theme Settings with secure operations
            result = secure_document_operation(
                operation="save",
                doc=owl_settings,
                justification="Sync brand settings to Owl Theme configuration - system branding and UI configuration management",
                required_permissions=["System Settings:write"],
            )
            if not result.success:
                frappe.throw(f"Failed to sync brand settings: {'; '.join(result.errors)}")

            frappe.msgprint(_("Successfully synced brand settings to Owl Theme"))

        except Exception as e:
            frappe.log_error(f"Error syncing to Owl Theme: {str(e)}", "Brand Settings Sync")
            # Don't throw error, just log it - brand settings should still work


@frappe.whitelist(allow_guest=True)
def get_active_brand_settings():
    """Get the brand settings (now a Single doctype)

    Note: No rate limiting - this is cached read-only config data called on every portal page load.
    """
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
@high_security_api(operation_type=OperationType.ADMIN)
def generate_brand_css():
    """Generate CSS with brand colors

    DEPRECATED: This function is deprecated. Use the new brand_css_generator.generate_brand_css_file() instead.
    This function now reads from the static CSS file generated by the new generator.
    """
    import os
    import warnings

    warnings.warn(
        "generate_brand_css() is deprecated. Use brand_css_generator.generate_brand_css_file() instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    # Read from the static CSS file generated by the new generator
    from verenigingen.utils.brand_css_generator import get_brand_css_file_path

    css_path = get_brand_css_file_path()
    if os.path.exists(css_path):
        with open(css_path, "r") as f:
            return f.read()

    # Fallback to old logic if file doesn't exist (preserved for backwards compatibility)
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
        return "#ffffff" if brightness < 128 else "#000000"

    primary_text = get_contrasting_text_color(settings["primary_color"])
    secondary_text = get_contrasting_text_color(settings["secondary_color"])
    accent_text = get_contrasting_text_color(settings["accent_color"])

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
@public_api
def get_organization_logo():
    """Get the currently active organization logo"""
    # Try to get from cache first
    cached_logo = frappe.cache().get_value("organization_logo")
    if cached_logo:
        return cached_logo

    # Check for public logo file first (no authentication needed)
    from pathlib import Path

    public_logo_path = Path(frappe.get_site_path("public", "files", "organization_logo.png"))
    if public_logo_path.exists():
        public_url = "/files/organization_logo.png"
        # Cache for future requests
        frappe.cache().set_value("organization_logo", public_url, expires_in_sec=86400)
        return public_url

    # Fallback to database lookup (requires authentication)
    try:
        settings = get_active_brand_settings()
        logo_url = settings.get("logo")

        # Cache for 1 hour
        if logo_url:
            frappe.cache().set_value("organization_logo", logo_url, expires_in_sec=3600)

        return logo_url
    except Exception as e:
        # If database lookup fails (e.g., no authentication), return None
        # This allows pages to gracefully handle missing logos
        frappe.logger().warning(f"Could not fetch logo from database: {str(e)}")
        return None


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def create_default_brand_settings():
    """Create default brand settings if none exist"""
    # Brand Settings is a Single DocType, check if it exists properly
    if frappe.db.exists("Brand Settings", "Brand Settings"):
        return False

    default_settings = frappe.get_doc(
        {
            "doctype": "Brand Settings",
            "settings_name": "Default Brand Settings",
            "description": "Default brand colors for the organization",
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

    result = secure_document_operation(
        operation="insert",
        doc=default_settings,
        justification="Create default brand settings during system initialization - essential UI configuration setup",
        required_permissions=["Brand Settings:create"],
    )
    if not result.success:
        frappe.log_error(f"Failed to create default brand settings: {'; '.join(result.errors)}")
        return False
    return True


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def sync_brand_settings_to_owl_theme():
    """Manual function to sync active Brand Settings to Owl Theme"""
    try:
        # Get brand settings (single doctype)
        try:
            brand_settings = frappe.get_single("Brand Settings")
        except frappe.DoesNotExistError:
            return {"success": False, "message": "Brand Settings not found"}

        # Sync to owl theme
        brand_settings.sync_to_owl_theme()

        return {"success": True, "message": "Successfully synced Brand Settings to Owl Theme"}

    except Exception as e:
        frappe.log_error(f"Error in manual sync to Owl Theme: {str(e)}", "Brand Settings Manual Sync")
        return {"success": False, "message": f"Error: {str(e)}"}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
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
        active_brand = frappe.get_all("Brand Settings", fields=["name", "description"], limit=1)

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
@high_security_api(operation_type=OperationType.UTILITY)
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
            try:
                brand_settings = frappe.get_single("Brand Settings")
                brand_primary = brand_settings.primary_color
            except frappe.DoesNotExistError:
                brand_primary = None

            owl_navbar = getattr(owl_settings, "navbar_background_color", None)

            if brand_primary:
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
            try:
                doc = frappe.get_single("Brand Settings")
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
@standard_api(operation_type=OperationType.PUBLIC)
def get_brand_css_inline():
    """Get brand CSS for inline inclusion in pages - bypasses route caching issues"""
    try:
        # Read from the generated static CSS file which has all the latest updates
        import os

        from verenigingen.utils.brand_css_generator import get_brand_css_file_path

        css_path = get_brand_css_file_path()
        if os.path.exists(css_path):
            with open(css_path, "r") as f:
                css = f.read()
        else:
            # Fallback to generating inline if file doesn't exist
            css = generate_brand_css()

        return {"success": True, "css": css, "timestamp": frappe.utils.now()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def force_rebuild_css():
    """Force rebuild and clear all brand-related caches"""
    try:
        # Clear all brand-related cache keys
        frappe.cache().delete_key("active_brand_settings")
        frappe.cache().delete_key("brand_settings_css")
        frappe.cache().delete_key("organization_logo")

        # Clear all website cache
        frappe.clear_cache()

        # Regenerate CSS using the new generator
        from verenigingen.utils.brand_css_generator import generate_brand_css_file

        css_path = generate_brand_css_file()

        # Read the generated CSS to return length
        import os

        css_length = 0
        if css_path and os.path.exists(css_path):
            with open(css_path, "r") as f:
                css_length = len(f.read())

        return {"success": True, "message": "CSS cache cleared and regenerated", "css_length": css_length}
    except Exception as e:
        return {"success": False, "message": f"Error rebuilding CSS: {str(e)}"}
