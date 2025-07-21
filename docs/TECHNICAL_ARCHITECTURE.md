# Technical Architecture Guide

## Overview

Verenigingen is a comprehensive association management system built on the Frappe Framework with advanced testing infrastructure, extensive integration capabilities, and modern development practices.

## System Architecture

### Core Framework
- **Frappe Framework v15+**: Modern Python-based web framework
- **ERPNext Integration**: Financial modules, customer management, and invoicing
- **MariaDB/MySQL**: Primary database with optimized queries and indexing
- **Redis**: Background job processing and caching
- **Python 3.10+**: Modern Python features and type hints

### Application Structure

```
verenigingen/
├── api/                          # RESTful API endpoints
├── patches.txt                   # Database migration scripts
├── public/                       # Static assets (CSS, JS, images)
├── templates/                    # Jinja2 templates and pages
├── tests/                        # Comprehensive test suite (186+ files)
├── utils/                        # Shared business logic utilities
└── verenigingen/                 # Core application modules
    ├── doctype/                  # Document type definitions
    ├── report/                   # Custom reports and analytics
    └── workspace/                # Frappe workspaces
```

## Enhanced Testing Framework

### VereningingenTestCase (New Standard)
All tests should inherit from `VereningingenTestCase` which provides:

```python
from verenigingen.tests.utils.base import VereningingenTestCase

class TestMyFeature(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        # Automatic cleanup and factory methods available

    def test_something(self):
        # Use factory methods
        member = self.create_test_member(
            first_name="Test",
            last_name="User",
            email="test@example.com"
        )
        # Automatic cleanup handled by base class
```

#### Key Features:
- **Automatic Document Cleanup**: All created documents tracked and cleaned up automatically
- **Customer Cleanup**: Automatic customer record cleanup for member-related tests
- **Factory Methods**: Consistent test data generation with proper relationships
- **Permission Compliance**: No `ignore_permissions=True` violations
- **Performance Tracking**: Built-in query count and execution time monitoring
- **Enhanced Assertions**: Domain-specific assertions for common test patterns

#### Factory Methods Available:
```python
# Core entities
member = self.create_test_member(first_name="John", email="john@example.com")
volunteer = self.create_test_volunteer(member=member.name)
chapter = self.create_test_chapter(chapter_name="Test Chapter")
membership = self.create_test_membership(member=member.name)

# Banking and payments
mandate = self.create_sepa_mandate(member=member.name, bank_code="TEST")
iban = self.factory.generate_test_iban("TEST")  # Valid test IBAN with checksum
```

### Test Organization (2025 Reorganization)

#### Test Categories:
- **`backend/business_logic/`**: Core business logic and critical functionality
- **`backend/components/`**: Individual component and feature tests
- **`backend/integration/`**: Cross-system integration tests
- **`backend/workflows/`**: Complex multi-step process tests
- **`backend/validation/`**: Data validation and schema tests
- **`frontend/`**: JavaScript and UI component tests

#### Migration Status:
- ✅ **Phase 1 Complete**: Critical business logic tests migrated to VereningingenTestCase
- ✅ **Phase 2 Complete**: Core component tests migrated with factory methods
- ✅ **Phase 3 Complete**: Workflow and integration tests migrated
- 🚧 **Ongoing**: Permission violation cleanup across remaining test files

### Mock Bank Testing Support
Enhanced testing with realistic but clearly marked test data:

```python
# Generate valid test IBANs with proper MOD-97 checksums
test_iban = generate_test_iban("TEST")  # NL13TEST0123456789
mock_iban = generate_test_iban("MOCK")  # NL82MOCK0123456789
demo_iban = generate_test_iban("DEMO")  # NL93DEMO0123456789

# All pass full IBAN validation and work with SEPA mandate creation
```

## DocType Architecture

### Key Document Types

#### Member Management:
- **Member**: Core member records with mixin pattern for specialized functionality
- **Membership**: Lifecycle management with custom subscription overrides
- **Membership Application**: Review workflow with geographic assignment

#### Financial Integration:
- **SEPA Mandate**: Direct debit authorization with enhanced validation
- **Direct Debit Batch**: SEPA file generation and processing
- **Payment Entry**: ERPNext integration for payment tracking

#### Organizational Structure:
- **Chapter**: Geographic organization with postal code validation
- **Team**: Project-based volunteer organization
- **Volunteer**: Assignment tracking and expense management

### Mixin Pattern Implementation
Key doctypes use specialized mixins for enhanced functionality:

```python
# Member uses multiple mixins for specialized operations
class Member:
    # PaymentMixin: SEPA mandate and payment processing
    # SEPAMandateMixin: Direct debit management
    # ChapterMixin: Geographic chapter assignment
    # TerminationMixin: Governance-compliant termination workflows
```

## Integration Architecture

### eBoekhouden Integration (Production Ready)
Comprehensive accounting system integration with dual API support:

#### REST API (Primary - Recommended):
- **Unlimited History**: Complete transaction and master data access
- **Enhanced Performance**: Modern JSON-based communication
- **Better Error Handling**: Detailed error responses and retry mechanisms
- **Future-Proof**: Actively maintained and enhanced

#### Features:
- **Complete Chart of Accounts**: Intelligent mapping with Dutch accounting standards
- **Opening Balance Import**: €324K+ successfully imported in production
- **Multi-Account Support**: Receivable, Payable, Stock, and Cash accounts
- **Zero Amount Handling**: Imports ALL transactions including zero-amount invoices
- **Party Management**: Automatic customer/supplier creation with proper relationships
- **Smart Document Naming**: Meaningful names like `EBH-Payment-1234`, `EBH-Memoriaal-5678`

#### SOAP API (Legacy):
- **Limited History**: 500 most recent transactions only
- **Backward Compatibility**: Maintained for legacy feature support

### ERPNext Integration
Deep integration with ERPNext modules:

#### Financial Modules:
- **Accounts**: Customer/supplier management and invoice processing
- **Payments**: Payment entry creation and bank reconciliation
- **Subscriptions**: Automated recurring billing with custom overrides

#### CRM Integration:
- **Customer Records**: Automatic creation from membership applications
- **Sales Invoices**: Membership fee and donation invoicing
- **Payment Tracking**: Complete payment history and reconciliation

### SEPA Direct Debit Processing
EU-compliant payment processing:

#### Features:
- **Mandate Management**: Electronic mandate creation and validation
- **Batch Processing**: Automated SEPA file generation
- **Bank Integration**: MT940 import and reconciliation
- **Error Handling**: Failed payment processing and retry mechanisms

## API Architecture

### RESTful APIs
Comprehensive API layer with `@frappe.whitelist()` decorators:

```python
@frappe.whitelist()
def get_member_details(member_id):
    """Get comprehensive member information"""
    # Proper permission checking
    # Structured response format
    # Error handling
```

#### API Categories:
- **Member Management**: CRUD operations and lifecycle management
- **Financial Operations**: Payment processing and invoice generation
- **Volunteer Coordination**: Assignment management and expense processing
- **Analytics**: Real-time KPI and reporting APIs

### JavaScript Integration
Modern JavaScript with ES6+ features:

#### Key Libraries:
- **IBAN Validation**: Client-side validation with MOD-97 checksum
- **SEPA Utilities**: Mandate creation and BIC derivation
- **Form Enhancements**: Dynamic field validation and UI improvements

## Development Best Practices

### Code Quality Standards

#### Frappe ORM Compliance:
```python
# ✅ Correct: Use Frappe ORM
doc = frappe.new_doc("DocType")
doc.field1 = "value"
doc.save()  # Let Frappe validate

# ❌ Never: Direct SQL manipulation
frappe.db.sql("INSERT INTO ...")  # Bypasses validation
```

#### Permission Compliance:
```python
# ✅ Correct: Use proper permissions
doc.insert()  # Respects role permissions

# ❌ Never: Bypass permissions in production code
doc.insert(ignore_permissions=True)  # Only for test setup
```

#### Field Reference Validation:
```python
# ✅ Always read DocType JSON first
# Check required fields: "reqd": 1
# Use exact field names from JSON
# Never guess field names
```

### Testing Requirements

#### Mandatory Test Patterns:
1. **Use VereningingenTestCase**: All new tests must inherit from enhanced base class
2. **Factory Methods**: Use provided factory methods for consistent test data
3. **Document Tracking**: Use `self.track_doc()` for automatic cleanup
4. **No Permission Bypassing**: Remove all `ignore_permissions=True` violations
5. **DocType Validation**: Read JSON files before writing tests that create documents

#### Test Execution:
```bash
# Use Frappe test runner
bench --site dev.veganisme.net run-tests --app verenigingen --module test_module

# Never use direct Python execution (will fail with import errors)
python test_file.py  # ❌ Fails with "ModuleNotFoundError: No module named 'frappe'"
```

## Performance Optimizations

### Database Optimization:
- **Query Optimization**: Efficient database queries with proper indexing
- **Bulk Operations**: Batch processing for large data operations
- **Caching**: Redis-based caching for frequently accessed data

### API Performance:
- **Response Caching**: 1-hour CSS caching for brand management
- **Query Count Monitoring**: Built-in test framework monitoring
- **Background Jobs**: Async processing for heavy operations

## Security Features

### Access Control:
- **Role-Based Permissions**: Fine-grained access control
- **Document-Level Security**: Permission queries for data isolation
- **Field-Level Permissions**: Permlevel system for sensitive fields

### Data Protection:
- **GDPR Compliance**: Built-in privacy features
- **Audit Trails**: Complete change tracking
- **Secure Storage**: Encrypted sensitive data

## Deployment Architecture

### Requirements:
- **Python 3.10+**: Modern Python features
- **Frappe v15+**: Latest framework features
- **MariaDB/MySQL**: Optimized database configuration
- **Redis**: Background job processing
- **Required Apps**: ERPNext, Payments, HRMS, CRM

### Environment Configuration:
- **Development**: Full debug logging and test data
- **Production**: Optimized performance and monitoring
- **Cloud Deployment**: Scalable infrastructure support

## Monitoring and Maintenance

### Health Monitoring:
- **System Health Dashboard**: Real-time system status
- **Performance Metrics**: Query count and execution time tracking
- **Error Tracking**: Comprehensive error logging and alerting

### Maintenance Tasks:
- **Database Cleanup**: Automated cleanup of test and temporary data
- **Log Rotation**: Managed log file rotation and archival
- **Backup Management**: Automated backup and recovery procedures

## Future Enhancements

### Planned Features:
- **Enhanced Analytics**: Advanced business intelligence and predictive analytics
- **Mobile Apps**: Native mobile applications for members and volunteers
- **API Extensions**: Extended API capabilities for third-party integrations
- **Multi-Language Support**: Internationalization for non-Dutch organizations

### Technical Roadmap:
- **Microservices Architecture**: Gradual migration to microservices
- **Real-Time Features**: WebSocket integration for live updates
- **Advanced Security**: Enhanced security features and compliance tools
- **Performance Scaling**: Horizontal scaling capabilities

---

This technical architecture provides a solid foundation for developing, testing, and maintaining the Verenigingen application with modern best practices and comprehensive testing infrastructure.
