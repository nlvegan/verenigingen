# Brand Settings → Owl Theme Mapping Guide

This document explains how Brand Settings fields map to Owl Theme Settings to control the Frappe Desk UI appearance.

## Overview

The `sync_to_owl_theme()` method automatically syncs your Brand Settings to Owl Theme whenever you save Brand Settings. This ensures consistent branding across both portal pages and the Frappe Desk interface.

## Field Mapping Reference

### 🎨 Primary Brand Identity (Navbar & Buttons)

| Brand Settings Field | → | Owl Theme Field | Controls |
|---------------------|---|-----------------|----------|
| `primary_color` | → | `navbar_background_color` | Top navbar background color |
| `primary_color` | → | `primary_buttons_background_color` | Primary button backgrounds |
| `primary_button_text_color` | → | `navbar_text_color` | **Breadcrumb trail text, navbar links** |
| `primary_button_text_color` | → | `app_name_color` | **Workspace/DocType name in navbar** |
| `primary_button_text_color` | → | `primary_buttons_text_color` | Text on primary buttons |

**Key Insight**: The `primary_button_text_color` field now controls THREE critical UI elements:
1. Breadcrumb document names (top left)
2. Workspace/DocType names in navbar
3. Primary button text

If `primary_button_text_color` is not set, the system auto-calculates contrasting color (white/black) based on `primary_color` brightness.

### 🔘 Secondary Actions

| Brand Settings Field | → | Owl Theme Field | Controls |
|---------------------|---|-----------------|----------|
| `secondary_color` | → | `secondary_buttons_background_color` | Secondary button backgrounds |
| `secondary_button_text_color` | → | `secondary_buttons_text_color` | Text on secondary buttons |

### 📝 Text & Typography

| Brand Settings Field | → | Owl Theme Field | Controls |
|---------------------|---|-----------------|----------|
| `text_primary_color` | → | `sidebar_text_color` | Sidebar menu text |
| `text_primary_color` | → | `cards_title_text_color` | Workspace card headers |
| `text_secondary_color` | → | `cards_text_color` | Workspace card descriptions |

### 🏗️ Backgrounds & Workspace

| Brand Settings Field | → | Owl Theme Field | Controls |
|---------------------|---|-----------------|----------|
| `background_primary_color` | → | `main_page_background_color` | Workspace background |
| `background_primary_color` | → | `background_color` | General page background |
| `background_primary_color` | → | `form_background_color` | Form view backgrounds |
| `background_primary_color` | → | `list_page_background_color` | List view backgrounds |
| `background_primary_color` | → | `cards_background_color` | Workspace shortcut cards |
| `background_secondary_color` | → | `sidebar_background_color` | Left sidebar background |
| `background_secondary_color` | → | `main_page_card_container_background_color` | Card container areas |

### 🖼️ Branding Assets

| Brand Settings Field | → | Owl Theme Field | Controls |
|---------------------|---|-----------------|----------|
| `logo` | → | `app_logo` | Organization logo in desk |

## How to Control Breadcrumb & Document Name Colors

### Problem
You want to control the text color of:
- Document names in breadcrumb trail (top left)
- Workspace/DocType names in the navbar

### Solution
Set the `primary_button_text_color` field in Brand Settings:

```python
# Example: White text on red navbar
primary_color = "#cf3131"              # Red navbar background
primary_button_text_color = "#ffffff"  # White breadcrumb/navbar text
```

```python
# Example: Black text on light navbar
primary_color = "#f0f0f0"              # Light gray navbar background
primary_button_text_color = "#333333"  # Dark breadcrumb/navbar text
```

### Auto-Calculation Fallback
If you don't set `primary_button_text_color`, the system automatically calculates it:
- Brightness > 128 → Black text (#000000)
- Brightness ≤ 128 → White text (#ffffff)

This uses the `get_contrasting_text_color()` method which implements the standard perceived brightness formula:
```
brightness = (R * 299 + G * 587 + B * 114) / 1000
```

## Field Reuse Strategy

Several Brand Settings fields are intentionally reused across multiple Owl Theme settings for consistency:

### `primary_color` (Used 3 times)
- Navbar background
- Primary buttons
- Creates unified primary brand identity

### `primary_button_text_color` (Used 3 times)
- Navbar text (breadcrumbs)
- App/workspace name
- Primary button text
- Ensures text remains visible on primary color backgrounds

### `background_primary_color` (Used 5 times)
- Workspace background
- Form backgrounds
- List backgrounds
- Card backgrounds
- General page background
- Creates clean, consistent workspace experience

### `background_secondary_color` (Used 2 times)
- Sidebar background
- Card container backgrounds
- Provides visual depth/hierarchy

### `text_primary_color` (Used 2 times)
- Sidebar text
- Card title text
- Primary readable text across UI

## Usage Instructions

### 1. Update Brand Settings
Navigate to **Brand Settings** and modify colors:
```
Setup → Brand Settings
```

### 2. Automatic Sync
When you save Brand Settings, `sync_to_owl_theme()` runs automatically via the `on_update()` hook.

### 3. Manual Sync (if needed)
```python
# From Frappe Console
frappe.get_single("Brand Settings").sync_to_owl_theme()
```

### 4. Clear Cache
After changes, always clear cache to see updates:
```bash
bench --site dev.veganisme.net clear-cache
```

### 5. Force Rebuild
If changes don't appear, force rebuild CSS:
```python
# From Frappe Console or API
frappe.call("verenigingen.verenigingen.doctype.brand_settings.brand_settings.force_rebuild_css")
```

## Testing the Sync

Use the built-in test function to verify the integration:
```python
# From Frappe Console
result = frappe.call("verenigingen.verenigingen.doctype.brand_settings.brand_settings.test_owl_theme_integration")
frappe.utils.pretty_print(result)
```

This will report:
- ✅ Owl Theme detection status
- ✅ Sync functionality
- ✅ Color synchronization verification
- ✅ Auto-sync trigger test

## Common Scenarios

### Scenario 1: Dark Navbar with White Text
```
primary_color = "#1a1a1a" (dark gray/black)
primary_button_text_color = "#ffffff" (white)
```
Result: Dark navbar with white breadcrumbs, workspace names, and button text

### Scenario 2: Brand Color Navbar with Auto Text
```
primary_color = "#cf3131" (red)
primary_button_text_color = <leave empty>
```
Result: Red navbar with auto-calculated white text (brightness < 128)

### Scenario 3: Light Theme
```
primary_color = "#ffffff" (white)
primary_button_text_color = "#333333" (dark gray)
background_primary_color = "#f8f9fa" (light gray)
background_secondary_color = "#e9ecef" (slightly darker gray)
```
Result: Light, minimal interface with dark text

## Troubleshooting

### Breadcrumb text is invisible
**Cause**: `primary_button_text_color` matches `primary_color`
**Fix**: Set contrasting `primary_button_text_color` (white on dark, black on light)

### Changes don't appear in desk
**Cause**: Cache not cleared or sync didn't run
**Fix**:
1. `bench clear-cache`
2. Hard refresh browser (Ctrl+Shift+R)
3. Check Owl Theme Settings to verify sync occurred

### Owl Theme Settings show old colors
**Cause**: Sync failed or didn't run
**Fix**: Manually trigger sync:
```python
frappe.get_single("Brand Settings").sync_to_owl_theme()
```

### Auto-calculated text color is wrong
**Cause**: Edge case with brightness calculation
**Fix**: Explicitly set `primary_button_text_color` to override auto-calculation

## Advanced: Direct Owl Theme Customization

If you need more granular control beyond Brand Settings:

1. Navigate to **Owl Theme Settings**
2. Directly modify specific fields
3. This bypasses Brand Settings sync
4. **Warning**: Manual Owl Theme changes will be overwritten next time Brand Settings syncs

For permanent customization beyond Brand Settings, modify the `sync_to_owl_theme()` method in:
```
verenigingen/verenigingen/doctype/brand_settings/brand_settings.py
```

## Related Documentation

- Brand Settings DocType: `verenigingen/verenigingen/doctype/brand_settings/`
- Owl Theme Settings: `/apps/owl_theme/owl_theme/doctype/owl_theme_settings/`
- Portal CSS Generation: `verenigingen/utils/brand_css_generator.py`
- Security Framework: `docs/features/ACCOUNT_CREATION_SYSTEM.md`
