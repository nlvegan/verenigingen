# Approval Thresholds Quick Reference

## Summary Card

**Quick Reference for Approval Authorities and Limits**

| Type | Auto-Approve | Manual Review | Authority Required |
|------|-------------|---------------|-------------------|
| **Expenses** | None | All amounts | Role + Amount-based |
| **Terminations** | Standard types | Disciplinary | Type-based |
| **Fee Changes** | Member increases <€1,000 | Decreases, >€1,000 | Manager level |
| **SEPA Batches** | None | All batches | Treasurer+ level |

---

## Volunteer Expense Thresholds

### By Approval Role

| Role | Maximum Approval Authority | Notes |
|------|---------------------------|--------|
| **System Manager** | Unlimited | Full system access |
| **Verenigingen Administrator** | Unlimited | Application-wide authority |
| **Chapter Head** | €1,000 | Per expense, chapter scope |
| **Treasurer** | €500 | Financial oversight role |
| **Team Leader** | €500 | Team expenses only |
| **Secretary** | €0 | Cannot approve expenses |
| **Board Members (other)** | €0 | Unless specific permissions |

### By Expense Amount

| Amount Range | Permission Level | Eligible Approvers |
|--------------|------------------|-------------------|
| **€0 - €100** | Basic | Team Leaders, Treasurers, Chapter Heads |
| **€101 - €500** | Financial | Treasurers, Chapter Heads |
| **€501 - €1,000** | Management | Chapter Heads only |
| **€1,000+** | Admin | System/App Administrators only |

### Escalation Thresholds

| Trigger | Escalation Action |
|---------|------------------|
| Team expense >€500 | Route to chapter approval |
| Chapter expense >€1,000 | Require administrator approval |
| Pending >7 days | Send reminder notifications |
| Pending >14 days | Escalate to supervisor |

---

## Membership Termination Approval Requirements

### By Termination Type

| Type | Secondary Approval Required | Documentation | Grace Period |
|------|----------------------------|---------------|--------------|
| **Voluntary** | No | Basic reason | 30 days |
| **Non-payment** | No | Payment history | 30 days |
| **Deceased** | No | Death certificate | 30 days |
| **Policy Violation** | **Yes** | Incident documentation | Immediate |
| **Disciplinary Action** | **Yes** | Investigation report | Immediate |
| **Expulsion** | **Yes** | Complete case file | Immediate |

### Approval Authority Matrix

| Termination Type | Primary Approver | Secondary Approver |
|------------------|------------------|-------------------|
| Standard (Vol/Non-pay/Deceased) | Chapter Board Member | Not required |
| Policy Violation | Chapter Head | Board Member |
| Disciplinary Action | Chapter Head | System Manager |
| Expulsion | System Manager | Verenigingen Admin |

---

## Fee Amendment Auto-Approval Rules

### Auto-Approved Conditions (ALL must be met)

✅ **Member-initiated request** (not staff-initiated)
✅ **Fee increase only** (no decreases)
✅ **Amount ≤ €1,000** (configurable limit)
✅ **Change ≤ 5%** of current amount OR fee increase
✅ **Within frequency limits** (≤2 changes per 365 days)
✅ **Active membership** status

### Manual Approval Required

❌ **Any fee decrease** (regardless of amount)
❌ **Amount >€1,000** (exceeds auto-approval limit)
❌ **Staff-initiated** changes
❌ **>2 changes** in past 365 days
❌ **Membership type changes**
❌ **Billing interval changes**

### Amendment Authority

| Role | Authority Level |
|------|----------------|
| System Manager | All amendments |
| Verenigingen Manager | All amendments |
| Verenigingen Staff | Read-only access |

---

## SEPA Batch Approval Matrix

### Approval Requirements

| Batch Characteristics | Approval Level | Approver Required |
|----------------------|---------------|-------------------|
| **Standard batches** | Standard | Verenigingen Treasurer |
| **High-risk batches** | Enhanced | Verenigingen Manager |
| **Failed retry batches** | Review | System Manager |
| **Emergency batches** | Urgent | System Manager |

### Risk Assessment Factors

| Factor | Low Risk | Medium Risk | High Risk |
|--------|----------|-------------|-----------|
| **Total Amount** | <€10,000 | €10,000-€50,000 | >€50,000 |
| **Transaction Count** | <100 | 100-500 | >500 |
| **FRST Transactions** | <5% | 5-20% | >20% |
| **Failed Retries** | None | 1-2 per mandate | >2 per mandate |

### Validation Checklist

Before approval, verify:
- [ ] All SEPA mandates active and valid
- [ ] IBAN formats correct and accounts active
- [ ] Amounts match invoices/dues schedules
- [ ] No duplicate transactions in batch
- [ ] Sequence types appropriate (FRST/RCUR)
- [ ] Bank account details current
- [ ] Pre-notification requirements met

---

## Standard Processing Times

### Target Response Times

| Request Type | Target Response | Maximum Time | Auto-Escalation |
|--------------|----------------|--------------|-----------------|
| **Volunteer Expense** | 48 hours | 7 days | After 3 days |
| **Membership Termination** | 5 business days | 14 days | After 7 days |
| **Fee Amendment (manual)** | 3 business days | 10 days | After 5 days |
| **SEPA Batch** | 24 hours | 72 hours | After 48 hours |

### Holiday/Weekend Adjustments

- **Standard processing** excludes weekends/holidays
- **Emergency procedures** available for urgent cases
- **Auto-escalation timers** paused during closure periods
- **Alternative approvers** activated during absences

---

## Emergency Override Procedures

### Emergency Approval Authority

| Situation | Override Authority | Documentation Required |
|-----------|-------------------|----------------------|
| **System outage** | System Manager | Incident report |
| **Critical member issue** | Verenigingen Admin | Business justification |
| **Financial emergency** | System Manager + Finance Head | Dual authorization |
| **Legal requirement** | System Manager | Legal documentation |

### Emergency Contact Escalation

1. **Chapter Level**: Chapter Head → Verenigingen Admin
2. **System Level**: Verenigingen Admin → System Manager
3. **Financial**: Treasurer → Finance Head → System Manager
4. **Legal/Compliance**: Any Admin → System Manager → Legal Counsel

---

## Configuration Settings Reference

### System Settings (Verenigingen Settings DocType)

| Setting | Default | Impact |
|---------|---------|--------|
| `auto_approve_fee_increases` | Enabled | Member fee increases auto-approved |
| `auto_approve_member_requests` | Enabled | Member-initiated requests auto-approved |
| `max_auto_approve_amount` | €1,000 | Maximum auto-approval amount |
| `max_adjustments_per_year` | 2 | Frequency limit per member |

### Role-Based Expense Limits (Configurable)

| Role Setting | Default Value | Configurable |
|--------------|---------------|--------------|
| Chapter Head expense limit | €1,000 | Yes (per chapter) |
| Treasurer expense limit | €500 | Yes (system-wide) |
| Team Leader expense limit | €500 | Yes (per team) |

---

## Quick Decision Trees

### Expense Approval Decision

```
Is expense amount ≤ my approval limit?
├─ Yes → Can I approve this expense type for this organization?
│  ├─ Yes → APPROVE
│  └─ No → ESCALATE to appropriate approver
└─ No → ESCALATE to higher authority
```

### Fee Amendment Decision

```
Is this a member self-service request?
├─ Yes → Is it a fee increase ≤ €1,000 and ≤5% change?
│  ├─ Yes → AUTO-APPROVED
│  └─ No → MANUAL REVIEW required
└─ No → MANUAL REVIEW required
```

### Termination Approval Decision

```
What is the termination type?
├─ Voluntary/Non-payment/Deceased → Single approval required
└─ Policy Violation/Disciplinary/Expulsion → Secondary approval required
```

---

## Common Threshold Questions

### Q: Can a Team Leader approve a €600 expense?
**A:** No. Team Leaders have a €500 limit. The expense must be escalated to Chapter Head approval.

### Q: Will a member's fee increase from €25 to €30 be auto-approved?
**A:** Yes, if it's member-initiated, represents a 20% increase (>5% threshold), but is still under the €1,000 limit and within frequency limits.

### Q: Who can approve a SEPA batch with €75,000 total?
**A:** This high-amount batch requires System Manager approval due to risk assessment.

### Q: How long should a termination approval take?
**A:** Target is 5 business days, maximum 14 days. Auto-escalation occurs after 7 days.

### Q: Can a Secretary approve membership terminations?
**A:** Yes, Secretaries can initiate and approve standard terminations (non-disciplinary) as board members.

---

**For detailed procedures and troubleshooting, see the complete [Approval Workflows Guide](APPROVAL_WORKFLOWS_GUIDE.md).**
