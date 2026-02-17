# Comprehensive UX Review: Verenigingen Member Portal

**Date**: 2026-02-17
**Reviewer**: UX Expert Agent (Claude)

---

## 1. Executive Summary

The Verenigingen member portal is a feature-rich system serving Dutch non-profit association members with pages for membership management, payments, volunteering, chapter administration, and document access. The portal demonstrates strong domain knowledge and functional completeness, but suffers from significant inconsistencies that undermine the user experience.

**Top-level findings:**

- **Architectural fragmentation**: Two competing versions of the main portal exist (`member_portal.html` and `member_portal_new.html`), each extending different base templates. This creates maintenance burden and user confusion.
- **Inconsistent technology stack**: Pages mix Tailwind CSS, Bootstrap grid classes, raw CSS, and `@apply` directives without a unifying approach. Some pages import Tailwind, others rely on Bootstrap panels.
- **Accessibility gaps**: No pages implement comprehensive ARIA labeling, keyboard navigation, or screen reader support. One page (`my_dues_schedule.html`) actively blocks pinch-to-zoom with `user-scalable=no`.
- **Inconsistent error handling**: Some pages handle missing member records gracefully (member_portal.py), while others throw hard exceptions (member_portal_new.py, membership_adjustment.py). Users encountering errors see wildly different experiences.
- **Navigation confusion**: Pages extend three different base templates (`base_portal.html`, `templates/web.html`, and one extends `base_portal.html` which itself extends `web.html`), resulting in inconsistent sidebar presence and layout widths.

**Overall UX maturity**: The portal is at the "functional but inconsistent" stage. Individual pages work well, but the system does not feel like a cohesive product when navigating between pages.

---

## 2. Page-by-Page Review

### 2.1 Member Portal (Main Dashboard)

**File**: `vereinigingen/templates/pages/member_portal.html` (~691 lines)
**Controller**: `vereinigingen/templates/pages/member_portal.py` (~871 lines)

**Strengths:**
- Graceful handling of the "no member record" case with a branded warning message
- Well-organized sections: Header, Member Info, Quick Actions, Payment Status, Portal Links, Recent Activity
- Wide layout wrapper provides generous working space (90vw, max 1600px)
- Context-aware quick actions that adapt to member's payment, address, and volunteer status

**Issues:**

1. **Visual Hierarchy - Emoji icons in section headings**: The portal sections use emoji characters alongside Font Awesome 4 icons. Emojis render differently across browsers, operating systems, and devices.
   - **Recommendation**: Replace all emoji icons with Font Awesome icons or SVG icons for cross-platform visual consistency.

2. **Information Architecture - Too many portal sections visible at once**: The main portal shows 6 portal section cards plus Quick Actions, Payment Status, and Recent Activity. This creates cognitive overload.
   - **Recommendation**: Prioritize the top 3-4 most-used sections above the fold; collapse the rest into an "All Services" expandable area.

3. **Interaction Design - `MemberPortal.toggleChapterFolder` JavaScript function**: The chapter document folder toggle lacks visual affordance - users cannot tell which folders are expandable before clicking.
   - **Recommendation**: Add a chevron/caret icon that rotates on toggle.

4. **Content - Untranslated title suffix in `member_portal_new.html`** (line 3):
   ```html
   {% block title %}{{ _("Member Portal") }} - TailwindCSS{% endblock %}
   ```
   The "- TailwindCSS" suffix is visible to end users in the browser tab.
   - **Recommendation**: Remove the "- TailwindCSS" suffix immediately.

5. **Error Handling - Controller throws exception for non-members in `member_portal_new.py`**:
   ```python
   if not member:
       frappe.throw(_("No member record found for your account"), frappe.DoesNotExistError)
   ```
   In contrast, `member_portal.py` handles this gracefully with a branded error page.
   - **Recommendation**: Adopt the graceful pattern from `member_portal.py` for all portal pages.

6. **Performance - Controller makes 10+ database queries** in `member_portal.py`: No caching is employed.
   - **Recommendation**: Consolidate related queries and consider caching for data that does not change on every page load.

### 2.2 Member Portal New (Duplicate)

**File**: `vereinigingen/templates/pages/member_portal_new.html` (~471 lines)
**Controller**: `vereinigingen/templates/pages/member_portal_new.py` (~458 lines)

**Critical Issue**: This page is a partial duplicate of `member_portal.html` with significant feature gaps:
- Missing: chapter information, document browser, organization logo, graceful no-member-record handling
- Extends `templates/web.html` instead of `templates/base_portal.html` (no sidebar)
- Contains duplicated link card to `/personal_details` in both "Account Management" and "Membership Services" sections
- Links to `/my_account` and `/resources` which may not exist as portal pages
- Billing frequency detection uses fragile string matching on membership type name

**Recommendation**: Decide whether to keep one version and retire the other, or merge the best features from both.

### 2.3 Payment Dashboard

**File**: `vereinigingen/templates/pages/payment_dashboard.html` (~1734 lines)
**Controller**: `vereinigingen/templates/pages/payment_dashboard.py` (~305 lines)

**Strengths:**
- Tab-based organization (Overview, Payment Methods, Payment History, Settings) is excellent
- IBAN auto-formatting with live validation
- Payment history with filtering, pagination, and CSV export
- Mollie subscription management

**Issues:**

1. **Bug - Undefined variable reference**: The code references `topBadge` which is never defined in scope.
2. **Performance - Page is 1734 lines**: All tabs' HTML, CSS (~300 lines), and JS (~700 lines) load regardless of which tab the user views.
3. **Error Handling - Hardcoded notification settings**: `get_notification_settings()` always returns all values as `True`.
4. **Accessibility - Tab navigation**: No ARIA `role="tablist"`, `role="tab"`, and `role="tabpanel"` attributes. Keyboard users cannot navigate between tabs.
5. **Interaction Design - Retry payment modal**: Does not clearly communicate what payment is being retried or the consequences.

### 2.4 Address Change

**File**: `vereinigingen/templates/pages/address_change.html` (~443 lines)
**Controller**: `vereinigingen/templates/pages/address_change.py` (~395 lines)

**Strengths:**
- Two-step flow (form then confirmation comparison) prevents accidental submissions
- Has breadcrumbs (unique among portal pages)
- Strong security in the controller

**Issues:**

1. **Consistency - Only page with breadcrumbs**: Jarring experience when navigating from other pages.
2. **Consistency - Uses Bootstrap grid** mixed with custom CSS, while other pages use Tailwind.
3. **Consistency - Extends `templates/web.html`** directly instead of `base_portal.html`.
4. **Content - Hardcoded English placeholder**: `"Enter your street address"` is not wrapped in a translation function.
5. **Interaction Design - Uses jQuery for all interactions** while other pages use vanilla JavaScript.
6. **Accessibility - Form validation uses `alert()`** instead of inline error messages.

### 2.5 Personal Details

**File**: `vereinigingen/templates/pages/personal_details.html` (~648 lines)
**Controller**: `vereinigingen/templates/pages/personal_details.py` (~406 lines)

**Strengths:**
- Good Dutch-specific UX: tussenvoegsel field with explanation, pronoun selection
- Image upload with preview and file validation
- Security: parameter tampering detection with audit logging
- Change tracking with field-level diff

**Issues:**

1. **Layout - Custom width wrapper** with different breakpoints than any other page (60vw).
2. **Interaction Design - Uses native form POST** (not AJAX), causing full page reload.
3. **Accessibility - Validation uses `alert()`**.
4. **Content - Pronoun options not translated**.

### 2.6 Membership Adjustment

**File**: `vereinigingen/templates/pages/membership_adjustment.html` (~887 lines)
**Controller**: `vereinigingen/templates/pages/membership_adjustment.py` (~940 lines)

**Strengths:**
- Well-designed 3-column layout
- Fee slider synced with number input
- Income-based contribution calculator
- Dynamic button text based on approval requirement

**Issues:**

1. **Bug - Console.log statements in production code**: Multiple `console.log` statements left in template.
2. **Error Handling - Hard throw on no membership**: Shows raw error instead of helpful message.
3. **Content - Minimum fee calculation is opaque**: Users only see the final number with no explanation.

### 2.7 Contact Request

**File**: `vereinigingen/templates/pages/contact_request.html` (~433 lines)
**Controller**: `vereinigingen/templates/pages/contact_request.py` (~147 lines)

**Strengths:**
- Clean form with request types, urgency levels, and preferred contact method
- Shows recent requests with status badges
- Graceful no-member-record handling

**Issues:**

1. **Security - XSS risk in `showAlert` function**: Creates HTML without escaping user content.
2. **Interaction Design - Uses `fetch()` API** instead of `frappe.call()`, missing CSRF protection.
3. **Content - Request types hardcoded in English** without `_()` wrapping.

### 2.8 My Dues Schedule

**File**: `vereinigingen/templates/pages/my_dues_schedule.html` (~735 lines)
**Controller**: `vereinigingen/templates/pages/my_dues_schedule.py` (~338 lines)

**Strengths:**
- Payment calendar with interactive day clicks
- Timeline view of payments
- Quick stats cards

**Issues:**

1. **Accessibility - CRITICAL: `user-scalable=no`**: Violates WCAG 2.1 SC 1.4.4, prevents users with low vision from zooming.
2. **Consistency - Uses Font Awesome 5** (`fas fa-*`) while all other pages use FA4.
3. **Localization - Calendar starts week on Sunday**: Dutch convention is Monday.
4. **Content - Hardcoded coverage calculation**: Returns `{"percentage": 75, "covered_months": 9}` always.
5. **Security - Export function writes to temp directory** but returns a Frappe file URL. Export is broken.

### 2.9 Chapter Dashboard

**File**: `vereinigingen/templates/pages/chapter_dashboard.html` (~1002 lines)
**Controller**: `vereinigingen/templates/pages/chapter_dashboard.py` (~1080 lines)

**Strengths:**
- Role-based permissions with detailed capability matrix
- Comprehensive financial summary
- Dues payment status with overdue severity breakdown
- Board documents with nested folder structure

**Issues:**

1. **Content - Many hardcoded English strings**: Not wrapped in `_()` for translation.
2. **Interaction Design - Links to `/app/` backend routes**: Breaks portal experience by sending users to Desk.
3. **Performance - Controller calls `get_member_overview` twice**: Duplicates database queries.
4. **Layout - ~250 lines of `@apply`-based CSS**: Inline Tailwind `@apply` likely not compiled.

### 2.10 My Teams

**File**: `vereinigingen/templates/pages/my_teams.html` (~322 lines)

**Issues:**
1. Uses emoji icons in empty states
2. Extends `templates/web.html` (no sidebar)
3. ~240 lines of inline CSS
4. Team cards lack semantic structure and proper disabled state

### 2.11 My Addresses

**File**: `vereinigingen/templates/pages/my_addresses.html` (~87 lines)

**Issues:**
1. Uses Bootstrap 3 panels (completely absent from all other pages)
2. Very simple page — could merge into personal details
3. **Security - Uses `|safe` filter** on `address_display` — XSS vector

### 2.12 Volunteer Portal Pages

**Dashboard** (`volunteer/dashboard.html`): Good loading/error/content state management.
**Expenses** (`volunteer/expenses.html`): Comprehensive expense submission with statistics.
**Profile** (`volunteer/profile.html`): Volunteer skills and chapter memberships.
**Skills** (`volunteer/skills.html`): Skill management with proficiency levels.
**Apply** (`volunteer/apply.html`): Application form for volunteer positions.

### 2.13 Board Portal Pages

**Document Upload** (`board/document_upload.html`): Upload documents for organizations.
**Document Browser** (`board/document_browser.html`): Browse organization documents.

### 2.14 Includes and Shared Components

- **web_sidebar.html**: ~80 lines inline style, ~25 lines inline script. Active state detection breaks with query parameters.
- **portal_sidebar.html**: ~113 lines inline CSS. Duplicates sidebar functionality.
- **skills_dashboard_widget.html**: Auto-refreshes every 5 minutes even when not viewed. Uses Bootstrap 5 classes while parents may use Bootstrap 3/4.
- **expense_statistics_cards.html**: Currency formatting uses `{:,.2f}` which doesn't match Dutch locale (period for thousands, comma for decimals).
- **expense_error_banner.html**: Error message output without HTML escaping.
- **volunteer_portal.css**: Overrides `.card` globally. Focus styles remove outline (accessibility regression).

---

## 3. Cross-Cutting Issues

### 3.1 Base Template Inconsistency

| Template | Pages |
|----------|-------|
| `base_portal.html` (has sidebar) | `member_portal.html`, `payment_dashboard.html`, `chapter_dashboard.html` |
| `templates/web.html` (no sidebar) | `member_portal_new.html`, `address_change.html`, `personal_details.html`, `my_teams.html`, `my_addresses.html`, `my_dues_schedule.html`, `team_members.html` |
| Unclear/mixed | `contact_request.html`, `membership_adjustment.html` |

**Recommendation**: All portal pages should extend one consistent base template with sidebar navigation.

### 3.2 CSS Framework Chaos

The portal uses at least 5 different CSS approaches simultaneously:
1. Tailwind utility classes
2. Tailwind `@apply` directives in `<style>` blocks
3. Bootstrap 3 classes
4. Bootstrap 4/5 classes
5. Raw custom CSS with hardcoded colors

**Recommendation**: Choose Tailwind as primary and migrate all pages.

### 3.3 Max-Width Inconsistency

| Page | Max Width |
|------|-----------|
| `member_portal.html` | 90vw / max 1600px |
| `member_portal_new.html` | `max-w-7xl` (~1280px) |
| `personal_details.html` | 60vw |
| `my_teams.html` | 1200px |
| `team_members.html` | 1000px |
| `my_addresses.html` | Bootstrap `col-md-8 col-md-offset-2` (~66%) |

**Recommendation**: Standardize on 2 widths: one for dashboards (1400-1600px) and one for forms (800-1000px).

### 3.4 Icon System Inconsistency

| Icon System | Pages |
|-------------|-------|
| Font Awesome 4 (`fa fa-*`) | Most pages |
| Font Awesome 5 (`fas fa-*`) | my_dues_schedule |
| Emoji characters | my_teams, member_portal (some) |
| Inline SVG | member_portal (warning icon) |

**Recommendation**: Use Font Awesome 4 consistently (loaded by Frappe).

### 3.5 Translation Coverage Gaps

Multiple pages have untranslated user-facing strings. For a Dutch-language application, this is a significant gap.

**Recommendation**: Systematic audit — every user-facing string must be wrapped in `_()` (Python) or `__()` (JavaScript).

### 3.6 Authentication and Error Handling Patterns

Three different patterns used for auth checks, and inconsistent error handling for missing member records.

**Recommendation**: Create a shared decorator/utility for consistent auth and member validation.

### 3.7 JavaScript Pattern Inconsistency

| Pattern | Pages |
|---------|-------|
| jQuery (`$`) | address_change, web_sidebar |
| `frappe.call()` | payment_dashboard, membership_adjustment |
| `fetch()` API | contact_request |
| Native form POST | personal_details |
| Vanilla DOM | my_dues_schedule |

**Recommendation**: Standardize on `frappe.call()` for APIs and vanilla JS for DOM.

---

## 4. Prioritized Recommendations

### Critical (Fix Immediately)

1. Remove `user-scalable=no` from `my_dues_schedule.html` — WCAG violation
2. Remove "- TailwindCSS" from `member_portal_new.html` title — dev artifact
3. Fix hardcoded coverage data in `my_dues_schedule.py` — misleading data
4. Fix undefined `topBadge` reference in `payment_dashboard.html` — JS error
5. Remove `console.log` statements from `membership_adjustment.html` — dev artifacts

### High Priority (Next Sprint)

6. Standardize base template for all portal pages
7. Standardize error handling with shared pattern
8. Fix XSS vectors (`|safe` filter, `showAlert`, `expense_error_banner`)
9. Fix export function in `my_dues_schedule.py`
10. Standardize icon system

### Medium Priority (Next Quarter)

11. Consolidate the two member portal versions
12. Standardize CSS approach (choose Tailwind)
13. Standardize max-widths
14. Add translation wrappers to all user-facing strings
15. Standardize JavaScript patterns
16. Add ARIA attributes to tab components
17. Fix notification settings in payment_dashboard.py

### Low Priority (Backlog)

18. Extract inline CSS/JS into separate bundled files
19. Scope volunteer_portal.css overrides
20. Fix calendar week start to Monday
21. Fix currency formatting for Dutch locale
22. Reduce database queries with caching
23. Fix duplicate `get_member_overview` call
24. Consider merging my_addresses into personal_details

---

## 5. Quick Wins

| Quick Win | File | Effort | Impact |
|-----------|------|--------|--------|
| Remove `user-scalable=no` | `my_dues_schedule.html` | 1 min | Accessibility fix |
| Remove "- TailwindCSS" from title | `member_portal_new.html` | 1 min | Removes dev artifact |
| Remove `console.log` statements | `membership_adjustment.html` | 5 min | Removes dev artifacts |
| Wrap request types in `_()` | `contact_request.py` | 5 min | Translation support |
| Add `aria-disabled="true"` to disabled buttons | `my_teams.html` | 2 min | Accessibility |
| Remove `outline: none` from volunteer_portal.css | `volunteer_portal.css` | 2 min | Accessibility fix |
| Fix hardcoded coverage data comment | `my_dues_schedule.py` | 5 min | Add "placeholder" label or remove section |
| Translate address_change placeholder | `address_change.html` | 2 min | Translation support |
| Scope `.card` override in volunteer_portal.css | `volunteer_portal.css` | 5 min | Prevents global style leaks |
| Fix `showAlert` XSS in contact_request | `contact_request.html` | 10 min | Security fix |
