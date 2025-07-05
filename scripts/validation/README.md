# Validation Scripts

Scripts to validate features, migrations, and system integrity.

## Feature Validation (`features/`)

- **`validate_bank_details.py`** - Validate bank details functionality
- **`validate_configurable_email.py`** - Validate configurable email system
- **`validate_contact_request_implementation.py`** - Validate contact request feature implementation
- **`validate_member_portal.py`** - Validate member portal functionality
- **`validate_personal_details.py`** - Validate personal details handling
- **`test_expense_approval_fix.py`** - Validate expense claim approval workflow fix
- **`test_member_portal_fix.py`** - Validate member portal expense query fix
- **`test_chapter_membership_fix.py`** - Validate chapter membership validation fix
- **`test_chapter_membership_final.py`** - Final validation test confirming the fix works

## Migration Validation (`migrations/`)

- **`validate_contribution_amendment_rename.py`** - Validate contribution amendment rename migration

## General Validation

- **`validation_check.py`** - General system validation check

## Usage

```bash
# Validate specific features
python scripts/validation/features/validate_bank_details.py
python scripts/validation/features/validate_member_portal.py

# Validate migrations
python scripts/validation/migrations/validate_contribution_amendment_rename.py

# Run general validation
python scripts/validation/validation_check.py
```

## Validation Categories

- **Features** - Validate specific feature functionality
- **Migrations** - Verify data migration integrity
- **General** - Overall system validation

## Adding Validation Scripts

When adding validation scripts:

1. Place feature validations in `features/`
2. Place migration validations in `migrations/`
3. Include clear pass/fail criteria
4. Provide detailed error messages
5. Document what is being validated
