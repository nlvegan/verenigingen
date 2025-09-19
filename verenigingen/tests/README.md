# Verenigingen Test Suite

This document describes the reorganized test structure for the Verenigingen app. All tests have been consolidated into a single, well-organized directory structure.

## 📁 Directory Structure

```
verenigingen/tests/
├── frontend/                    # JavaScript/Frontend tests
│   ├── unit/                   # Frontend unit tests
│   ├── integration/            # Frontend integration tests
│   └── components/             # Component-specific tests
├── backend/                    # Python backend tests
│   ├── unit/                   # Backend unit tests
│   │   ├── api/               # API endpoint tests
│   │   └── controllers/       # Doctype controller tests
│   ├── integration/           # Backend integration tests
│   ├── workflows/             # Business workflow tests
│   ├── components/            # Component/feature tests
│   ├── business_logic/        # Core business logic tests
│   ├── validation/            # Data validation tests
│   ├── performance/           # Performance & optimization tests
│   ├── security/              # Security-related tests
│   ├── comprehensive/         # Comprehensive/edge case tests
│   ├── data_migration/        # Migration and patch tests
│   ├── optimization/          # API optimization tests
│   └── features/              # Feature-specific tests
├── fixtures/                   # Test data and personas
├── utils/                      # Test utilities and helpers
└── docs/                       # Test documentation
```

## 🚀 Running Tests

### Quick Start

```bash
# Run all tests
python verenigingen/tests/run_all_tests.py --all

# List available categories
python verenigingen/tests/run_all_tests.py --list

# Run specific category
python verenigingen/tests/run_all_tests.py --category backend

# Run specific subcategory
python verenigingen/tests/run_all_tests.py --category backend --subcategory unit
```

### Frappe Testing Commands

```bash
# Run via Frappe framework
cd /home/frappe/frappe-bench
bench --site dev.veganisme.net run-tests --app verenigingen --module verenigingen.tests.backend.unit

# Run specific test file
bench --site dev.veganisme.net run-tests --app verenigingen --module verenigingen.tests.backend.validation.test_iban_validator
```

## 📂 Test Categories

### Frontend Tests (`frontend/`)

- **Unit Tests**: Individual component/function testing
- **Integration Tests**: Cross-component integration
- **Components**: Specific UI component tests

**Technologies**: JavaScript, Jest, Node.js test runners

### Backend Tests (`backend/`)

#### Core Categories:

- **Unit Tests**: Individual function/method testing
- **Integration Tests**: Cross-system integration testing
- **Workflows**: Business process and workflow testing

#### Specialized Categories:

- **Components**: Feature-specific tests (members, payments, volunteers, etc.)
- **Business Logic**: Core business rule testing
- **Validation**: Data validation and constraint testing
- **Performance**: Performance benchmarking and optimization
- **Security**: Security and permission testing
- **Comprehensive**: Edge cases and comprehensive scenario testing
- **Data Migration**: Database migration and patch testing
- **Features**: Complete feature testing (applications, ANBI, etc.)

### Support Directories:

- **Fixtures**: Test data, personas, and mock objects
- **Utils**: Test utilities, base classes, and helpers
- **Docs**: Test documentation and summaries

## 🔧 Test Organization Principles

### File Naming Convention:

- Python tests: `test_*.py`
- JavaScript tests: `*.test.js` or `*.spec.js`
- Specific naming: `test_[component]_[feature].py`

### Import Structure:

```python
# Standard test imports
import unittest
import frappe
from verenigingen.tests.utils.base import BaseTestCase
from verenigingen.tests.fixtures.test_personas import TestDataFactory

# Component-specific imports
from verenigingen.tests.backend.components.test_member_lifecycle import MemberTestCase
```

### Test Dependencies:

- All test utilities are in `utils/`
- All test data is in `fixtures/`
- Base test classes extend from `utils/base.py`

## 📋 Migration Notes

### Changes Made:

1. **Consolidated Structure**: Merged `/tests` and `/verenigingen/tests` directories
2. **Logical Organization**: Grouped tests by functionality and type
3. **Improved Naming**: Renamed vague test files for clarity
4. **Updated Imports**: All import paths updated to new structure
5. **Comprehensive Runner**: New test runner supports all categories

### File Movements:

- App-level JavaScript tests → `frontend/`
- Python backend tests → `backend/[category]/`
- Test utilities → `utils/`
- Test data → `fixtures/`
- Documentation → `docs/`

### Removed Duplicates:

- Merged overlapping IBAN validation tests
- Consolidated JavaScript integration tests
- Removed redundant test fixtures

## 🛠️ Development Guidelines

### Adding New Tests:

1. Choose appropriate category in `backend/` or `frontend/`
2. Follow naming conventions
3. Use base classes from `utils/`
4. Add test data to `fixtures/` if needed

### Test Categories Decision Tree:

- **Frontend component?** → `frontend/`
- **API endpoint?** → `backend/unit/api/`
- **Business workflow?** → `backend/workflows/`
- **Data validation?** → `backend/validation/`
- **Performance test?** → `backend/performance/`
- **Security test?** → `backend/security/`
- **Full feature test?** → `backend/features/`

### Best Practices:

- Write clear test docstrings
- Use descriptive test method names
- Leverage existing test utilities
- Keep tests isolated and repeatable
- Document complex test scenarios

## 🔍 Legacy Compatibility

The reorganization maintains compatibility with existing Frappe test commands:

```bash
# These still work
bench --site dev.veganisme.net run-tests --app verenigingen
python verenigingen/tests/test_runner.py
```

However, some import paths in custom scripts may need updating to reflect the new structure.

## 📊 Test Statistics

**Total Test Files**: 100+ organized test files
**Coverage Areas**:

- Member management
- Payment processing
- Volunteer workflows
- SEPA integration
- Financial reporting
- Security validation
- Performance monitoring
- Data migration

**Test Types**:

- Unit Tests: 40+ files
- Integration Tests: 20+ files
- Workflow Tests: 15+ files
- Component Tests: 25+ files
- Validation Tests: 10+ files

## 🎯 Next Steps

1. **Update CI/CD**: Update continuous integration to use new test runner
2. **IDE Integration**: Configure IDE test runners for new structure
3. **Documentation**: Update developer docs with new test patterns
4. **Performance**: Monitor test execution times and optimize slow tests
5. **Coverage**: Add test coverage reporting for comprehensive analysis

---

For questions about the test structure or specific test categories, refer to the individual README files in each directory or consult the development team.
