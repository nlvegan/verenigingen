# Brand Settings Complete Guide

**Last Updated:** 2025-11-18
**Status:** ✅ Authoritative documentation based on actual codebase

This document provides complete documentation for the Verenigingen Brand Settings system, covering both portal pages and Frappe Desk integration.

## Overview

The Brand Settings system provides centralized brand color management across:
1. **Portal Pages** (via auto-generated CSS file)
2. **Frappe Desk** (via Owl Theme synchronization)

All brand colors are defined once in Brand Settings and automatically applied throughout the application.

---

## Brand Settings Fields

### 🎨 Brand Colors (Primary Configuration)

| Field | Default | Description |
|-------|---------|-------------|
| `primary_color` | #cf3131 (Red) | Main brand color for buttons, headers, key UI elements |
| `secondary_color` | #01796f (Teal) | Supporting color for secondary buttons, complementary elements |
| `accent_color` | #663399 (Purple) | Accent color for highlights, special features, decorative elements |

### 📊 Semantic Status Colors

| Field | Default | Description |
|-------|---------|-------------|
| `success_color` | #28a745 (Green) | Success states, positive actions, confirmations |
| `warning_color` | #ffc107 (Amber) | Warnings, caution states, pending actions |
| `error_color` | #dc3545 (Red) | Errors, danger states, destructive actions |
| `info_color` | #17a2b8 (Blue) | Information, neutral notifications |

### 📝 Text & Background Colors

| Field | Default | Description |
|-------|---------|-------------|
| `text_primary_color` | #333333 (Dark Gray) | Primary readable text on light backgrounds |
| `text_secondary_color` | #666666 (Medium Gray) | Secondary/muted text, descriptions |
| `background_primary_color` | #ffffff (White) | Main page background |
| `background_secondary_color` | #f8f9fa (Light Gray) | Cards, panels, secondary backgrounds |

### 🔘 Button Text Colors (Auto-Calculated)

| Field | Default | Description |
|-------|---------|-------------|
| `primary_button_text_color` | #ffffff (White) | Text on primary color buttons (auto: black/white based on brightness) |
| `secondary_button_text_color` | #ffffff (White) | Text on secondary color buttons (auto-calculated) |
| `accent_button_text_color` | #ffffff (White) | Text on accent color buttons (auto-calculated) |

**Auto-Calculation Logic:**
- Brightness > 128 → Black text (#000000)
- Brightness ≤ 128 → White text (#ffffff)
- Formula: `(R × 299 + G × 587 + B × 114) / 1000`

### 🎯 Advanced Hover Colors (Auto-Calculated)

| Field | Default | Description |
|-------|---------|-------------|
| `primary_hover_color` | #b82828 | 15% darker than primary (hover states, gradients) |
| `secondary_hover_color` | #015a52 | 15% darker than secondary |
| `accent_hover_color` | #4d2673 | 15% darker than accent |

---

## How Brand Colors Work

### 1. CSS Generation System

When Brand Settings is saved, the system automatically generates `/sites/[site]/public/css/brand_colors.css`:

**Generated CSS Variables:**
```css
:root {
    /* Base brand colors */
    --brand-primary: #cf3131;
    --brand-secondary: #01796f;
    --brand-accent: #663399;
    --brand-success: #28a745;
    --brand-warning: #ffc107;
    --brand-error: #dc3545;
    --brand-info: #17a2b8;

    /* Complete Tailwind scale (50-900) */
    --brand-primary-50: color-mix(in srgb, var(--brand-primary) 10%, white);
    --brand-primary-100: color-mix(in srgb, var(--brand-primary) 20%, white);
    --brand-primary-200: color-mix(in srgb, var(--brand-primary) 35%, white);
    --brand-primary-300: color-mix(in srgb, var(--brand-primary) 50%, white);
    --brand-primary-400: color-mix(in srgb, var(--brand-primary) 70%, white);
    --brand-primary-500: var(--brand-primary);
    --brand-primary-600: color-mix(in srgb, var(--brand-primary) 85%, black);
    --brand-primary-700: color-mix(in srgb, var(--brand-primary) 70%, black);
    --brand-primary-800: color-mix(in srgb, var(--brand-primary) 55%, black);
    --brand-primary-900: color-mix(in srgb, var(--brand-primary) 40%, black);

    /* Contrast colors for accessibility */
    --brand-primary-contrast: #000000;  /* Auto-calculated */
    --brand-secondary-contrast: #ffffff;
    --brand-accent-contrast: #ffffff;
}
```

**Tailwind Utility Class Overrides:**
```css
/* Background colors */
.bg-primary-50 { background-color: var(--brand-primary-50) !important; }
.bg-primary-100 { background-color: var(--brand-primary-100) !important; }
/* ... through 900 */

/* Text colors */
.text-primary-600 { color: var(--brand-primary-600) !important; }
.text-secondary-500 { color: var(--brand-secondary-500) !important; }

/* Border colors */
.border-accent-200 { border-color: var(--brand-accent-200) !important; }

/* Hover states */
.hover:bg-primary-700:hover { background-color: var(--brand-primary-700) !important; }
```

### 2. Using Brand Colors in Templates

**Portal Templates** (HTML):
```html
<!-- Section header with brand accent color -->
<div class="bg-accent-50 border-accent-200">
    <h3 class="text-accent-600">💳 Dues Payment Status</h3>
</div>

<!-- Button with brand primary color -->
<button class="bg-primary-600 text-primary-contrast hover:bg-primary-700">
    Submit
</button>

<!-- Card with brand secondary -->
<div class="bg-secondary-50 border-l-4 border-secondary-400">
    <p class="text-secondary-600">Board Members</p>
</div>
```

**Direct CSS Variables:**
```css
.custom-element {
    background: var(--brand-primary);
    color: var(--brand-primary-contrast);
    border-color: var(--brand-accent-300);
}
```

### 3. Semantic vs Brand Colors

**When to use brand colors:**
- Section headers and navigation
- Buttons and interactive elements
- Cards and panel backgrounds
- Branding elements (logos, banners)

**When to use semantic colors:**
- Status indicators (success, warning, error)
- Form validation feedback
- Alert messages
- Data visualization (charts, badges)

**Example:**
```html
<!-- ✅ GOOD: Brand colors for UI structure -->
<div class="bg-primary-600 text-primary-contrast">
    <h1>Chapter Dashboard</h1>
</div>

<!-- ✅ GOOD: Semantic colors for status -->
<span class="bg-danger-50 text-danger-600">Overdue Invoice</span>
<span class="bg-success-100 text-success-700">Payment Received</span>

<!-- ❌ AVOID: Hardcoded Tailwind colors -->
<div class="bg-blue-600 text-white">  <!-- Use bg-primary-600 instead -->
```

---

## Frappe Desk Integration (Owl Theme)

### Owl Theme Synchronization

Brand Settings automatically syncs to Owl Theme Settings for Frappe Desk UI consistency.

**Key Mappings:**

| Brand Settings → | Owl Theme Field | Desk UI Element |
|------------------|-----------------|-----------------|
| `primary_color` | `navbar_background_color` | Top navbar background |
| `primary_color` | `primary_buttons_background_color` | Primary button backgrounds |
| `primary_button_text_color` | `navbar_text_color` | Breadcrumb text, navbar links |
| `primary_button_text_color` | `app_name_color` | Workspace/DocType name |
| `secondary_color` | `secondary_buttons_background_color` | Secondary buttons |
| `background_primary_color` | `main_page_background_color` | Workspace background |
| `background_primary_color` | `form_background_color` | Form backgrounds |
| `background_secondary_color` | `sidebar_background_color` | Left sidebar |
| `text_primary_color` | `sidebar_text_color` | Sidebar text |
| `logo` | `app_logo` | Organization logo |

**Automatic Sync Trigger:**
- Runs on Brand Settings `on_update()` hook
- Updates Owl Theme Settings in database
- Applies changes immediately (clear cache for browser refresh)

---

## Management Commands

### Regenerate Brand CSS

```bash
# From Frappe Console
frappe.call("verenigingen.utils.brand_css_generator.regenerate_brand_css")

# From Python
from verenigingen.utils.brand_css_generator import generate_brand_css_file
generate_brand_css_file()
```

### Check Brand Settings

```bash
# From Frappe Console
frappe.call("verenigingen.utils.brand_css_generator.check_brand_settings_and_generate")
```

### Clear Cache (Always Required After Changes)

```bash
bench --site dev.veganisme.net clear-cache
```

### Test Owl Theme Integration

```python
# From Frappe Console
result = frappe.call("verenigingen.verenigingen.doctype.brand_settings.brand_settings.test_owl_theme_integration")
frappe.utils.pretty_print(result)
```

---

## Color Selection Best Practices

### 1. Brand Color Palette

**Recommended Approach:**
- **Primary**: Your main brand color (logo color, primary actions)
- **Secondary**: Complementary color (10-30° away on color wheel)
- **Accent**: Highlight color for special elements

**Color Harmony Examples:**

**Analogous (Close colors):**
```
Primary: #3b82f6 (Blue)
Secondary: #8b5cf6 (Purple)
Accent: #06b6d4 (Cyan)
```

**Triadic (Balanced):**
```
Primary: #ef4444 (Red)
Secondary: #10b981 (Green)
Accent: #3b82f6 (Blue)
```

**Complementary (High contrast):**
```
Primary: #f59e0b (Orange)
Secondary: #3b82f6 (Blue)
Accent: #8b5cf6 (Purple)
```

### 2. Accessibility Guidelines

**WCAG AA Compliance:**
- Normal text: 4.5:1 contrast ratio minimum
- Large text (18px+): 3:1 contrast ratio minimum
- UI components: 3:1 contrast ratio

**Auto-Calculated Contrast:**
The system automatically calculates contrasting text colors, but verify:
```
Light backgrounds → Dark text
Dark backgrounds → Light text
```

**Test Tools:**
- [WebAIM Contrast Checker](https://webaim.org/resources/contrastchecker/)
- Chrome DevTools Accessibility Panel
- [Coolors Contrast Checker](https://coolors.co/contrast-checker)

### 3. Semantic Color Standards

**Do NOT change these unless necessary:**
- Success: Green shades (#10b981, #22c55e)
- Warning: Amber/Yellow (#f59e0b, #fbbf24)
- Error: Red shades (#ef4444, #dc2626)
- Info: Blue shades (#3b82f6, #06b6d4)

Users expect these color associations for status indicators.

---

## Implementation Files

### Core Files:
- **Brand Settings DocType**: `verenigingen/verenigingen/doctype/brand_settings/brand_settings.py`
- **CSS Generator**: `verenigingen/utils/brand_css_generator.py`
- **Generated CSS**: `/sites/[site]/public/css/brand_colors.css`

### Hooks:
```python
# hooks.py
doc_events = {
    "Brand Settings": {
        "on_update": "verenigingen.utils.brand_css_generator.generate_brand_css_file",
    }
}
```

### Template Integration:
```html
<!-- Portal page templates automatically include brand CSS -->
{% block style %}
    <link rel="stylesheet" href="/assets/css/brand_colors.css">
{% endblock %}
```

---

## Troubleshooting

### Colors Not Updating

**Symptom**: Changed Brand Settings but portal/desk still shows old colors

**Solution:**
```bash
# 1. Verify Brand Settings saved
bench --site dev.veganisme.net console
frappe.get_single("Brand Settings").primary_color

# 2. Regenerate CSS
frappe.call("verenigingen.utils.brand_css_generator.regenerate_brand_css")

# 3. Clear cache
bench --site dev.veganisme.net clear-cache

# 4. Hard refresh browser (Ctrl+Shift+R)
```

### Text Invisible on Colored Backgrounds

**Symptom**: Can't read text on primary/secondary/accent backgrounds

**Solution:**
Use `.text-primary-contrast`, `.text-secondary-contrast`, or `.text-accent-contrast`:
```html
<div class="bg-primary-600 text-primary-contrast">
    Readable text!
</div>
```

### CSS File Not Found

**Symptom**: 404 error for `/assets/css/brand_colors.css`

**Solution:**
```bash
# Check file exists
ls -la sites/dev.veganisme.net/public/css/brand_colors.css

# If missing, regenerate
bench --site dev.veganisme.net console
from verenigingen.utils.brand_css_generator import generate_brand_css_file
generate_brand_css_file()
```

### Owl Theme Not Syncing

**Symptom**: Desk shows different colors than Brand Settings

**Solution:**
```python
# Manual sync
frappe.get_single("Brand Settings").sync_to_owl_theme()

# Verify sync
owl_theme = frappe.get_single("Owl Theme Settings")
print(owl_theme.navbar_background_color)  # Should match primary_color
```

---

## Migration from Hardcoded Colors

### Step 1: Audit Current Colors

```bash
# Find hardcoded Tailwind colors
grep -r "bg-blue-\|text-red-\|border-green-" apps/verenigingen/verenigingen/templates/

# Find hardcoded hex colors
grep -r "#[0-9a-fA-F]\{6\}" apps/verenigingen/verenigingen/templates/
```

### Step 2: Replace with Brand Colors

**Before:**
```html
<div class="bg-blue-600 text-white">Header</div>
<div class="bg-green-50 border-green-200">Success</div>
```

**After:**
```html
<div class="bg-primary-600 text-primary-contrast">Header</div>
<div class="bg-success-50 border-success-200">Success</div>
```

### Step 3: Update Custom CSS

**Before:**
```css
.custom-header {
    background-color: #3b82f6;
    color: white;
}
```

**After:**
```css
.custom-header {
    background-color: var(--brand-primary);
    color: var(--brand-primary-contrast);
}
```

---

## Related Documentation

- **Owl Theme Mapping**: `docs/BRAND_SETTINGS_OWL_THEME_MAPPING.md`
- **Brand Settings DocType**: `verenigingen/verenigingen/doctype/brand_settings/`
- **CSS Generator Source**: `verenigingen/utils/brand_css_generator.py`
- **Portal Templates**: `verenigingen/templates/pages/`

---

## Version History

- **2025-11-18**: Complete rewrite based on actual codebase implementation
- **2025-01-10**: Initial Owl Theme mapping documentation
- **2025-01-01**: Brand Settings DocType creation
