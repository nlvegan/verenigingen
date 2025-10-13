# Legacy Validation Code

**Status:** Archived as of 2025-10-13  
**Reason:** Validation logic refactored into DocType controllers

## Background

This directory contains the original `verenigingen/validations.py` file which defined standalone validation functions:
- `validate_termination_request()` 
- `validate_verenigingen_settings()`
- `validate_membership_grace_period()`

These functions were originally intended to be called via Frappe hooks, but the validation logic was later moved directly into the respective DocType controller classes.

## Current Location of Validation Logic

- **Termination Request Validation:** `verenigingen/doctype/membership_termination_request/membership_termination_request.py` (method: `validate_termination_request()`)
- **Settings Validation:** `verenigingen/doctype/verenigingen_settings/verenigingen_settings.py` (method: `validate()`)
- **Grace Period Validation:** `verenigingen/doctype/membership/membership.py` (method: `validate_grace_period()`)

## Archived Files

- `validations.py` - The original standalone validation module
