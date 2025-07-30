# Field Reference Fixes Summary

## Issues Found

### 1. Invalid `member.chapter` field references (9 occurrences)
**Problem**: Tests are trying to access/set `member.chapter`, but this field doesn't exist in the Member doctype.
**Solution**: Use Chapter Member relationships or `current_chapter_display` field.

**Files affected:**
- `verenigingen/tests/test_member_status_transitions_enhanced.py` (2 occurrences)
- `verenigingen/tests/backend/components/test_chapter_assignment_comprehensive.py` (6 occurrences)
- `verenigingen/tests/backend/components/test_member_status_transitions.py` (1 occurrence)

### 2. Invalid `annual_fee` field references (37 occurrences)
**Problem**: Tests are trying to access/set `annual_fee` on Membership documents, but this field doesn't exist.
**Solution**: Use `membership_type.minimum_amount` or Membership Dues Schedule relationships.

**Files most affected:**
- `verenigingen/tests/backend/comprehensive/test_financial_integration_edge_cases.py` (18 occurrences)
- `verenigingen/tests/backend/comprehensive/test_termination_workflow_edge_cases.py` (6 occurrences)
- `verenigingen/tests/backend/components/test_payment_failure_scenarios.py` (8 occurrences)
- `verenigingen/tests/backend/security/test_security_comprehensive.py` (3 occurrences)
- `verenigingen/tests/backend/performance/test_performance_edge_cases.py` (1 occurrence)
- `verenigingen/tests/test_member_status_transitions_enhanced.py` (1 occurrence)

## Correct Field Structure (From DocType JSON Analysis)

### Member DocType
- ✅ `current_chapter_display` (HTML field showing current chapters)
- ✅ `chapter_assigned_by` (User who assigned chapter)
- ✅ `previous_chapter` (Link to previous chapter)
- ✅ `chapter_change_reason` (Text field for change reason)
- ❌ `chapter` (DOES NOT EXIST)

### Membership DocType
- ✅ `member` (Link to Member)
- ✅ `membership_type` (Link to Membership Type)
- ✅ `status`, `start_date`, `renewal_date`
- ❌ `annual_fee` (DOES NOT EXIST - fee comes from membership_type.minimum_amount)

### Membership Type DocType
- ✅ `minimum_amount` (Currency field for fee)
- ✅ `billing_period`
- ✅ `dues_schedule_template`

## Fix Strategy

### For `member.chapter` references:
1. Replace direct assignments with Chapter Member relationship creation
2. Replace assertions with Chapter Member queries
3. Use `assign_member_to_chapter()` function when available

### For `annual_fee` references:
1. Remove from Membership document creation
2. Set fees via Membership Type `minimum_amount` field instead
3. Replace assertions with membership_type.minimum_amount checks
4. Use Membership Dues Schedule for actual billing amounts

## Status
- ✅ Analysis completed
- 🚧 Fixes in progress
- ⏳ Testing pending
