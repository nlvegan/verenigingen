# Controller Growth Prevention Policy

**Effective Date**: 2025-11-25
**Status**: Active
**Owner**: Technical Leadership

---

## Executive Summary

This policy establishes strict guidelines to prevent controller files from growing beyond manageable sizes by enforcing service-oriented architecture principles. All new business logic must be implemented in the service layer.

**Policy Statement**: ALL new business logic MUST be implemented in service layer classes, not in DocType controllers.

---

## Background and Rationale

### Problem Statement

Historically, the Verenigingen codebase suffered from "controller bloat" - business logic accumulating in DocType controller files, leading to:

- **Massive file sizes**: member.py reached 4,989 lines
- **Poor maintainability**: Logic scattered across large files
- **Testing difficulties**: Tight coupling to Frappe framework
- **Code duplication**: Similar patterns repeated across controllers
- **Onboarding friction**: New developers overwhelmed by complexity

### Solution Implemented

**Phase 2D/2E Service Extraction** (2024-2025):
- Extracted business logic into focused service classes
- Reduced member.py from 4,989 → 1,747 lines (65% reduction)
- Reduced volunteer.py from 1,100 → 858 lines (22% reduction)
- Created 40+ service classes with clear responsibilities

### Why This Policy Matters

Without prevention mechanisms, we risk:
1. **Regression**: New features added to controllers, undoing extraction work
2. **Pattern confusion**: Developers uncertain which pattern to follow
3. **Wasted effort**: Service extraction effort becomes meaningless
4. **Technical debt**: Controllers continue growing indefinitely

---

## Policy Details

### Scope

This policy applies to:

- **Member controller** (`medlem.py`) - Current: 1,747 lines, Target: 800 lines
- **Volunteer controller** (`volunteer.py`) - Current: 858 lines, Target: 500 lines
- **Membership Dues Schedule** (`membership_dues_schedule.py`) - Current: 2,371 lines, Target: 800 lines
- **All controllers >500 lines** - Future enforcement

### What Controllers MAY Contain

Controllers are permitted to contain ONLY:

1. **Frappe lifecycle hooks**
   - `validate()`, `before_save()`, `after_insert()`, `on_update()`, `on_submit()`, `on_cancel()`, etc.

2. **Permission checks**
   - `has_permission()`, `has_website_permission()`
   - Basic permission validation

3. **Service orchestration**
   - Calling services and coordinating responses
   - Handling service results
   - Managing transactions

4. **Minimal validation**
   - Simple field-level validation that MUST occur in controller
   - Framework-specific validation (e.g., link field validation)

### What Controllers MUST NOT Contain

Controllers are PROHIBITED from containing:

- ❌ Complex business logic (>10 lines)
- ❌ Data transformation logic
- ❌ External API calls
- ❌ Complex calculations
- ❌ Workflow management
- ❌ State machine logic
- ❌ Query building (beyond simple reads)
- ❌ Report generation
- ❌ Email composition
- ❌ PDF generation
- ❌ File processing

---

## Implementation Guidelines

### How to Add New Features

**❌ WRONG: Adding logic to controller**

```python
class Member(Document):
    def calculate_membership_discount(self):
        """Calculate discount based on member status and history."""
        # 50 lines of complex business logic
        if self.member_type == "Student":
            base_fee = self.get_base_fee()
            years_active = self.get_years_active()
            discount_pct = min(years_active * 5, 25)
            # More complex logic...
            return base_fee * (1 - discount_pct / 100)
        # More conditions...
```

**✅ CORRECT: Using service**

```python
class Member(Document):
    def calculate_membership_discount(self):
        """Calculate discount based on member status and history."""
        from verenigingen.services.member.financial.member_discount_service import (
            MemberDiscountService
        )

        service = MemberDiscountService()
        result = service.calculate_discount(
            member_name=self.name,
            member_type=self.member_type
        )

        if not result.success:
            frappe.throw(result.message)

        return result.data["discount_amount"]
```

### Service Creation Pattern

When implementing new features:

**Step 1: Create Service Class**

```python
# verenigingen/services/member/financial/member_discount_service.py

from typing import Dict
from verenigingen.services.base_service import DataService
from verenigingen.utils.operation_result import OperationResult

class MemberDiscountService(DataService):
    """Calculate member discounts based on business rules."""

    def calculate_discount(
        self,
        member_name: str,
        member_type: str
    ) -> OperationResult:
        """
        Calculate membership discount.

        Args:
            member_name: Member identifier
            member_type: Type of membership

        Returns:
            OperationResult with discount_amount and discount_pct
        """
        try:
            # Business logic here
            member = self._get_member(member_name)

            if member_type == "Student":
                discount = self._calculate_student_discount(member)
            elif member_type == "Senior":
                discount = self._calculate_senior_discount(member)
            else:
                discount = 0

            return OperationResult.success(
                data={
                    "discount_amount": discount,
                    "discount_pct": (discount / member.base_fee) * 100
                },
                message=f"Calculated discount: {discount}"
            )

        except Exception as e:
            return OperationResult.failure(
                message=f"Failed to calculate discount: {str(e)}"
            )

    def _calculate_student_discount(self, member) -> float:
        """Student-specific discount logic."""
        # Complex business logic
        pass

    def _calculate_senior_discount(self, member) -> float:
        """Senior-specific discount logic."""
        # Complex business logic
        pass
```

**Step 2: Add Tests**

```python
# verenigingen/tests/services/test_member_discount_service.py

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.services.member.financial.member_discount_service import (
    MemberDiscountService
)

class TestMemberDiscountService(EnhancedTestCase):
    def test_student_discount_calculation(self):
        """Test student discount calculation."""
        member = self.create_test_member(
            member_type="Student",
            birth_date="2000-01-01"
        )

        service = MemberDiscountService()
        result = service.calculate_discount(
            member_name=member.name,
            member_type="Student"
        )

        self.assertTrue(result.success)
        self.assertGreater(result.data["discount_amount"], 0)
```

**Step 3: Call from Controller**

```python
# verenigingen/verenigingen/doctype/member/member.py

class Member(Document):
    def validate(self):
        """Validate member data."""
        if self.membership_type == "Student":
            self._apply_student_discount()

    def _apply_student_discount(self):
        """Apply student discount using service."""
        from verenigingen.services.member.financial.member_discount_service import (
            MemberDiscountService
        )

        service = MemberDiscountService()
        result = service.calculate_discount(
            member_name=self.name,
            member_type=self.member_type
        )

        if result.success:
            self.discount_amount = result.data["discount_amount"]
        else:
            frappe.throw(result.message)
```

---

## Enforcement Mechanisms

### 1. Automated CI/CD Checks

**GitHub Actions Workflow**: `.github/workflows/controller-size-check.yml`

- Runs on every pull request
- Checks controller line counts
- Fails PR if limits exceeded
- Posts comment with remediation guidance

**Run locally**:
```bash
python scripts/check_controller_size.py
```

### 2. Code Review Requirements

All PRs must pass code review checklist:

- [ ] No new business logic added to controllers
- [ ] New logic added to service classes
- [ ] Services have unit tests
- [ ] Controller line counts not increased
- [ ] Documentation updated

### 3. Pre-commit Hooks

**Recommended**: Add to `.pre-commit-config.yaml`:

```yaml
  - repo: local
    hooks:
      - id: controller-size-check
        name: Controller Size Check
        entry: python scripts/check_controller_size.py
        language: system
        pass_filenames: false
        always_run: true
```

### 4. Documentation Requirements

New features MUST document:
- Which service implements the logic
- How to test the service
- Integration points with controllers

---

## Metrics and Monitoring

### Current Baseline (2025-11-25)

| Controller | Current | Max | Target | Progress |
|------------|---------|-----|--------|----------|
| member.py | 1,747 | 2,160 | 800 | 30% |
| volunteer.py | 858 | 1,020 | 500 | 31% |
| membership_dues_schedule.py | 2,371 | 2,837 | 800 | 22% |

### Monthly Tracking

Track and report monthly:
- Controller line counts (trend analysis)
- Service adoption rate (% of logic in services)
- Policy violations (count and severity)
- Service layer test coverage

### Success Criteria

**6-Month Goals**:
- Zero controller size limit violations
- >90% service adoption for new features
- member.py reduced to <1,500 lines
- volunteer.py reduced to <700 lines

**12-Month Goals**:
- member.py reduced to <1,000 lines
- volunteer.py reduced to <600 lines
- All controllers >500 lines in monitoring

---

## Exceptions and Waivers

### Exception Request Process

1. **Document justification**: Why must logic be in controller?
2. **Present alternatives**: What service approaches were considered?
3. **Get approval**: Technical leadership must approve
4. **Document decision**: Create Architecture Decision Record (ADR)
5. **Add TODO**: Plan for future extraction

### Valid Exception Scenarios

Rare cases where controller logic may be necessary:

- **Frappe framework limitations**: Logic that MUST run in specific lifecycle hook
- **Performance critical paths**: Proven performance need (with benchmarks)
- **Transaction management**: Complex transaction boundaries
- **Legacy compatibility**: Temporary during migration (with expiration date)

### Exception Template

```python
# CONTROLLER EXCEPTION: [Ticket/ADR Reference]
# Approved by: [Name] on [Date]
# Justification: [Reason]
# Expiration: [Date when this must be refactored]
# TODO: Extract to service by [Date]

def exceptional_controller_logic(self):
    """Logic that temporarily lives in controller."""
    # Exceptional logic here
    pass
```

---

## FAQ

### Q: What if I'm fixing a bug in existing controller code?

**A**: Bug fixes to existing code are allowed. However, consider:
1. Can the fix be made while also extracting to a service?
2. If the bug area is large, should we extract while fixing?
3. Add TODO comment for future extraction if not doing it now

### Q: What about small utility functions (<10 lines)?

**A**: Small, truly generic utilities can stay in controllers IF:
- They're reusable across multiple methods
- They don't contain business logic
- They're simple transformations or helpers

Prefer extracting to a utility module if used across controllers.

### Q: How do I know if something is "business logic"?

**A**: Ask these questions:
1. Would QA/product team care if this changed? → Business logic
2. Could this be reused outside this controller? → Extract to service
3. Would this benefit from isolated testing? → Extract to service
4. Is this >10 lines of logic? → Extract to service

### Q: What if the service layer is too slow?

**A**:
1. Measure first (don't optimize prematurely)
2. Profile to find actual bottleneck
3. Optimize the service, not by moving logic to controller
4. Consider caching, query optimization, or async processing

### Q: Can I call services from JavaScript/client-side?

**A**: Yes! Services can be exposed via whitelisted API methods:

```python
@frappe.whitelist()
def calculate_member_discount(member_name, member_type):
    """API endpoint for discount calculation."""
    service = MemberDiscountService()
    result = service.calculate_discount(member_name, member_type)
    return result.to_dict()
```

---

## Related Documentation

- [Service Infrastructure Architecture](../architecture/SERVICE_INFRASTRUCTURE_ARCHITECTURE.md)
- [Enhanced Test Factory Guide](../testing/ENHANCED_TEST_FACTORY.md)
- [Operation Result Pattern](../patterns/OPERATION_RESULT_PATTERN.md)
- [Phase 2D/2E Extraction Summary](../refactoring/PHASE_2D_2E_SUMMARY.md)

---

## Review and Updates

**Policy Review**: Quarterly
**Next Review**: 2026-02-25
**Version**: 1.0
**Last Updated**: 2025-11-25

**Change Log**:
- 2025-11-25: Initial policy creation
