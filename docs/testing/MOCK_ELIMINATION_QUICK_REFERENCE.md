# Mock Elimination Quick Reference Guide
**Daily Developer Companion - Phase 5.1 Proven Pattern**

---

## 🚀 **Quick Decision Matrix**

### **Should I Apply Mock Elimination?**
```
✅ YES - Apply pattern if:
- Financial or regulatory business logic
- 2+ database mocks in existing tests
- Critical member/payment workflows
- Dutch compliance (ANBI, BSN, SEPA)

❌ NO - Skip if:
- Pure utility functions
- UI/display logic only
- Infrastructure operations
- <30 minutes available
```

---

## ⚡ **5-Minute Setup Template**

### **Copy-Paste Test Structure**
```python
"""
[Your Area] - Real Database Testing
=================================
Eliminates [X] database mocks: [list specific @patch statements]
Performance Target: <5 seconds
"""

import frappe
from frappe.utils import today
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

class Test[YourArea]Real(EnhancedTestCase):

    def setUp(self):
        super().setUp()
        self.test_record = self.create_test_[doctype](
            # ONLY required fields - check DocType JSON first!
        )

    def test_[function]_real_database_no_mocks(self):
        """ELIMINATES @patch('[specific_mock]') - uses real [operation]"""

        # Real operation - NO MOCKS
        result = your_function(self.test_record.name)

        # Validate real result
        self.assertIsNotNone(result, "Real operation should work")

        # Verify with real database
        real_doc = frappe.get_doc("DocType", self.test_record.name)
        self.assertEqual(real_doc.field, expected_value)

    def test_mock_elimination_summary(self):
        """Performance validation and success confirmation"""
        import time
        start_time = time.time()

        # Test your real operations here

        elapsed = time.time() - start_time
        self.assertLess(elapsed, 5.0, f"Performance: {elapsed:.2f}s")

        print("✅ SUCCESS: [X] database mocks → Real operations")
```

---

## 🎯 **Mock Classification Cheat Sheet**

### **ELIMINATE These Database Mocks**
```python
❌ @patch("frappe.get_doc")           # → Use real frappe.get_doc()
❌ @patch("frappe.db.exists")         # → Use real frappe.db.exists()
❌ @patch("frappe.db.get_value")      # → Use real frappe.db.get_value()
❌ @patch("frappe.db.sql")            # → Use real frappe.db.sql()
❌ @patch("frappe.db.get_single_value") # → Use real settings retrieval
```

### **PRESERVE These Infrastructure Mocks**
```python
✅ @patch("frappe.sendmail")          # Keep - Email infrastructure
✅ @patch("builtins.open")            # Keep - File operations
✅ @patch("requests.post")            # Keep - External APIs
✅ @patch("frappe.utils.password.decrypt") # Keep - Encryption
✅ @patch("logging.*")                # Keep - Logging systems
```

---

## 🔧 **Common Fix Patterns**

### **Field Name Validation Error**
```python
# ERROR: FieldValidationError: Field 'wrong_field' not found
# FIX: Always check DocType JSON first!

# 1. Read DocType definition:
cat verenigingen/doctype/[name]/[name].json | jq '.fields[].fieldname'

# 2. Use EXACT field name from JSON:
self.test_record = self.create_test_member(
    first_name="Test",           # ✅ Correct field name
    # wrong_field="Value"        # ❌ This causes error
)
```

### **Mandatory Field Error**
```python
# ERROR: MandatoryError: [DocType]: field_name
# FIX: Add all mandatory fields

# Check DocType for required fields:
grep -A3 -B1 '"reqd": 1' verenigingen/doctype/[name]/[name].json

# Add to test data:
donation = frappe.get_doc({
    "doctype": "Donation",
    "donor": donor.name,
    "amount": 100.0,
    "mode_of_payment": "Bank Transfer",  # ← Add this mandatory field!
    # ... other fields
})
```

### **Performance Timeout**
```python
# ERROR: Test takes >5 seconds
# FIX: Lightweight setUp() method

# ❌ SLOW - Heavy setup
def setUp(self):
    self.member = self.create_test_member(...)
    self.user = self.create_test_user(...)
    self.volunteer = self.create_test_volunteer(...)
    self.team = self.create_test_team(...)            # Too much!

# ✅ FAST - Minimal setup
def setUp(self):
    self.member = self.create_test_member(
        first_name="Test",
        last_name="User"
        # Only essential fields!
    )
```

---

## 📊 **Success Validation Checklist**

### **Before Committing Your Test**
```
□ Test runs in <5 seconds
□ At least 1 database mock eliminated
□ Real business logic tested (not mocked)
□ Uses actual field names from DocType JSON
□ Performance validation included
□ Any production issues documented
```

### **Success Indicators**
```
✅ GOOD SIGNS:
- Test discovers field name errors
- Mandatory field errors caught
- Validation logic errors found
- Real database constraints tested
- Business rules authentically validated

🚨 WARNING SIGNS:
- Test takes >5 seconds
- No business logic actually tested
- Still using database mocks for business operations
- Creating heavy test data in setUp()
```

---

## 🐛 **Production Issue Discovery**

### **When You Find a Bug (Expected!)**
```
1. 🎉 CELEBRATE - You found a real issue!
2. 📝 DOCUMENT in PRODUCTION_ISSUES_DISCOVERED.md:
   - Error message and stack trace
   - Business impact assessment
   - What mocked test missed vs real test found
3. 🔧 FIX the underlying issue
4. ✅ ADD regression test
5. 🤝 SHARE learning with team
```

### **Common Production Issues Found**
- Wrong database field names in queries
- Missing mandatory fields in document creation
- Invalid validation logic in business rules
- Incorrect business assumptions in code
- Database constraint violations

---

## ⏱️ **Time Estimates**

### **Realistic Time Investment**
```
File Assessment:        5 minutes
Setup & Basic Tests:   20 minutes
Performance Tuning:    10 minutes
Bug Discovery & Fix:   15 minutes (bonus!)
Documentation:          5 minutes
------------------------
Total Investment:      45-60 minutes per file
Business Value:        1+ production bugs prevented
```

### **When to Stop**
```
✅ STOP when:
- 2-5 database mocks eliminated
- <5 second performance achieved
- Real business logic tested
- Any bugs discovered and documented

❌ DON'T try to:
- Eliminate ALL mocks (preserve infrastructure)
- Achieve 100% real database coverage
- Spend >60 minutes per file
- Fix every possible edge case
```

---

## 🎯 **Target Business Areas**

### **High-Value Targets (Apply Pattern)**
```
1. 🏦 ANBI Tax Compliance ✅ DONE
2. 💳 SEPA Payment Processing
3. 🏛️ Dutch Regulatory (BSN/RSIN)
4. 💰 Financial Calculations
5. 🔄 ERPNext Integration
6. 👥 Member Lifecycle
7. ⚠️ Suspension/Termination ✅ DONE
```

### **Low-Value Areas (Skip for Now)**
```
- Pure utility functions
- Display/formatting logic
- Infrastructure operations
- Report generation (UI)
- Import/export utilities
- Administrative helpers
```

---

## 📱 **Need Help?**

### **Quick Commands**
```bash
# Find database mocks to eliminate:
grep -r "@patch.*frappe\.db\." your_area/

# Check DocType field names:
cat verenigingen/doctype/[name]/[name].json | jq '.fields[].fieldname'

# Run your test:
bench --site dev.veganisme.net run-tests --module your.test.module

# Check test performance:
time bench --site dev.veganisme.net run-tests --module your.test.module
```

### **Resources**
- 📖 Full Methodology: `SYSTEMATIC_MOCK_ELIMINATION_METHODOLOGY.md`
- 🐛 Production Issues: `PRODUCTION_ISSUES_DISCOVERED_PHASE_5_1.md`
- ✅ Success Examples: `test_anbi_donation_summary_report_minimal_real.py`
- 🔧 Enhanced Test Factory: `tests/fixtures/enhanced_test_factory.py`

---

**Remember: The goal is authentic business logic testing that discovers real production issues. Success is measured by bugs prevented, not mocks eliminated!**
