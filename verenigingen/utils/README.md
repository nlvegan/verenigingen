# Verenigingen Utils Directory

This directory contains reusable utility functions and classes organized by functionality.

## Directory Structure

```
utils/
├── eboekhouden/               # eBoekhouden integration utilities
├── migration/                 # Migration-related utilities
├── debug/                     # Debug and diagnostic utilities
├── validation/                # Validation utilities and helpers
└── [core utilities]           # Core business logic utilities
```

## Core Utility Categories

### Business Logic Utilities:
- `application_helpers.py` - Membership application utilities
- `application_notifications.py` - Application notification system
- `application_payments.py` - Application payment processing
- `assignment_history_manager.py` - Team/chapter assignment tracking
- `chapter_membership_manager.py` - Chapter membership operations
- `donation_history_manager.py` - Donation tracking utilities
- `iban_history_manager.py` - IBAN change tracking
- `member_portal_utils.py` - Member portal functionality
- `subscription_processing.py` - Membership subscription utilities
- `termination_integration.py` - Member termination workflows
- `termination_utils.py` - Termination utility functions

### Financial/Payment Utilities:
- `payment_gateways.py` - Payment gateway integration
- `payment_notifications.py` - Payment-related notifications
- `payment_retry.py` - Failed payment retry logic
- `sepa_notifications.py` - SEPA mandate notifications
- `sepa_reconciliation.py` - SEPA payment reconciliation

### Data Management:
- `address_formatter.py` - Address formatting utilities
- `boolean_utils.py` - Boolean conversion utilities
- `config_manager.py` - Configuration management
- `database_query_analyzer.py` - Database query optimization
- `dutch_name_utils.py` - Dutch name processing
- `error_handling.py` - Error handling utilities
- `performance_utils.py` - Performance monitoring

### Portal/UI Utilities:
- `brand_css_generator.py` - Dynamic brand CSS generation
- `portal_customization.py` - Portal customization utilities
- `portal_menu_enhancer.py` - Portal menu management
- `jinja_methods.py` - Custom Jinja template methods

## Specialized Subdirectories

### `/eboekhouden/` - eBoekhouden Integration
Contains all utilities related to eBoekhouden accounting system integration:
- Account mapping and migration
- Payment processing and reconciliation
- API client implementations
- Migration and validation tools

### `/migration/` - Migration Utilities
Data migration and upgrade utilities:
- Migration audit trails
- Performance optimization for migrations
- Error recovery and validation
- Transaction safety utilities

### `/debug/` - Debug Utilities
Development and debugging tools:
- Account balance checks
- Import error analysis
- Memorial processing debugging
- Transaction verification tools

### `/validation/` - Validation Utilities
Data validation and integrity checking:
- API request validators
- Application validation logic
- Account group validation
- IBAN validation utilities

## Usage Examples

### Business Logic:
```python
from verenigingen.utils.member_portal_utils import get_member_dashboard_data
from verenigingen.utils.subscription_processing import process_membership_renewal
from verenigingen.utils.termination_utils import validate_termination_readiness
```

### Financial Operations:
```python
from verenigingen.utils.payment_retry import schedule_payment_retry
from verenigingen.utils.sepa_reconciliation import reconcile_sepa_payments
```

### Data Validation:
```python
from verenigingen.utils.validation.iban_validator import validate_iban
from verenigingen.utils.validation.api_validators import validate_member_data
```

### Portal/UI:
```python
from verenigingen.utils.brand_css_generator import generate_brand_css
from verenigingen.utils.portal_customization import customize_member_portal
```

## Organization Principles

1. **Core utilities** remain in the main utils directory
2. **Specialized utilities** are organized in subdirectories by domain
3. **One-off scripts** have been moved to the scripts directory
4. **Debug/development tools** are separated from production utilities

## Migration Notes

The following organizational changes were made:
- **eBoekhouden utilities** → `eboekhouden/` subdirectory
- **Migration tools** → `migration/` subdirectory
- **Debug scripts** → `debug/` subdirectory
- **Validation tools** → `validation/` subdirectory
- **One-off scripts** → moved to main `scripts/` directory

This organization improves maintainability and makes it easier to find relevant utilities for specific use cases.
