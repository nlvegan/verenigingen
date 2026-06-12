# Payment Dashboard: Contextual Dues-Adjustment Action

**Date:** 2026-06-12
**Status:** Approved
**Scope:** `verenigingen/templates/pages/payment_dashboard.html` only

## Problem

The "Adjust Dues Rate" quick-action card on the member payment dashboard is
visually drowned out. Every element on the page is a white rounded card with
shadows and accent borders; the quick-action card (white background, thin
`border-primary-300`) carries the same visual weight as the passive metric
cards above it, so it reads as another info tile rather than an action.

## Goal

Members who come looking to change their dues rate should find the action
instantly, without it shouting at everyone else ("easily findable when
needed", per Foppe). Reduce competing visual noise rather than making the
button louder.

## Design

All changes in `payment_dashboard.html`:

1. **Remove the standalone quick-action card** (the "Adjust Dues Rate" tile
   between the three metric cards and the tab block, currently lines
   450–466). The tab block moves up.

2. **Add the action to the Current Schedule Details panel** (Overview tab,
   the gray `bg-gray-50` panel showing Status / Contribution Mode / Dues
   Rate / Next Invoice Date). Below the detail rows, separated by a top
   border (`border-t border-gray-200 pt-3`): an `Adjust dues rate →` link
   to `/membership_adjustment`, styled `btn-primary text-sm` — the same
   treatment as the existing "Set Up Schedule" button in the no-schedule
   fallback, so both states of the panel present the same way. Overview is
   the default active tab, so the action is visible on page load.

3. **Add a small "Adjust" link next to "Current rate"** in the SEPA Direct
   Debit setup card on the Payment Methods tab (the
   `active_dues_schedule` block, currently lines ~671–677) — the second
   place a member encounters their rate. Inline text link
   (`text-primary-600 hover:text-primary-700 font-medium`), not a button,
   to keep the SEPA card's own CTA ("Set up automatic payment") dominant.

4. **Remove the hover lift/shadow from `.financial-card`** (the
   `.financial-card:hover` rule). The three metric cards are not
   clickable; the hover affordance falsely suggests interactivity and
   competes with real actions.

5. **Delete dead `.quick-action*` CSS**: the `.quick-actions`,
   `.quick-action`, `.quick-action:hover`, `.quick-action-icon`,
   `.quick-action-title`, `.quick-action-description` rules (lines
   172–216) and the `.quick-actions` rule inside the mobile media query
   (lines 275–277). No HTML uses these classes.

## Not changed

- Page background gradient, fade/slide animations, tab styling.
- The no-schedule fallback (already links to `/membership_adjustment` via
  "Set Up Schedule").
- No JavaScript changes: the removed card has no id or event handlers.
- Translations: all new user-facing strings wrapped in `{{ _("…") }}`.

## Verification

Render the page on a test site (not veg11) logged in as a member:

- With an active dues schedule: button appears in Current Schedule Details;
  "Adjust" link appears next to "Current rate" in the SEPA card (when no
  mandate); standalone card gone; metric cards no longer lift on hover.
- Without a schedule: "Set Up Schedule" fallback unchanged.
- `grep` confirms no remaining references to the removed card or
  `.quick-action` classes.
