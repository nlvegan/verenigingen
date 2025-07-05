# Required DocTypes for DD Security Enhancement

## 1. DD Security Audit Log

**Purpose**: Comprehensive audit logging for all SEPA Direct Debit batch operations

**Fields**:
```json
{
  "doctype": "DocType",
  "name": "DD Security Audit Log",
  "naming_rule": "Expression (old style)",
  "autoname": "format:DDAUDIT-{YYYY}-{MM}-{#####}",
  "fields": [
    {
      "fieldname": "timestamp",
      "fieldtype": "Datetime",
      "label": "Timestamp",
      "reqd": 1,
      "default": "Now"
    },
    {
      "fieldname": "action",
      "fieldtype": "Data",
      "label": "Action",
      "reqd": 1,
      "length": 200
    },
    {
      "fieldname": "batch_id",
      "fieldtype": "Data",
      "label": "Batch ID",
      "length": 200
    },
    {
      "fieldname": "user",
      "fieldtype": "Link",
      "label": "User",
      "options": "User",
      "reqd": 1
    },
    {
      "fieldname": "ip_address",
      "fieldtype": "Data",
      "label": "IP Address",
      "length": 45
    },
    {
      "fieldname": "user_agent",
      "fieldtype": "Text",
      "label": "User Agent"
    },
    {
      "fieldname": "session_id",
      "fieldtype": "Data",
      "label": "Session ID",
      "length": 200
    },
    {
      "fieldname": "details",
      "fieldtype": "Long Text",
      "label": "Details (JSON)"
    },
    {
      "fieldname": "risk_level",
      "fieldtype": "Select",
      "label": "Risk Level",
      "options": "Low\nMedium\nHigh\nCritical",
      "default": "Low"
    }
  ],
  "permissions": [
    {
      "role": "System Manager",
      "read": 1,
      "create": 1
    },
    {
      "role": "DD Administrator",
      "read": 1,
      "create": 1
    }
  ],
  "sort_field": "timestamp",
  "sort_order": "DESC"
}
```

## 2. DD Security Event Log

**Purpose**: Security-specific event logging (fraud detection, access violations, etc.)

**Fields**:
```json
{
  "doctype": "DocType",
  "name": "DD Security Event Log",
  "naming_rule": "Expression (old style)",
  "autoname": "format:DDSEC-{YYYY}-{MM}-{#####}",
  "fields": [
    {
      "fieldname": "timestamp",
      "fieldtype": "Datetime",
      "label": "Timestamp",
      "reqd": 1,
      "default": "Now"
    },
    {
      "fieldname": "event_type",
      "fieldtype": "Select",
      "label": "Event Type",
      "options": "Authentication Failure\nUnauthorized Access\nFraud Detection\nData Breach\nSuspicious Activity\nSystem Anomaly\nConfiguration Change\nPermission Violation",
      "reqd": 1
    },
    {
      "fieldname": "severity",
      "fieldtype": "Select",
      "label": "Severity",
      "options": "Low\nMedium\nHigh\nCritical",
      "reqd": 1
    },
    {
      "fieldname": "description",
      "fieldtype": "Text",
      "label": "Description",
      "reqd": 1
    },
    {
      "fieldname": "user",
      "fieldtype": "Link",
      "label": "User",
      "options": "User"
    },
    {
      "fieldname": "ip_address",
      "fieldtype": "Data",
      "label": "IP Address",
      "length": 45
    },
    {
      "fieldname": "details",
      "fieldtype": "Long Text",
      "label": "Details (JSON)"
    },
    {
      "fieldname": "resolved",
      "fieldtype": "Check",
      "label": "Resolved",
      "default": 0
    },
    {
      "fieldname": "resolution_notes",
      "fieldtype": "Text",
      "label": "Resolution Notes"
    },
    {
      "fieldname": "resolved_by",
      "fieldtype": "Link",
      "label": "Resolved By",
      "options": "User"
    },
    {
      "fieldname": "resolved_date",
      "fieldtype": "Datetime",
      "label": "Resolved Date"
    }
  ],
  "permissions": [
    {
      "role": "System Manager",
      "read": 1,
      "write": 1,
      "create": 1
    },
    {
      "role": "DD Administrator",
      "read": 1,
      "write": 1,
      "create": 1
    },
    {
      "role": "Security Officer",
      "read": 1,
      "write": 1
    }
  ],
  "sort_field": "timestamp",
  "sort_order": "DESC"
}
```

## 3. DD Conflict Report

**Purpose**: Track and manage member identity conflicts and resolutions

**Fields**:
```json
{
  "doctype": "DocType",
  "name": "DD Conflict Report",
  "naming_rule": "Expression (old style)",
  "autoname": "format:DDCONF-{YYYY}-{MM}-{#####}",
  "fields": [
    {
      "fieldname": "batch_id",
      "fieldtype": "Data",
      "label": "Batch ID",
      "length": 200
    },
    {
      "fieldname": "report_date",
      "fieldtype": "Date",
      "label": "Report Date",
      "reqd": 1,
      "default": "Today"
    },
    {
      "fieldname": "conflict_data",
      "fieldtype": "Long Text",
      "label": "Conflict Data (JSON)",
      "reqd": 1
    },
    {
      "fieldname": "summary",
      "fieldtype": "Text",
      "label": "Summary",
      "reqd": 1
    },
    {
      "fieldname": "status",
      "fieldtype": "Select",
      "label": "Status",
      "options": "Open\nUnder Review\nResolved\nEscalated\nClosed",
      "default": "Open",
      "reqd": 1
    },
    {
      "fieldname": "priority",
      "fieldtype": "Select",
      "label": "Priority",
      "options": "Low\nMedium\nHigh\nUrgent",
      "default": "Medium"
    },
    {
      "fieldname": "created_by",
      "fieldtype": "Link",
      "label": "Created By",
      "options": "User",
      "reqd": 1
    },
    {
      "fieldname": "assigned_to",
      "fieldtype": "Link",
      "label": "Assigned To",
      "options": "User"
    },
    {
      "fieldname": "resolution_details",
      "fieldtype": "Text",
      "label": "Resolution Details"
    },
    {
      "fieldname": "resolved_by",
      "fieldtype": "Link",
      "label": "Resolved By",
      "options": "User"
    },
    {
      "fieldname": "resolved_date",
      "fieldtype": "Datetime",
      "label": "Resolved Date"
    },
    {
      "fieldname": "escalation_reason",
      "fieldtype": "Text",
      "label": "Escalation Reason"
    },
    {
      "fieldname": "duplicate_members",
      "fieldtype": "Table",
      "label": "Duplicate Members",
      "options": "DD Conflict Member"
    }
  ],
  "permissions": [
    {
      "role": "System Manager",
      "read": 1,
      "write": 1,
      "create": 1,
      "delete": 1
    },
    {
      "role": "DD Administrator",
      "read": 1,
      "write": 1,
      "create": 1
    },
    {
      "role": "Membership Manager",
      "read": 1,
      "write": 1
    }
  ],
  "sort_field": "creation",
  "sort_order": "DESC"
}
```

## 4. DD Conflict Member (Child Table)

**Purpose**: Store individual member details in conflict reports

**Fields**:
```json
{
  "doctype": "DocType",
  "name": "DD Conflict Member",
  "istable": 1,
  "fields": [
    {
      "fieldname": "member_id",
      "fieldtype": "Link",
      "label": "Member",
      "options": "Member"
    },
    {
      "fieldname": "member_name",
      "fieldtype": "Data",
      "label": "Member Name",
      "reqd": 1,
      "length": 200
    },
    {
      "fieldname": "email",
      "fieldtype": "Data",
      "label": "Email",
      "length": 200
    },
    {
      "fieldname": "iban",
      "fieldtype": "Data",
      "label": "IBAN",
      "length": 50
    },
    {
      "fieldname": "risk_score",
      "fieldtype": "Float",
      "label": "Risk Score",
      "precision": 3
    },
    {
      "fieldname": "conflict_type",
      "fieldtype": "Select",
      "label": "Conflict Type",
      "options": "Name Similarity\nEmail Similarity\nIBAN Match\nAddress Match\nPhone Match"
    },
    {
      "fieldname": "resolution_action",
      "fieldtype": "Select",
      "label": "Resolution Action",
      "options": "Proceed\nMerge\nExclude\nEscalate\nPending"
    },
    {
      "fieldname": "notes",
      "fieldtype": "Text",
      "label": "Notes"
    }
  ]
}
```

## 5. Enhanced SEPA Direct Debit Batch Fields

**Additional fields to add to existing SEPA Direct Debit Batch DocType**:

```json
{
  "additional_fields": [
    {
      "fieldname": "security_section",
      "fieldtype": "Section Break",
      "label": "Security & Validation"
    },
    {
      "fieldname": "risk_assessment",
      "fieldtype": "Select",
      "label": "Risk Assessment",
      "options": "Low\nMedium\nHigh\nCritical",
      "default": "Low",
      "read_only": 1
    },
    {
      "fieldname": "duplicate_checks_performed",
      "fieldtype": "Check",
      "label": "Duplicate Checks Performed",
      "default": 0,
      "read_only": 1
    },
    {
      "fieldname": "conflicts_detected",
      "fieldtype": "Int",
      "label": "Conflicts Detected",
      "default": 0,
      "read_only": 1
    },
    {
      "fieldname": "conflicts_resolved",
      "fieldtype": "Int",
      "label": "Conflicts Resolved",
      "default": 0,
      "read_only": 1
    },
    {
      "fieldname": "security_approval_required",
      "fieldtype": "Check",
      "label": "Security Approval Required",
      "default": 0
    },
    {
      "fieldname": "security_approved_by",
      "fieldtype": "Link",
      "label": "Security Approved By",
      "options": "User"
    },
    {
      "fieldname": "security_approval_date",
      "fieldtype": "Datetime",
      "label": "Security Approval Date"
    },
    {
      "fieldname": "anomaly_detection_results",
      "fieldtype": "Long Text",
      "label": "Anomaly Detection Results (JSON)"
    },
    {
      "fieldname": "validation_warnings",
      "fieldtype": "Text",
      "label": "Validation Warnings"
    }
  ]
}
```

## 6. Role Definitions

**New Roles Required**:

1. **DD Administrator**
   - Full access to SEPA Direct Debit batch management
   - Can resolve conflicts and approve high-risk batches
   - Access to security logs and audit trails

2. **Security Officer**
   - Read access to security event logs
   - Can investigate and resolve security incidents
   - Cannot create or modify DD batches

3. **DD Operator**
   - Can create and manage routine DD batches
   - Limited access to low-risk operations only
   - Cannot resolve conflicts or access security logs

**Permission Structure**:
```json
{
  "DD Administrator": {
    "SEPA Direct Debit Batch": "all",
    "DD Security Audit Log": "read,create",
    "DD Security Event Log": "read,write,create",
    "DD Conflict Report": "all",
    "Member": "read,write"
  },
  "Security Officer": {
    "DD Security Event Log": "read,write",
    "DD Security Audit Log": "read",
    "DD Conflict Report": "read"
  },
  "DD Operator": {
    "SEPA Direct Debit Batch": "read,write,create (if risk_assessment='Low')",
    "DD Conflict Report": "read"
  }
}
```

## 7. Custom Scripts and Hooks

**Required Hooks in hooks.py**:
```python
# Scheduled tasks for security monitoring
scheduler_events = {
    "hourly": [
        "verenigingen.utils.dd_security_enhancements.monitor_security_events"
    ],
    "daily": [
        "verenigingen.utils.dd_security_enhancements.generate_security_report",
        "verenigingen.utils.dd_security_enhancements.cleanup_old_logs"
    ]
}

# Document events for audit logging
doc_events = {
    "SEPA Direct Debit Batch": {
        "before_save": "verenigingen.utils.dd_security_enhancements.log_batch_changes",
        "on_submit": "verenigingen.utils.dd_security_enhancements.log_batch_submission",
        "on_cancel": "verenigingen.utils.dd_security_enhancements.log_batch_cancellation"
    }
}
```

## Implementation Priority

1. **Phase 1** (Week 1): Create DD Security Audit Log and DD Security Event Log
2. **Phase 2** (Week 2): Create DD Conflict Report and DD Conflict Member
3. **Phase 3** (Week 3): Enhance SEPA Direct Debit Batch with security fields
4. **Phase 4** (Week 4): Implement roles and permissions

This enhanced DocType structure provides comprehensive security monitoring, audit trails, and conflict resolution capabilities for the SEPA Direct Debit batch system while maintaining compliance with financial data protection standards.
