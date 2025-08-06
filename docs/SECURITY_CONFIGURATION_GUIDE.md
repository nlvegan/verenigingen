# Security Configuration Guide for Verenigingen

**Critical Post-Installation Security Configuration Requirements**

This guide addresses 4 critical security issues identified during comprehensive test infrastructure implementation that require immediate administrative attention after Verenigingen installation.

## Overview

The Verenigingen test infrastructure has identified legitimate security policy gaps that must be addressed through system configuration rather than code changes. These issues affect data privacy, regulatory compliance, and organizational data isolation.

## Critical Security Issues Requiring Configuration

### 🔴 CRITICAL: Guest Access Control Gap

**Issue:** Guest users can currently access member personal data and financial information
**Risk:** Data privacy violation, potential GDPR compliance issues
**Impact:** High - Unauthorized access to sensitive member information

**Solution Steps:**
1. Navigate to: **Setup > Users and Permissions > Role Permissions Manager**
2. Select Role: **"Guest"**
3. For the following DocTypes, **remove ALL permissions** (read, write, create, delete):
   - Member
   - SEPA Mandate
   - Membership
   - Volunteer Expense
   - Direct Debit Batch
   - Payment Entry
4. Save changes
5. **Validation:** Log out and try accessing `/app` - should not see member data

### 🔴 CRITICAL: Financial Data Isolation

**Issue:** Guest users can view SEPA mandate and financial information
**Risk:** Financial fraud, privacy violations, regulatory compliance issues
**Impact:** High - Exposure of sensitive financial data

**Solution Steps:**
1. Navigate to: **Setup > Users and Permissions > Role Permissions Manager**
2. Select Role: **"Guest"**
3. For financial DocTypes, **remove ALL permissions**:
   - SEPA Mandate
   - Direct Debit Batch
   - Sales Invoice
   - Payment Entry
   - Member Payment History
4. Select Role: **"Verenigingen Member"**
5. For financial DocTypes: Only allow **"read"** for own records (if business requirement exists)
6. **Validation:** Non-financial users should not access payment/mandate information

### 🟡 HIGH: Document-Level Permission Enforcement

**Issue:** Users can access documents from other organizational units (chapters)
**Risk:** Cross-organizational data leakage
**Impact:** Medium - Data isolation breach between chapters

**Solution Steps:**
1. Navigate to: **Setup > Users and Permissions > Role Permissions Manager**
2. Select Role: **"Verenigingen Chapter Manager"**
3. For DocType **"Member"**:
   - Enable **"User Permission"**
   - Set condition ensuring users only see members from their assigned chapter
4. For DocType **"Verenigingen Volunteer"**:
   - Enable **"User Permission"** with chapter restriction
5. Navigate to: **Setup > Users and Permissions > User Permissions**
6. For each Chapter Manager user:
   - Add **User Permission** for their specific Chapter
   - Ensure they can only access their chapter's data
7. **Validation:** Chapter Manager should only see members from their assigned chapter

### 🟡 MEDIUM: Audit Trail Compliance

**Issue:** Document version tracking is disabled
**Risk:** Regulatory compliance gaps, inability to track changes for audit purposes
**Impact:** Medium - Audit and compliance requirements not met

**Solution Steps:**
1. Navigate to: **Setup > System Settings**
2. Check **"Track Changes"** option
3. Navigate to: **Setup > Customize > DocType List**
4. For critical DocTypes (Member, Membership, SEPA Mandate, Volunteer):
   - Open each DocType
   - Check **"Track Changes"** in Settings tab
   - Save the DocType
5. **Validation:**
   - Make changes to member records
   - Verify Version history is created
   - Go to: **Setup > Document > Version** to view change history

## Post-Configuration Validation

### Security Test Execution

After implementing the security configurations above, validate the fixes by running the security test suite:

```bash
# Navigate to bench directory
cd /home/frappe/frappe-bench

# Run security tests
bench --site [your-site] run-tests --app verenigingen --module verenigingen.tests.backend.security.test_security_core

# Expected result: Improved security test results with fewer permission-related failures
```

### Manual Validation Checklist

- [ ] **Guest Access Test**: Log out and verify no access to member/financial data
- [ ] **Chapter Isolation Test**: Login as Chapter Manager and verify access limited to assigned chapter
- [ ] **Financial Data Test**: Verify non-financial users cannot access SEPA/payment data
- [ ] **Version Tracking Test**: Make member changes and verify Version documents are created
- [ ] **Permission Review**: Confirm User Permissions are properly configured for chapter isolation

## API Endpoints for Configuration Validation

The system provides API endpoints to help validate security configuration:

```javascript
// Get security configuration guide
frappe.call({
    method: "verenigingen.verenigingen.onboarding_step.verenigingen_configure_security.verenigingen_configure_security.get_security_configuration_guide",
    callback: function(r) {
        console.log(r.message); // Complete security checklist
    }
});

// Validate current security configuration
frappe.call({
    method: "verenigingen.verenigingen.onboarding_step.verenigingen_configure_security.verenigingen_configure_security.validate_security_configuration",
    callback: function(r) {
        console.log(r.message); // Issues found and recommendations
    }
});
```

## Ongoing Security Monitoring

### Regular Maintenance Tasks

1. **Weekly Permission Review**
   - Check User Permissions for chapter isolation
   - Review Role Permissions for any unauthorized changes
   - Validate Guest role has no sensitive data access

2. **Monthly Compliance Check**
   - Verify Version documents are being created for critical changes
   - Review audit trails for completeness
   - Test security configurations after system updates

3. **Quarterly Security Assessment**
   - Run complete security test suite
   - Review user access patterns
   - Update security configurations as needed

### Log Monitoring

Monitor the following in **Setup > System Console**:
- Failed permission attempts (indicates potential security issues)
- Unusual data access patterns
- Version document creation (confirms audit trails working)

## Emergency Response

### If Security Issues Are Discovered

1. **Immediate Actions:**
   - Document the issue and affected data
   - Temporarily restrict access if necessary
   - Check system logs for extent of exposure

2. **Investigation:**
   - Run security test suite to identify specific gaps
   - Review User Permissions and Role configurations
   - Check Version documents for unauthorized changes

3. **Remediation:**
   - Apply appropriate permission restrictions
   - Update security configurations per this guide
   - Re-test with security test suite
   - Document changes for audit purposes

## Support and Escalation

### Self-Service Resources

- **Security Test Suite**: Automated validation of security configurations
- **System Logs**: Setup > System Console for permission-related errors
- **Database Verification**: Use `bench --site [site] mariadb` to verify permission changes
- **Frappe Documentation**: Official Frappe Framework security documentation

### Configuration Verification Commands

```bash
# Check current user permissions
bench --site [site] console
>>> frappe.get_all("DocPerm", filters={"parent": "Member", "role": "Guest"})

# Verify version tracking is enabled
>>> frappe.get_single("System Settings").enable_version_control

# Check DocType tracking settings
>>> frappe.get_meta("Member").track_changes
```

## Conclusion

These security configurations are **mandatory** for production deployment of Verenigingen. The identified issues represent real security gaps that could lead to data breaches, regulatory non-compliance, and organizational data leakage.

**Implementation Priority:**
1. **Immediate (Critical)**: Guest access control and financial data isolation
2. **High (Within 24 hours)**: Document-level permission enforcement
3. **Medium (Within 1 week)**: Audit trail compliance

**Validation Requirement:** All security configurations must be validated through the security test suite before production deployment.

---

**Document Version:** 1.0
**Last Updated:** January 2025
**Review Schedule:** Quarterly or after major system updates
