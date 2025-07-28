# Phase 4.1 Specific Test Restoration Actions

## Immediate Restoration Requirements

### 1. Critical Test Files to Restore

#### Expense Workflow Tests (CRITICAL)
```bash
# Restore from archived_removal/
git checkout HEAD -- archived_removal/test_expense_workflow_complete.py
git checkout HEAD -- archived_removal/test_expense_events.py
git checkout HEAD -- archived_removal/test_expense_handlers.py

# Move to proper location
mv archived_removal/test_expense_workflow_complete.py verenigingen/tests/backend/workflows/
mv archived_removal/test_expense_events.py verenigingen/tests/backend/workflows/
mv archived_removal/test_expense_handlers.py verenigingen/tests/backend/workflows/
```

#### Edge Case Tests (HIGH PRIORITY)
```bash
# Restore edge case testing
git checkout HEAD -- verenigingen/tests/test_edge_case_testing_demo.py

# Move to edge cases directory
mkdir -p verenigingen/tests/edge_cases/
mv verenigingen/tests/test_edge_case_testing_demo.py verenigingen/tests/edge_cases/test_edge_case_scenarios.py
```

#### Financial Validation Tests (HIGH PRIORITY)
```bash
# Restore financial tests
git checkout HEAD -- archived_removal/test_dues_validation.py
git checkout HEAD -- verenigingen/tests/test_sepa_invoice_validation_fix.py

# Move to proper location
mv archived_removal/test_dues_validation.py verenigingen/tests/backend/financial/
mv verenigingen/tests/test_sepa_invoice_validation_fix.py verenigingen/tests/backend/financial/
```

### 2. Factory Method Restoration

Create new file: `verenigingen/tests/fixtures/enhanced_test_factory.py`

```python
from .test_data_factory import TestDataFactory
import random
from datetime import datetime, timedelta

class EnhancedTestDataFactory(TestDataFactory):
    """Enhanced factory with bulk generation and scenario building"""

    def create_test_members_bulk(self, count=10, chapters=None, status_distribution=None):
        """Create multiple members with controlled distribution"""
        if status_distribution is None:
            status_distribution = {
                "Active": 0.8,
                "Suspended": 0.1,
                "Terminated": 0.1
            }

        if not chapters:
            chapters = self.create_test_chapters(5)

        members = []
        statuses = []

        # Build status list based on distribution
        for status, ratio in status_distribution.items():
            statuses.extend([status] * int(count * ratio))

        # Fill remaining with Active
        while len(statuses) < count:
            statuses.append("Active")

        random.shuffle(statuses)

        for i in range(count):
            chapter = random.choice(chapters)
            status = statuses[i]

            member = self.create_test_member(
                chapter=chapter.name,
                status=status,
                email=f"bulktest{i}_{self.test_run_id}@example.com"
            )
            members.append(member)

        return members

    def create_test_memberships_bulk(self, members, membership_types=None, coverage_ratio=0.9):
        """Create memberships for a percentage of members"""
        if not membership_types:
            membership_types = [
                self.create_test_membership_type(
                    membership_type_name=f"Type{i}_{self.test_run_id}",
                    dues_rate=rate
                ) for i, rate in enumerate([100, 50, 25])
            ]

        memberships = []
        member_sample = random.sample(members, int(len(members) * coverage_ratio))

        for member in member_sample:
            membership_type = random.choice(membership_types)
            membership = self.create_test_membership(
                member=member.name,
                membership_type=membership_type.name
            )
            memberships.append(membership)

        return memberships

    def create_edge_case_scenarios(self):
        """Generate standard edge case test scenarios"""
        scenarios = {}

        # Scenario 1: Billing frequency conflict
        conflict_member = self.create_test_member()
        conflict_membership = self.create_test_membership(member=conflict_member.name)

        # Clear auto-schedules for controlled testing
        from vereiningen.tests.utils.base import VereningingenTestCase
        test_case = VereningingenTestCase()
        test_case.clear_member_auto_schedules(conflict_member.name)

        # Create conflicting schedules
        monthly = test_case.create_controlled_dues_schedule(
            conflict_member.name, "Monthly", 25.0
        )
        annual = test_case.create_controlled_dues_schedule(
            conflict_member.name, "Annual", 250.0
        )

        scenarios['billing_conflict'] = {
            'member': conflict_member,
            'membership': conflict_membership,
            'schedules': [monthly, annual]
        }

        # Scenario 2: Zero-rate schedules
        zero_member = self.create_test_member()
        zero_membership = self.create_test_membership(member=zero_member.name)
        test_case.clear_member_auto_schedules(zero_member.name)

        zero_schedule = test_case.create_controlled_dues_schedule(
            zero_member.name, "Monthly", 0.0
        )

        scenarios['zero_rate'] = {
            'member': zero_member,
            'membership': zero_membership,
            'schedule': zero_schedule
        }

        # Scenario 3: Multiple active memberships
        multi_member = self.create_test_member()
        memberships = []
        for i in range(3):
            membership_type = self.create_test_membership_type(
                membership_type_name=f"MultiType{i}_{self.test_run_id}"
            )
            membership = self.create_test_membership(
                member=multi_member.name,
                membership_type=membership_type.name
            )
            memberships.append(membership)

        scenarios['multiple_active'] = {
            'member': multi_member,
            'memberships': memberships
        }

        return scenarios

    def create_performance_test_data(self, member_count=1000):
        """Generate large dataset for performance testing"""
        print(f"Creating performance test data with {member_count} members...")

        # Create chapters
        chapters = self.create_test_chapters(10)

        # Create membership types
        membership_types = []
        for period in ["Annual", "Monthly", "Quarterly"]:
            mt = self.create_test_membership_type(
                membership_type_name=f"Perf_{period}_{self.test_run_id}",
                dues_rate={"Annual": 100, "Monthly": 10, "Quarterly": 30}[period]
            )
            membership_types.append(mt)

        # Create members in batches
        members = []
        batch_size = 100
        for i in range(0, member_count, batch_size):
            batch_count = min(batch_size, member_count - i)
            batch = self.create_test_members_bulk(
                count=batch_count,
                chapters=chapters
            )
            members.extend(batch)
            print(f"  Created {i + batch_count}/{member_count} members")

        # Create memberships (90% coverage)
        memberships = self.create_test_memberships_bulk(
            members,
            membership_types,
            coverage_ratio=0.9
        )

        # Create volunteers (30% of members)
        volunteer_count = int(member_count * 0.3)
        volunteer_members = random.sample(members, volunteer_count)
        volunteers = []
        for member in volunteer_members:
            volunteer = self.create_test_volunteer(member=member.name)
            volunteers.append(volunteer)

        print(f"✅ Created performance test data:")
        print(f"   - {len(chapters)} chapters")
        print(f"   - {len(members)} members")
        print(f"   - {len(memberships)} memberships")
        print(f"   - {len(volunteers)} volunteers")

        return {
            'chapters': chapters,
            'members': members,
            'memberships': memberships,
            'volunteers': volunteers,
            'membership_types': membership_types
        }
```

### 3. Test Runner Enhancement

Create file: `verenigingen/tests/runners/comprehensive_test_runner.py`

```python
import frappe
import unittest
import os
import sys
from pathlib import Path

class ComprehensiveTestRunner:
    """Enhanced test runner with coverage tracking"""

    def __init__(self):
        self.test_categories = {
            'core': [
                'test_critical_business_logic',
                'test_member_lifecycle',
                'test_expense_workflow'
            ],
            'edge_cases': [
                'test_edge_case_scenarios',
                'test_billing_conflicts',
                'test_zero_amounts'
            ],
            'integration': [
                'test_end_to_end_workflows',
                'test_cross_module_integration'
            ],
            'financial': [
                'test_dues_validation',
                'test_sepa_validation',
                'test_payment_processing'
            ],
            'performance': [
                'test_bulk_operations',
                'test_query_optimization'
            ]
        }

    def run_category(self, category):
        """Run tests for a specific category"""
        if category not in self.test_categories:
            print(f"Unknown category: {category}")
            return False

        test_modules = self.test_categories[category]
        suite = unittest.TestSuite()

        for module_name in test_modules:
            try:
                # Import and add tests
                module = __import__(f'vereiningen.tests.{module_name}', fromlist=[module_name])
                suite.addTests(unittest.TestLoader().loadTestsFromModule(module))
            except ImportError as e:
                print(f"Warning: Could not import {module_name}: {e}")

        # Run tests
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)

        return result.wasSuccessful()

    def run_all(self):
        """Run all test categories"""
        results = {}
        for category in self.test_categories:
            print(f"\n{'='*60}")
            print(f"Running {category} tests...")
            print('='*60)
            results[category] = self.run_category(category)

        # Summary
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        for category, success in results.items():
            status = "✅ PASSED" if success else "❌ FAILED"
            print(f"{category:20} {status}")

        return all(results.values())

    def check_coverage(self):
        """Check test coverage gaps"""
        gaps = []

        # Check for missing test files
        expected_tests = [
            'test_member_lifecycle',
            'test_expense_workflow',
            'test_dues_validation',
            'test_edge_case_scenarios'
        ]

        test_dir = Path('verenigingen/tests')
        for expected in expected_tests:
            if not any(test_dir.rglob(f'{expected}.py')):
                gaps.append(f"Missing test file: {expected}.py")

        # Check factory capabilities
        factory_file = test_dir / 'fixtures' / 'test_data_factory.py'
        if factory_file.exists():
            content = factory_file.read_text()
            required_methods = [
                'create_test_members_bulk',
                'create_edge_case_scenarios',
                'create_performance_test_data'
            ]
            for method in required_methods:
                if f'def {method}' not in content:
                    gaps.append(f"Missing factory method: {method}")

        return gaps

if __name__ == "__main__":
    runner = ComprehensiveTestRunner()

    # Check for coverage gaps first
    gaps = runner.check_coverage()
    if gaps:
        print("⚠️  Test Coverage Gaps Detected:")
        for gap in gaps:
            print(f"   - {gap}")
        print("\nRun restoration scripts to fix these gaps.")

    # Run tests based on command line argument
    if len(sys.argv) > 1:
        category = sys.argv[1]
        if category == 'all':
            success = runner.run_all()
        else:
            success = runner.run_category(category)
    else:
        print("Usage: python comprehensive_test_runner.py [all|core|edge_cases|integration|financial|performance]")
        sys.exit(1)

    sys.exit(0 if success else 1)
```

### 4. Restoration Script

Create file: `scripts/restore_critical_tests.py`

```python
#!/usr/bin/env python
"""Script to restore critical tests removed in Phase 4"""

import os
import shutil
from pathlib import Path

def restore_tests():
    """Restore critical test files"""

    restorations = [
        # (source, destination)
        ('archived_removal/test_expense_workflow_complete.py', 'verenigingen/tests/backend/workflows/test_expense_workflow_complete.py'),
        ('archived_removal/test_expense_events.py', 'verenigingen/tests/backend/workflows/test_expense_events.py'),
        ('archived_removal/test_dues_validation.py', 'verenigingen/tests/backend/financial/test_dues_validation.py'),
        ('verenigingen/tests/test_edge_case_testing_demo.py', 'verenigingen/tests/edge_cases/test_edge_case_scenarios.py'),
    ]

    for source, dest in restorations:
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # Use git to restore file
        os.system(f'git checkout HEAD -- {source}')

        if Path(source).exists():
            shutil.move(source, dest)
            print(f"✅ Restored: {dest}")
        else:
            print(f"❌ Failed to restore: {source}")

    print("\n📝 Next steps:")
    print("1. Update imports in restored files")
    print("2. Run comprehensive_test_runner.py to verify")
    print("3. Commit restored tests")

if __name__ == "__main__":
    restore_tests()
```

## Summary of Restoration Actions

1. **Restore 4 critical test files** containing ~15 essential test methods
2. **Enhance factory with 4 bulk methods** for scenario generation
3. **Create comprehensive test runner** with category-based execution
4. **Add coverage gap detection** to prevent future regressions

These specific actions will restore the most critical test coverage while maintaining the improved organization from Phase 4.
