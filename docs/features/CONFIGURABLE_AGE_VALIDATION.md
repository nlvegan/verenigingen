# Configurable Age Validation System

**Date**: 2025-09-11
**Purpose**: Implement configurable age validation settings for membership, volunteer, and voting eligibility
**Impact**: Enables organizations to customize age requirements through Verenigingen Settings interface

## Overview

The Verenigingen platform now supports configurable age validation through the `AgeValidator` utility class. Previously, age limits were hardcoded throughout the codebase. This enhancement centralizes age validation logic and makes it configurable through the Verenigingen Settings DocType.

## Features

### Configurable Age Settings

Age requirements can now be configured through **Setup > Verenigingen Settings > Age Validation Settings**:

| Setting                    | Default | Description                                               |
| -------------------------- | ------- | --------------------------------------------------------- |
| **Minimum Membership Age** | 16      | Minimum age required for membership eligibility           |
| **Minimum Volunteer Age**  | 16      | Minimum age required for volunteer activities             |
| **Minimum Voting Age**     | 18      | Minimum age required for voting in organizational matters |
| **Minimum Student Age**    | 14      | Minimum age for student membership types                  |
| **Minimum Youth Age**      | 12      | Minimum age for youth membership categories               |
| **Minimum Senior Age**     | 65      | Minimum age for senior membership benefits                |

### Context-Aware Validation

The `AgeValidator` supports different validation contexts:

- **membership**: General membership eligibility
- **volunteer**: Volunteer activity participation
- **voting**: Voting rights and governance participation
- **student_membership**: Student-specific membership types
- **youth_membership**: Youth-specific membership categories
- **senior_membership**: Senior-specific membership benefits

## Usage Examples

### Basic Age Validation

```python
from verenigingen.utils.validation_utilities import AgeValidator

# Validate membership eligibility
result = AgeValidator.validate_age("1990-01-01", context="membership")
if result.is_valid:
    print(f"Member age: {result.age_years:.1f} years")
else:
    print(f"Validation error: {result.message}")
```

### Membership Type-Specific Validation

```python
# Validate age for specific membership types
result = AgeValidator.validate_membership_age_for_type("2000-01-01", "Student")
if result.is_valid:
    print("Eligible for student membership")
```

### Custom Age Overrides

```python
# Use custom age limits when needed
result = AgeValidator.validate_age(
    birth_date="1995-06-15",
    context="volunteer",
    custom_min_age=18,  # Override default with custom minimum
    throw_on_error=False
)
```

### Parental Consent Support

```python
# Allow under-age members with parental consent
result = AgeValidator.validate_age(
    birth_date="2007-01-01",  # 17 years old
    context="membership",
    allow_parental_consent=True
)
if result.warning:
    print(f"Warning: {result.warning}")  # "Parental consent required..."
```

## Configuration Management

### Accessing Settings

The validation system automatically reads configuration from Verenigingen Settings:

```python
# Settings are automatically loaded from DocType
settings = frappe.get_single("Verenigingen Settings")
min_age = settings.minimum_membership_age or 16  # Fallback to default
```

### Migration Support

Existing installations are automatically configured with default values through the migration patch `configure_age_validation_settings.py`.

### Fallback Behavior

If settings cannot be loaded or are not configured:

1. System uses hardcoded defaults from validation utility
2. Error is logged but validation continues
3. System administrators receive notification to configure settings

## API Reference

### AgeValidator Class

#### `validate_age(birth_date, context="membership", **kwargs)`

Validates age requirements with context-aware business rules.

**Parameters:**

- `birth_date` (str|date): Birth date to validate
- `context` (str): Validation context (membership, volunteer, voting, etc.)
- `custom_min_age` (int, optional): Override minimum age requirement
- `custom_max_age` (int, optional): Override maximum age requirement
- `allow_parental_consent` (bool): Allow under-age with parental consent
- `throw_on_error` (bool): Whether to throw exception on validation failure

**Returns:** `AgeValidationResult` object with validation status and details

#### `validate_membership_age_for_type(birth_date, membership_type, **kwargs)`

Validates age requirements for specific membership types.

**Parameters:**

- `birth_date` (str|date): Birth date to validate
- `membership_type` (str): Type of membership (Student, Youth, Senior, etc.)
- `throw_on_error` (bool): Whether to throw exception on validation failure

### AgeValidationResult Class

Result object containing validation outcome:

**Properties:**

- `is_valid` (bool): Whether validation passed
- `age_years` (float): Calculated age in years with decimal precision
- `message` (str): Error message if validation failed
- `warning` (str): Warning message for edge cases (e.g., parental consent required)

## Implementation Details

### Configuration Loading

The system uses a hierarchical approach to load age settings:

1. **Verenigingen Settings DocType** (highest priority) - Runtime configurable values
2. **Context defaults** (fallback) - Hardcoded defaults per validation context
3. **Emergency defaults** (last resort) - System-wide minimum values

### Performance Optimization

- Settings are cached automatically by Frappe's SingleDocType system
- Validation logic is optimized for high-frequency operations
- Database queries are minimized through intelligent caching

### Error Handling

Robust error handling ensures system reliability:

```python
try:
    result = AgeValidator.validate_age(birth_date)
except ValidationError as e:
    frappe.throw(str(e))  # User-friendly error message
```

## Migration from Previous System

### Automatic Migration

The `configure_age_validation_settings.py` migration patch automatically:

1. Sets default age values in Verenigingen Settings
2. Preserves any existing custom configurations
3. Provides fallback values for new installations
4. Logs migration status for audit purposes

### Manual Migration

For custom implementations using the old system:

```python
# Old approach (deprecated)
if member_age < 16:
    frappe.throw("Member must be at least 16 years old")

# New approach (recommended)
from verenigingen.utils.validation_utilities import AgeValidator
result = AgeValidator.validate_age(birth_date, context="membership")
if not result.is_valid:
    frappe.throw(result.message)
```

## Business Rules

### Default Age Requirements

The system implements standard age requirements for Dutch associations:

- **Membership**: 16 years (legal age for association membership in Netherlands)
- **Volunteer**: 16 years (aligned with membership age)
- **Voting**: 18 years (standard voting age)
- **Student**: 14 years (secondary education age)
- **Youth**: 12 years (pre-teen programs)
- **Senior**: 65 years (retirement age)

### Parental Consent Logic

For members between 16-17 years:

- Regular membership allowed with parental consent warning
- Youth-specific programs available without restrictions
- Voting rights restricted until age 18

### Maximum Age Validation

The system validates against unrealistic ages:

- Maximum age set to 120 years for data quality
- Warning issued for ages over 100 years
- Validation error for ages over maximum threshold

## Security Considerations

### Input Validation

- All birth dates validated for format and logical constraints
- Future dates rejected with clear error messages
- Invalid date formats handled gracefully

### Permission Checks

- Only authorized users can modify age validation settings
- System Manager and Verenigingen Administrator roles have configuration access
- Audit logging for all configuration changes

## Troubleshooting

### Common Issues

**Issue**: "Validation utilities not loading"
**Solution**: Ensure `validation_utilities.py` is in the Python path

**Issue**: "Settings not found" error
**Solution**: Run migration to create default settings: `bench migrate`

**Issue**: "Age validation too strict"
**Solution**: Adjust minimum age settings in Verenigingen Settings

### Debug Mode

Enable debug logging for age validation:

```python
import logging
logging.getLogger("verenigingen.utils.validation_utilities").setLevel(logging.DEBUG)
```

## Future Enhancements

### Planned Features

1. **Regional Compliance**: Support for different countries' legal age requirements
2. **Granular Permissions**: Role-based age requirement overrides
3. **Audit Trail**: Comprehensive logging of age validation decisions
4. **Bulk Validation**: Efficient validation for large member imports

### Extension Points

The system is designed for easy extension:

```python
# Custom validation context
AgeValidator.CONTEXTS["custom_program"] = {
    "min_age": 21,
    "max_age": 65,
    "error_template": _("Custom program requires age 21-65")
}
```

## Conclusion

The configurable age validation system provides:

✅ **Flexibility**: Customizable age requirements through user interface
✅ **Consistency**: Centralized validation logic across all modules
✅ **Reliability**: Robust error handling and fallback mechanisms
✅ **Performance**: Optimized for high-frequency validation operations
✅ **Maintainability**: Single source of truth for age-related business rules

This enhancement significantly improves the platform's adaptability to different organizational requirements while maintaining data integrity and user experience quality.
