"""
Migration patch to configure age validation settings in Verenigingen Settings

This migration sets default age validation values for existing installations
to ensure consistent behavior after the introduction of configurable age validation.
"""
# flake8: noqa: E713

import frappe


def execute():
    """Configure age validation settings with sensible defaults"""
    try:
        # Get the Verenigingen Settings singleton
        settings = frappe.get_single("Verenigingen Settings")

        # Define default age validation settings
        age_settings = {
            "minimum_membership_age": 16,
            "minimum_volunteer_age": 16,  # Updated from 12 to align with membership age
            "minimum_voting_age": 18,
            "minimum_student_age": 14,
            "minimum_youth_age": 12,
            "minimum_senior_age": 65,
        }

        # Only set values if they haven't been configured yet
        settings_updated = False
        for field_name, default_value in age_settings.items():
            if hasattr(settings, field_name):
                current_value = getattr(settings, field_name)
                if current_value is None or current_value == 0:
                    setattr(settings, field_name, default_value)
                    settings_updated = True
                    print(f"Set {field_name} to {default_value}")
                else:
                    print(f"Field {field_name} already configured with value {current_value}")
            else:
                print(f"Warning: Field {field_name} does not exist in Verenigingen Settings")

        if settings_updated:
            settings.save()
            print("Age validation settings configured successfully")

            # Clear cache to ensure new settings are loaded
            frappe.clear_cache()
        else:
            print("No age validation settings needed to be updated")

    except Exception as e:
        # Log error but don't fail the migration
        frappe.log_error(
            f"Failed to configure age validation settings: {str(e)}", "Age Validation Settings Migration"
        )
        print(f"Warning: Failed to configure age validation settings: {str(e)}")
        print("System will use default hardcoded values until settings are manually configured")
