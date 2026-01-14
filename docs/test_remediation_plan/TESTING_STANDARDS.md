# Testing Standards for Verenigingen

_Tiered Testing Strategy for Service-Oriented Architecture_

## **Executive Summary**

These standards establish a tiered testing approach that reflects our evolving architecture. As we've separated business logic into dedicated service classes, we can now effectively use unit tests with mocks for isolated service logic while maintaining integration tests for orchestration layers.

**Key Change**: The blanket prohibition on mocking database operations has been replaced with context-specific guidance. The goal remains the same—tests that catch real bugs—but the approach is now nuanced based on what's being tested.

---

## **Why We Updated These Standards**

### The Original Problem

Our previous standards prohibited all mocking of database operations. This was a reasonable overcorrection to "testing theater"—tests that mocked so much they validated nothing.

The root cause was **architectural**: business logic was entangled inside DocType controllers. Mocking `frappe.get_doc` in that context meant mocking the thing you were trying to test.

### What Changed

We've separated concerns:
- `TransactionService` - payment entry business logic
- `MandateService` - mandate lifecycle management
- `PaymentAlertService` - alerting logic
- `SecureCertManager` - certificate handling
- Dedicated service layers for Mollie, Ponto, ING Checkout

These services have **clear interfaces**: they take inputs, apply business logic, and produce outputs. The business logic is now testable in isolation.

### The New Approach

| Layer | Unit Tests + Mocks | Integration Tests |
|-------|-------------------|-------------------|
| Pure functions | Yes | Optional |
| Service classes | Yes | Recommended |
| DocType controllers | No | Required |
| API endpoints | No | Required |
| Permission checks | No | Required |

---

## **Tiered Testing Strategy**

### **Tier 1: Unit Tests (Service Layer)**

**When to use**: Testing isolated business logic in service classes.

**Mocking allowed**: Database operations (`frappe.get_doc`, `frappe.get_all`, etc.) when testing service logic.

**Rationale**: Service classes have clear boundaries. Mocking the data layer lets you test business logic without database setup overhead.

```python
from unittest.mock import patch, MagicMock

class TestMandateService(unittest.TestCase):
    """Unit tests for MandateService business logic."""

    def test_create_mandate_validates_member_has_iban(self):
        """Test that mandate creation requires IBAN."""
        service = MandateService()

        # Mock: We're testing the service logic, not database retrieval
        mock_member = MagicMock()
        mock_member.iban = None  # No IBAN

        with patch("frappe.get_doc", return_value=mock_member):
            result = service.create_mandate_for_member("MEM-001")

        # Assert: Service correctly rejects member without IBAN
        self.assertFalse(result["success"])
        self.assertIn("IBAN", result["error"])

    def test_overpayment_calculation(self):
        """Test overpayment amount calculation - pure logic."""
        service = TransactionService()

        # No mocking needed - testing pure calculation
        # (assuming we extract this to a testable method)
        overpayment = service._calculate_overpayment(
            paid=150.00,
            outstanding=100.00
        )

        self.assertEqual(overpayment, 50.00)
```

**Requirements**:
- Document what you're testing and why mocking is appropriate
- Keep mocks focused on data access, not business logic
- Pair with integration tests for critical paths

### **Tier 2: Integration Tests (Orchestration Layer)**

**When to use**: Testing DocType controllers, API endpoints, workflows, permissions.

**Mocking allowed**: Only external services (email, SMS, external APIs like Mollie/Pay.nl).

**Rationale**: These layers orchestrate multiple components. You need to verify they work together correctly with real database state.

```python
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from unittest.mock import patch

class TestMembershipApprovalIntegration(EnhancedTestCase):
    """Integration tests for membership approval workflow."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(status="Pending")
        self.admin = self.create_test_user(
            "admin@test.com",
            roles=["System Manager"]
        )

    def test_approval_creates_customer_and_sends_email(self):
        """Test complete approval workflow with real database operations."""

        # Mock only external service
        with patch("frappe.sendmail") as mock_email:
            with self.as_user(self.admin.email):
                approve_membership(self.member.name)

        # Verify real database changes
        self.member.reload()
        self.assertEqual(self.member.status, "Active")
        self.assertIsNotNone(self.member.customer)

        # Verify external service was called
        mock_email.assert_called_once()
```

### **Tier 3: Security/Permission Tests**

**When to use**: Testing authorization boundaries.

**Mocking allowed**: Never for permission checks. External services only.

**Rationale**: Permission bugs are critical. Must test real permission system.

```python
class TestAPISecurityIntegration(EnhancedTestCase):
    """Security tests - NO mocking of permissions."""

    def test_non_admin_cannot_approve_membership(self):
        """Verify permission boundaries are enforced."""
        member = self.create_test_member(status="Pending")
        regular_user = self.create_test_user(
            "member@test.com",
            roles=["Verenigingen Member"]  # No admin role
        )

        with self.as_user(regular_user.email):
            with self.assertRaises(frappe.PermissionError):
                approve_membership(member.name)
```

---

## **Decision Guide: When to Mock**

### **Mock When:**

1. **Testing service class logic in isolation**
   - You want fast, focused tests
   - The database interactions are incidental to what you're testing
   - You'll also have integration tests for the full flow

2. **External APIs that cost money or have side effects**
   - Mollie payments, Pay.nl transactions
   - Email/SMS sending
   - Third-party webhooks

3. **Simulating error conditions**
   - Network failures, API errors
   - Edge cases hard to reproduce with real data

### **Don't Mock When:**

1. **Testing DocType controller methods**
   - `validate()`, `before_save()`, `on_submit()`
   - These ARE the orchestration—test them integrated

2. **Testing permission boundaries**
   - Always use real user contexts
   - Never `ignore_permissions=True` in test assertions

3. **Testing data integrity rules**
   - Unique constraints, foreign keys
   - Field validation, required fields

4. **The mock would hide the bug you're trying to catch**
   - If you're unsure, write the integration test

---

## **Patterns by Component Type**

### **Service Classes** (e.g., `MandateService`, `TransactionService`)

```python
# Unit test - mock data layer
class TestMandateServiceUnit(unittest.TestCase):
    @patch("frappe.get_doc")
    def test_validates_mandate_status(self, mock_get_doc):
        mock_mandate = MagicMock(status="Cancelled")
        mock_get_doc.return_value = mock_mandate

        service = MandateService()
        result = service.execute_debit("MANDATE-001", 100.00)

        self.assertFalse(result["success"])
        self.assertIn("not active", result["error"])

# Integration test - verify full flow
class TestMandateServiceIntegration(EnhancedTestCase):
    def test_execute_debit_creates_transaction(self):
        mandate = self.create_test_mandate(status="Active")

        with patch("vereiningen.ponto.api.create_payment"):
            service = MandateService()
            result = service.execute_debit(mandate.name, 100.00)

        # Verify real database state
        self.assertTrue(result["success"])
        self.assertTrue(frappe.db.exists("Payment Transaction", result["transaction"]))
```

### **DocType Controllers** (e.g., `ing_checkout_transaction.py`)

```python
# Integration test only - no mocking database operations
class TestINGCheckoutTransaction(EnhancedTestCase):
    def test_webhook_updates_status_and_creates_payment_entry(self):
        transaction = self.create_test_transaction(status="Pending")
        invoice = self.create_test_invoice(amount=100.00)

        webhook_data = {"object": {"status": {"code": 100}}}  # Paid

        # Mock only external callback, not database
        transaction.update_from_webhook(webhook_data)

        transaction.reload()
        self.assertEqual(transaction.status, "Paid")
        self.assertIsNotNone(transaction.payment_entry)
```

### **API Endpoints**

```python
# Integration test - test real request/response cycle
class TestPaymentAPI(EnhancedTestCase):
    def test_initiate_payment_returns_redirect_url(self):
        invoice = self.create_test_invoice()

        with patch("mollie.api.create_payment") as mock_mollie:
            mock_mollie.return_value = {"checkout_url": "https://..."}

            response = self.post_api(
                "verenigingen.api.payments.initiate",
                {"invoice": invoice.name}
            )

        self.assertEqual(response["status"], "success")
        self.assertIn("redirect_url", response)
```

---

## **Migration from Old Standards**

### **Existing Tests**

Tests written under the old "no mocking" standard remain valid. They provide strong integration coverage.

### **New Tests**

Choose the appropriate tier:
1. **Service logic** → Unit tests with mocks OK
2. **Workflows/APIs** → Integration tests required
3. **Permissions** → Integration tests, no permission bypasses

### **Updating Pre-Commit Hooks**

The `test-quality-enforcer` hook should be updated to:
- Allow `frappe.get_doc` mocks in files under `tests/unit/`
- Continue blocking them in `tests/integration/`
- Always block `ignore_permissions=True` outside of setUp/tearDown

---

## **Test Organization**

```
tests/
├── unit/                    # Tier 1: Unit tests, mocking allowed
│   ├── services/
│   │   ├── test_mandate_service.py
│   │   ├── test_transaction_service.py
│   │   └── test_payment_alert_service.py
│   └── utils/
│       └── test_iban_validator.py
├── integration/             # Tier 2: Integration tests, external mocks only
│   ├── test_membership_workflow.py
│   ├── test_payment_processing.py
│   └── test_mandate_lifecycle.py
└── security/                # Tier 3: Permission tests, no mocking
    ├── test_api_authorization.py
    └── test_role_boundaries.py
```

---

## **Summary**

| Aspect | Old Standard | New Standard |
|--------|--------------|--------------|
| Database mocks | Never allowed | Allowed in unit tests for services |
| Integration tests | Required for everything | Required for orchestration layers |
| Service class testing | Integration only | Unit + Integration |
| Permission testing | No mocking | No mocking (unchanged) |
| External API mocks | Allowed | Allowed (unchanged) |

The goal remains unchanged: **tests that catch real bugs**. The approach is now matched to our improved architecture.
