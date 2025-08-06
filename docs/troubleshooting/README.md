# Verenigingen Troubleshooting Documentation

This directory contains comprehensive error recovery and troubleshooting documentation for the Verenigingen system.

## Documentation Overview

### 📘 [Error Recovery Guide](ERROR_RECOVERY_GUIDE.md)
**Primary comprehensive guide** covering all major system failure scenarios:

- **Payment System Failures**
  - SEPA direct debit failures with bank codes
  - Mandate creation and validation errors
  - Payment reconciliation issues
  - Failed transactions and retry mechanisms

- **Portal Access Issues**
  - Login failures and password resets
  - Permission denied errors with role fixes
  - Session timeout handling
  - Browser compatibility troubleshooting

- **Data Processing Errors**
  - Import failure diagnostics and recovery
  - Validation error resolution
  - Duplicate entry prevention and cleanup
  - Data integrity restoration

- **Integration Failures**
  - eBoekhouden API connection recovery
  - Timeout and rate limiting solutions
  - Webhook failure debugging
  - Email delivery troubleshooting

- **System-Level Issues**
  - Database connection restoration
  - Redis/cache problem resolution
  - Background job recovery
  - Server resource management

### 🆘 [Quick Reference Card](QUICK_REFERENCE_CARD.md)
**Emergency procedures** for immediate response situations:

- System down recovery (5-minute guide)
- Common payment failure fixes
- Portal access quick fixes
- Database emergency commands
- Background job restart procedures
- Emergency contact information

### 💡 [Practical Error Examples](PRACTICAL_ERROR_EXAMPLES.md)
**Real-world scenarios** with actual error messages and solutions:

- SEPA payment rejection scenarios (AM04, AC04, etc.)
- Validation error examples with exact fixes
- Login failure diagnostics with user account recovery
- Import error resolution with CSV corrections
- API timeout recovery with retry mechanisms
- Performance issue diagnosis and optimization

### 🔍 [Workspace Debugging Guide](workspace-debugging.md)
**Development and testing** troubleshooting procedures:

- Development environment debugging
- Test execution troubleshooting
- Code validation issues
- Performance testing procedures

## New: Automation and Business Rules Documentation

### 🤖 [Automated Processes Guide](../user-manual/AUTOMATED_PROCESSES_GUIDE.md)
**Complete guide to system automation** covering:

- **Daily scheduled tasks** (member refresh, invoice generation, payment retry)
- **Background processing** (payment updates, donor creation, notifications)
- **SEPA batch automation** (creation, validation, collection timing)
- **Membership automation** (renewals, grace periods, terminations)
- **Error handling** and retry mechanisms built into automated processes

### 📋 [Business Rules Reference](../user-manual/BUSINESS_RULES_REFERENCE.md)
**System limits and validation rules** including:

- **Membership rules** (fee limits, billing periods, status transitions)
- **Payment processing rules** (SEPA validation, batch limits, retry logic)
- **Volunteer and chapter rules** (assignment logic, approval requirements)
- **Data quality rules** (format validation, duplicate prevention)

### 📅 [Automation Schedule Reference](../user-manual/AUTOMATION_SCHEDULE_REFERENCE.md)
**Quick reference for timing** with:

- **Daily schedule** (exact times for all automated processes)
- **Performance expectations** (normal durations, warning thresholds)
- **Planning guidance** (best times for manual work, avoiding conflicts)

## Using This Documentation

### For Emergency Situations
1. **Start with**: [Quick Reference Card](QUICK_REFERENCE_CARD.md)
2. **Check automation**: [Automation Schedule Reference](../user-manual/AUTOMATION_SCHEDULE_REFERENCE.md) for timing conflicts
3. **Follow up with**: [Error Recovery Guide](ERROR_RECOVERY_GUIDE.md) relevant section
4. **For examples**: Check [Practical Error Examples](PRACTICAL_ERROR_EXAMPLES.md)

### For Automation Issues
1. **Check timing**: [Automation Schedule Reference](../user-manual/AUTOMATION_SCHEDULE_REFERENCE.md)
2. **Understand process**: [Automated Processes Guide](../user-manual/AUTOMATED_PROCESSES_GUIDE.md)
3. **Verify rules**: [Business Rules Reference](../user-manual/BUSINESS_RULES_REFERENCE.md)
4. **Troubleshoot**: [Error Recovery Guide](ERROR_RECOVERY_GUIDE.md) automation section

### For Planned Troubleshooting
1. **Start with**: [Error Recovery Guide](ERROR_RECOVERY_GUIDE.md)
2. **Reference**: [Practical Error Examples](PRACTICAL_ERROR_EXAMPLES.md) for similar scenarios
3. **Check automation**: [Automated Processes Guide](../user-manual/AUTOMATED_PROCESSES_GUIDE.md) for process details
4. **Quick commands**: Use [Quick Reference Card](QUICK_REFERENCE_CARD.md)

### For Development Issues
1. **Start with**: [Workspace Debugging Guide](workspace-debugging.md)
2. **Check business rules**: [Business Rules Reference](../user-manual/BUSINESS_RULES_REFERENCE.md)
3. **System issues**: Fall back to [Error Recovery Guide](ERROR_RECOVERY_GUIDE.md)

## Key System Components Covered

### Payment Processing
- **SEPA Mandate System**: Creation, validation, lifecycle management
- **Direct Debit Batches**: Generation, processing, failure handling
- **Payment Reconciliation**: Matching, duplicate resolution, error recovery
- **Bank Integration**: API connectivity, return code handling, retry logic

### User Management
- **Portal Access**: Authentication, permissions, session management
- **Role Assignment**: Member, volunteer, admin role troubleshooting
- **Account Management**: Creation, activation, password recovery

### Data Integration
- **eBoekhouden Sync**: API connectivity, transaction processing, error recovery
- **Data Import**: CSV processing, validation, bulk operations
- **Data Quality**: Duplicate detection, integrity validation, cleanup

### System Infrastructure
- **Database Management**: Connection pools, query optimization, backup/restore
- **Cache Systems**: Redis troubleshooting, cache invalidation, performance
- **Background Jobs**: Queue management, worker processes, job recovery
- **Email Systems**: SMTP configuration, template management, delivery monitoring

## Diagnostic Command Categories

### System Health
```bash
bench status                    # Service status
bench doctor                   # Comprehensive health check
bench --site [site] mariadb   # Database access
```

### Data Validation
```bash
# Member data validation
bench --site [site] execute verenigingen.utils.data_quality_utils.validate_member_import

# SEPA validation
bench --site [site] execute verenigingen.utils.sepa_validator.validate_mandates

# Financial data integrity
bench --site [site] execute verenigingen.utils.payment_utils.validate_financial_integrity
```

### Recovery Operations
```bash
# Payment retry
bench --site [site] execute verenigingen.utils.sepa_retry_manager.create_retry_batch

# Permission fix
bench --site [site] execute verenigingen.api.fix_customer_permissions.fix_member_permissions

# Email queue retry
bench --site [site] execute frappe.email.queue.retry_sending
```

## Error Escalation Matrix

| Severity | Response Time | Examples | Actions |
|----------|--------------|----------|---------|
| **CRITICAL** | < 1 hour | System down, data loss, security breach | Immediate escalation, all hands |
| **HIGH** | < 4 hours | Payment processing down, portal inaccessible | Technical team lead notification |
| **MEDIUM** | < 24 hours | Individual user issues, minor integration failures | Standard support queue |
| **LOW** | < 72 hours | Enhancement requests, documentation updates | Backlog prioritization |

## Preventive Maintenance

### Daily Checks
- [ ] System health dashboard review
- [ ] Error log summary analysis
- [ ] Payment processing status verification
- [ ] Email delivery queue monitoring

### Weekly Reviews
- [ ] Performance metrics analysis
- [ ] Integration connectivity testing
- [ ] User access issue trends
- [ ] Documentation update needs

### Monthly Audits
- [ ] Security access reviews
- [ ] System capacity planning
- [ ] Disaster recovery testing
- [ ] Training needs assessment

## Integration with Monitoring

This troubleshooting documentation integrates with:

- **[System Monitoring](../monitoring/README.md)**: Proactive issue detection
- **[Security Monitoring](../security/README.md)**: Security incident response
- **[Performance Monitoring](../optimization/README.md)**: Performance issue resolution

## Feedback and Improvements

This documentation is continuously improved based on:

- Real incident experiences
- User feedback and questions
- System evolution and changes
- Best practice discoveries

**To contribute**: Document new error scenarios in [Practical Error Examples](PRACTICAL_ERROR_EXAMPLES.md) and update relevant sections in the [Error Recovery Guide](ERROR_RECOVERY_GUIDE.md).

---

**Document Maintenance**:
- **Owner**: Technical Team
- **Review Schedule**: Monthly for accuracy, quarterly for completeness
- **Version Control**: All changes tracked in git repository
- **Training**: Quarterly sessions for support staff

**For immediate assistance**: See emergency contacts in [Quick Reference Card](QUICK_REFERENCE_CARD.md)
