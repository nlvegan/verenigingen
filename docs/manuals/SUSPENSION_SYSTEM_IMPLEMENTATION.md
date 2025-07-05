# Member Suspension System Implementation

## Overview

The suspension system provides a **temporary, reversible alternative** to permanent termination. This allows board members and administrators to suspend members for disciplinary reasons, non-payment, or other temporary issues while preserving the ability to fully restore the member later.

## Key Differences: Suspension vs Termination

| Aspect | Suspension | Termination |
|--------|------------|-------------|
| **Reversibility** | ✅ Fully reversible | ❌ Permanent action |
| **Member Status** | Suspended (temporary) | Terminated/Banned (permanent) |
| **Memberships** | Remain active | Cancelled |
| **Status Restoration** | Restores to original status | Cannot be restored |
| **Use Cases** | Temporary disciplinary, payment issues | Policy violations, expulsions |
| **Team Access** | Suspended, can be restored | Removed permanently |

## Implementation Details

### 1. Core Suspension Functions (`termination_integration.py`)

**`suspend_member_safe(member_name, suspension_reason, suspend_user=True, suspend_teams=True)`**
- Sets member status to "Suspended"
- Stores original status in `pre_suspension_status` field
- Optionally disables user account
- Optionally suspends team memberships
- Adds detailed notes with suspension reason and date
- Returns comprehensive results with actions taken

**`unsuspend_member_safe(member_name, unsuspension_reason)`**
- Restores member to original status (from `pre_suspension_status`)
- Reactivates user account if it was suspended
- Adds unsuspension notes
- Team memberships require manual restoration (by design)
- Returns results with restoration actions

**`get_member_suspension_status(member_name)`**
- Checks current suspension state
- Reports user account status
- Counts active team memberships
- Provides restoration readiness information

### 2. API Endpoints (`suspension_api.py`)

**Frontend-Safe API Methods:**
- `suspend_member()` - Execute suspension with permission checks
- `unsuspend_member()` - Execute unsuspension with permission checks
- `get_suspension_status()` - Get current status for UI rendering
- `can_suspend_member()` - Permission check for UI buttons
- `get_suspension_preview()` - Preview suspension impact before action
- `bulk_suspend_members()` - Suspend multiple members at once

**Permission Integration:**
- Uses existing `can_terminate_member()` permission function
- Board members can suspend members in their chapters
- System/Association managers can suspend any member

### 3. Frontend Integration (`member.js`)

**Smart Button Display:**
- Shows "Suspend Member" for non-suspended members
- Shows "Unsuspend Member" for suspended members
- Permission-aware (only shows to authorized users)
- Real-time status checking

**Suspension Dialog Features:**
- **Impact Preview**: Shows what will be affected (teams, user account, etc.)
- **Configurable Options**: Choose to suspend user account and/or teams
- **Detailed Information**: Lists current teams and roles
- **Confirmation Steps**: Requires reason and confirmation

**Status Display:**
- Orange dashboard indicator for suspended members
- Red indicator for disabled user accounts
- Visual status tracking in member badge color

### 4. Member Integration (`termination_mixin.py`)

**Programmatic Methods:**
```python
member = frappe.get_doc("Member", "MEMBER-12345")

# Suspend member
result = member.suspend_member("Payment overdue", suspend_user=True, suspend_teams=True)

# Check suspension status
status = member.get_suspension_summary()

# Unsuspend member
result = member.unsuspend_member("Payment received")
```

**Visual Status Updates:**
- Suspension status affects member badge colors
- Orange color for suspended members
- Integrated with existing status display system

## Usage Scenarios

### 1. Disciplinary Suspension
```
Scenario: Member violates community guidelines
Action: Suspend with user account and team access disabled
Result: Member cannot log in or participate in teams
Restoration: When issue is resolved, full restoration possible
```

### 2. Payment Issues
```
Scenario: Member has overdue payments
Action: Suspend teams only, keep user account active
Result: Member can still log in but cannot participate in teams
Restoration: When payment received, restore team access
```

### 3. Temporary Leave
```
Scenario: Member requests temporary leave
Action: Suspend teams and user account
Result: Member status preserved for return
Restoration: Full restoration when member returns
```

### 4. Investigation Period
```
Scenario: Allegation requires investigation
Action: Suspend user account and teams pending investigation
Result: Member access suspended during investigation
Restoration: Full restoration if cleared, termination if guilty
```

## Technical Features

### Permission System
- **Same permissions as termination**: Board members for their chapters, managers for all
- **API-level checks**: All suspension actions validate permissions
- **UI-level filtering**: Buttons only show to authorized users

### Audit Trail
- **Detailed logging**: All suspension/unsuspension actions logged
- **Reason tracking**: Required reason field for all actions
- **Status preservation**: Original status stored for accurate restoration
- **Timeline tracking**: Notes added with dates and reasons

### Error Handling
- **Safe operations**: Uses same safe integration patterns as termination
- **Rollback capability**: Failed operations don't leave member in inconsistent state
- **Detailed reporting**: Returns specific information about what succeeded/failed

### Bulk Operations
- **Mass suspension**: Suspend multiple members with single action
- **Permission validation**: Checks each member individually
- **Progress reporting**: Detailed results for each member processed

## Frontend User Experience

### For Board Members
1. Navigate to member in their chapter
2. See "Suspend Member" button (if permitted)
3. Click button → Preview dialog shows impact
4. Configure suspension options (user account, teams)
5. Enter reason and confirm
6. Member immediately suspended with visual feedback

### For Suspended Members
1. Member form shows "Member Suspended" indicator
2. "Unsuspend Member" button available (if permitted)
3. Unsuspension dialog explains restoration process
4. Enter reason and confirm
5. Member restored to original status

### Visual Indicators
- **Orange dashboard indicators** for suspended members
- **Badge color changes** in member list views
- **Status-aware buttons** (suspend/unsuspend based on current state)

## Benefits

### 1. Operational Flexibility
- **Temporary disciplinary action** without permanent consequences
- **Graduated response** system (suspend → terminate if needed)
- **Payment enforcement** without losing members permanently

### 2. Proper Governance
- **Audit compliance** with detailed tracking
- **Permission-based access** ensuring proper authorization
- **Reversible actions** allowing correction of mistakes

### 3. User-Friendly Interface
- **Clear visual feedback** about suspension status
- **Impact preview** before taking action
- **Simple restoration** process when appropriate

### 4. Technical Robustness
- **Same safety patterns** as termination system
- **Comprehensive error handling** and logging
- **Integration with existing** permission and audit systems

## Deployment Notes

### Prerequisites
- Enhanced termination system must be installed
- No additional database changes required
- Uses existing permission structure

### Backward Compatibility
- Existing member statuses preserved
- No impact on existing termination workflow
- Can be deployed alongside existing system

### Testing
- Comprehensive test suite validates all functions
- Permission testing confirms proper access control
- UI testing verifies proper button display and functionality

The suspension system provides a powerful, user-friendly tool for temporary member management while maintaining the robust permission structure and audit capabilities of the termination system.
