# IBAN Validation Enhancement

## Overview
Enhanced the membership application form to perform comprehensive IBAN validation with mod-97 checksum at multiple points in the user journey, rather than only on final form submission.

## Implementation Details

### 1. Enhanced Validation Logic
- **Location**: `/verenigingen/public/js/membership_application.js`
- **Methods Added**:
  - `performIBANValidation(iban)` - Comprehensive IBAN validation with mod-97 checksum
  - `deriveBICFromIBAN(iban)` - Automatic BIC derivation for Dutch banks
  - `getBankNameFromIBAN(iban)` - Bank identification for user feedback

### 2. Validation Triggers
IBAN validation now occurs at three key points:

1. **On Blur** (when user leaves IBAN field)
   - Immediate feedback with error messages
   - Auto-formatting of valid IBANs
   - Automatic BIC field population for Dutch banks

2. **Step Validation** (when moving to next step)
   - Prevents progression with invalid IBAN
   - Shows specific error messages

3. **Confirmation Page** (final review)
   - Re-validates IBAN before submission
   - Shows bank name and BIC if available
   - Highlights any validation errors

### 3. Features Implemented

#### Comprehensive Validation
- **Mod-97 Checksum**: Detects typos and invalid IBANs
- **Country-Specific Length**: Validates IBAN length per country
- **Format Validation**: Ensures proper IBAN structure
- **Character Validation**: Checks for invalid characters

#### User Experience Enhancements
- **Auto-Formatting**: Formats IBANs with spaces (e.g., `NL91 ABNA 0417 1643 00`)
- **Bank Identification**: Shows bank name for Dutch IBANs
- **BIC Auto-Fill**: Automatically fills BIC field for supported Dutch banks
- **Clear Error Messages**: Specific feedback like "Dutch IBAN must be 18 characters"

#### Supported Countries
- Netherlands (NL) - 18 characters
- Belgium (BE) - 16 characters
- Germany (DE) - 22 characters
- France (FR) - 27 characters
- United Kingdom (GB) - 22 characters
- Spain (ES) - 24 characters
- Italy (IT) - 27 characters
- And 12 more European countries

### 4. Dutch Bank Support
Automatic BIC derivation and bank name display for:
- ABN AMRO (ABNA → ABNANL2A)
- ING (INGB → INGBNL2A)
- Rabobank (RABO → RABONL2U)
- Triodos Bank (TRIO → TRIONL2U)
- SNS Bank (SNSB → SNSBNL2A)
- ASN Bank (ASNB → ASNBNL21)
- Knab (KNAB → KNABNL2H)
- Bunq (BUNQ → BUNQNL2A)
- RegioBank (RBRB → RBRBNL21)

### 5. Visual Feedback
- **Valid IBAN**: Green checkmark with bank name
- **Invalid IBAN**: Red X with specific error message
- **BIC Field**: Auto-filled and locked when derivable

### 6. Files Created/Modified

#### Modified Files
- `/verenigingen/public/js/membership_application.js` - Added validation methods
- `/verenigingen/hooks.py` - Added CSS inclusion

#### New Files
- `/verenigingen/public/js/utils/iban-validator.js` - Reusable IBAN validation module
- `/verenigingen/public/css/iban-validation.css` - Styling for validation feedback
- `/tests/unit/iban-validation.spec.js` - Unit tests (21 tests)
- `/tests/test_iban_validation_frontend.js` - Integration test examples

### 7. Testing
- **Unit Tests**: 21 tests covering all validation scenarios
- **Integration Tests**: Validation flow testing
- **Total Test Coverage**: 107 JavaScript tests, all passing

## Benefits
1. **Early Error Detection**: Users get immediate feedback on IBAN errors
2. **Reduced Form Abandonment**: Clear guidance helps users fix errors immediately
3. **Improved Data Quality**: Invalid IBANs cannot proceed through the form
4. **Better User Experience**: Auto-formatting and bank identification
5. **Time Savings**: Automatic BIC derivation eliminates manual entry

## Technical Notes
- Validation logic matches server-side Python validation in `iban_validator.py`
- Uses chunked mod-97 calculation to avoid JavaScript number precision issues
- Supports both uppercase and lowercase input
- Handles IBANs with or without spaces
- Backward compatible with existing form submissions
