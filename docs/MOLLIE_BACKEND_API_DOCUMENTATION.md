# API Documentation

This comprehensive guide covers the Verenigingen API endpoints, authentication, and integration patterns.

## Table of Contents
- [Overview](#overview)
- [Authentication](#authentication)
- [Core API Endpoints](#core-api-endpoints)
- [Member Management API](#member-management-api)
- [Payment and Financial API](#payment-and-financial-api)
- [eBoekhouden Integration API](#eboekhouden-integration-api)
- [Volunteer Management API](#volunteer-management-api)
- [Communication API](#communication-api)
- [Portal APIs](#portal-apis)
- [Integration Examples](#integration-examples)
- [Error Handling](#error-handling)
- [Rate Limiting](#rate-limiting)

## Overview

The Verenigingen app provides a comprehensive REST API built on the Frappe framework. All endpoints follow Frappe's API conventions and require proper authentication.

### Base URL Structure
```
https://your-site.com/api/method/verenigingen.api.[module].[function]
```

### API Capabilities
- **Member Management**: Complete lifecycle from application to termination with automated workflows
- **Payment Processing**: SEPA direct debit, mandate management, and ERPNext financial integration
- **eBoekhouden Integration**: Production-ready REST API integration for financial data synchronization
- **Volunteer Coordination**: Team assignments, expense management, and skills tracking
- **Portal Systems**: Member and volunteer self-service portals with brand customization
- **Communication**: Automated email templates and notification systems
- **Analytics & Reporting**: Real-time KPIs, cohort analysis, and business intelligence
- **Brand Management**: Dynamic theming with color preview and instant activation
- **System Administration**: Health monitoring, test framework, and migration tools
- **Geographic Organization**: Chapter management with postal code assignment
- **Termination Workflows**: Governance-compliant termination with audit trails
- **Banking Integration**: MT940 import, IBAN validation, and bank reconciliation

### Response Format
All API responses follow this standard format:
```json
{
  "message": {
    "success": true,
    "data": {
      "id": "record_id",
      "name": "Document Name",
      "details": {}
    },
    "error": null,
    "timestamp": "2025-01-21T10:30:00Z",
    "version": "1.0"
  }
}
```

### Error Response Format
Error responses include detailed information for debugging:
```json
{
  "exc_type": "ValidationError",
  "message": "Detailed error description",
  "exception": "Full stack trace (in debug mode)"
}
```

## Authentication

### API Key Authentication (Recommended)

1. **Generate API Keys**:
   - Go to **Users and Permissions → User**
   - Select user account
   - Click "Generate Keys" in API Access section

2. **API Request Headers**:
   ```http
   Authorization: token api_key:api_secret
   Content-Type: application/json
   ```

### Session-Based Authentication

For browser-based applications:
```javascript
// Login to create session
fetch('/api/method/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    usr: 'user@example.com',
    pwd: 'password'
  })
});
```

## Core API Endpoints

### Member Management API

#### Get Member Information
```http
GET /api/method/verenigingen.api.member_management.get_member_info
```

**Parameters**:
- `member_id` (string): Member ID or email address
- `include_payments` (boolean): Include payment history
- `include_volunteer` (boolean): Include volunteer information

**Example Request**:
```bash
curl -X GET "https://your-site.com/api/method/verenigingen.api.member_management.get_member_info" \
  -H "Authorization: token your_api_key:your_api_secret" \
  -d "member_id=MEMBER001&include_payments=true"
```

**Example Response**:
```json
{
  "message": {
    "success": true,
    "data": {
      "member_id": "MEMBER001",
      "name": "John Doe",
      "email": "john@example.com",
      "status": "Active",
      "membership_type": "Individual",
      "chapter": "Amsterdam",
      "join_date": "2023-01-15",
      "payments": [
        {
          "date": "2024-01-01",
          "amount": 25.00,
          "status": "Paid",
          "method": "SEPA"
        }
      ]
    }
  }
}
```

#### Create New Member
```http
POST /api/method/verenigingen.api.member_management.create_member
```

**Request Body**:
```json
{
  "first_name": "Jane",
  "last_name": "Smith",
  "email": "jane@example.com",
  "phone": "+31612345678",
  "address": {
    "street": "Damrak 1",
    "city": "Amsterdam",
    "postal_code": "1012LG",
    "country": "Netherlands"
  },
  "membership_type": "Individual",
  "fee_amount": 25.00
}
```

#### Update Member Information
```http
PUT /api/method/verenigingen.api.member_management.update_member
```

**Parameters**:
- `member_id` (string, required): Member to update
- `data` (object): Fields to update

### Membership Application API

#### Submit New Application
```http
POST /api/method/verenigingen.api.membership_application.submit_application
```

**Request Body**:
```json
{
  "applicant": {
    "first_name": "John",
    "last_name": "Doe",
    "email": "john@example.com",
    "phone": "+31612345678",
    "birth_date": "1990-01-01"
  },
  "address": {
    "street": "Damrak 1",
    "city": "Amsterdam",
    "postal_code": "1012LG"
  },
  "membership_type": "Individual",
  "payment_method": "sepa",
  "iban": "NL91ABNA0417164300"
}
```

#### Get Application Status
```http
GET /api/method/verenigingen.api.membership_application.get_application_status
```

**Parameters**:
- `application_id` (string): Application reference number
- `email` (string): Applicant email address

## Payment and Financial API

### SEPA Mandate Management

#### Create SEPA Mandate
```http
POST /api/method/verenigingen.api.sepa_mandate_fix.create_sepa_mandate
```

**Request Body**:
```json
{
  "member_id": "MEMBER001",
  "iban": "NL91ABNA0417164300",
  "account_holder": "John Doe",
  "mandate_type": "RCUR"
}
```

#### Validate IBAN
```http
GET /api/method/verenigingen.utils.iban_validator.validate_iban
```

**Parameters**:
- `iban` (string): IBAN to validate

**Example Response**:
```json
{
  "message": {
    "valid": true,
    "iban": "NL91ABNA0417164300",
    "bank": "ABN AMRO",
    "bic": "ABNANL2A",
    "country": "Netherlands"
  }
}
```

### Payment Processing

#### Process Payment
```http
POST /api/method/verenigingen.api.payment_processing.process_payment
```

**Request Body**:
```json
{
  "member_id": "MEMBER001",
  "amount": 25.00,
  "payment_method": "sepa",
  "description": "Annual membership fee",
  "due_date": "2024-12-31"
}
```

#### Get Payment History
```http
GET /api/method/verenigingen.api.payment_processing.get_payment_history
```

**Parameters**:
- `member_id` (string): Member ID
- `from_date` (date): Start date filter
- `to_date` (date): End date filter
- `status` (string): Payment status filter

### Direct Debit Batch Management

#### Create SEPA Batch
```http
POST /api/method/verenigingen.api.dd_batch_scheduler.create_dd_batch
```

**Request Body**:
```json
{
  "execution_date": "2024-12-31",
  "batch_type": "membership_fees",
  "include_member_types": ["Individual", "Student"],
  "exclude_suspended": true
}
```

## eBoekhouden Integration API

The eBoekhouden integration provides comprehensive accounting system synchronization using REST API architecture. This enables complete financial data management and compliance with Dutch accounting standards.

> **📖 Detailed Guide**: For complete implementation details, see [eBoekhouden API Integration Guide](api/EBOEKHOUDEN_API_GUIDE.md)

### Migration Management

#### Start Complete Migration
```http
POST /api/method/verenigingen.utils.eboekhouden_rest_full_migration.start_full_rest_import
```

**Request Body**:
```json
{
  "migration_name": "eBoekhouden Migration 2025-01-07"
}
```

**Example Response**:
```json
{
  "message": {
    "success": true,
    "migration_id": "MIGRATE-2025-001",
    "status": "Started",
    "estimated_transactions": 7163,
    "start_time": "2025-01-07 10:00:00"
  }
}
```

#### Test Opening Balance Import
```http
GET /api/method/verenigingen.utils.eboekhouden_rest_full_migration.test_opening_balance_import
```

**Example Response**:
```json
{
  "message": {
    "success": true,
    "imported": 1,
    "total_amount": "324062.12",
    "account_entries": 22,
    "journal_entry": "EBH-Opening-Balance"
  }
}
```

#### Get Migration Progress
```http
GET /api/method/verenigingen.utils.eboekhouden_rest_full_migration.get_migration_status
```

**Parameters**:
- `migration_id` (string): Migration identifier

**Example Response**:
```json
{
  "message": {
    "migration_id": "MIGRATE-2025-001",
    "status": "In Progress",
    "progress": {
      "total_mutations": 7163,
      "processed": 1250,
      "successful": 1200,
      "failed": 50,
      "percentage": 17.4
    },
    "current_operation": "Processing mutation 1251: ID=4550, Type=3",
    "errors": [
      "Failed to import mutation 3746: Zero amount invoice",
      "Skipped mutation 1256: Zero amount journal entry"
    ]
  }
}
```

### Data Analysis and Validation

#### Analyze Missing Mappings
```http
GET /api/method/verenigingen.utils.eboekhouden_rest_full_migration.analyze_missing_ledger_mappings
```

**Example Response**:
```json
{
  "message": {
    "total_unmapped": 15,
    "missing_mappings": [
      {
        "ledger_id": "42308",
        "usage_count": 25,
        "description": "Bijeenkomsten: deelnemersbijdragen"
      }
    ],
    "impact_analysis": {
      "affected_transactions": 250,
      "total_amount": "15420.50"
    }
  }
}
```

#### Export Unprocessed Data
```http
POST /api/method/verenigingen.utils.eboekhouden_rest_full_migration.export_unprocessed_mutations
```

**Request Body**:
```json
{
  "export_path": "/tmp/unprocessed_mutations.json",
  "format": "json"
}
```

### API Connectivity Testing

#### Test REST API Connection
```http
GET /api/method/verenigingen.utils.eboekhouden_rest_iterator.test_rest_iterator
```

**Example Response**:
```json
{
  "message": {
    "success": true,
    "api_status": "Connected",
    "mutations_found": {
      "100": "Found - Type: 2, Date: 2024-03-15",
      "500": "Found - Type: 1, Date: 2024-04-20"
    },
    "session_token": "Valid",
    "estimated_range": "1 to 7420"
  }
}
```

#### Estimate Data Range
```http
GET /api/method/verenigingen.utils.eboekhouden_rest_iterator.estimate_mutation_range
```

**Example Response**:
```json
{
  "message": {
    "success": true,
    "lowest_id": 0,
    "highest_id": 7420,
    "estimated_count": 7421,
    "includes_opening_balance": true
  }
}
```

### Cache Management

#### Get Cache Statistics
```http
GET /api/method/verenigingen.utils.eboekhouden_rest_full_migration.get_cache_statistics
```

**Example Response**:
```json
{
  "message": {
    "total_cached_mutations": 5000,
    "cache_size_mb": 45.2,
    "oldest_entry": "2024-01-01",
    "newest_entry": "2024-12-31",
    "hit_rate": "85.6%"
  }
}
```

#### Clear Cache
```http
DELETE /api/method/verenigingen.utils.eboekhouden_rest_full_migration.clear_cache
```

### Account Management

#### Create Account Mapping
```http
POST /api/method/verenigingen.api.eboekhouden_account_manager.create_account_mapping
```

**Request Body**:
```json
{
  "eboekhouden_code": "42308",
  "erpnext_account": "42308 - Bijeenkomsten: deelnemersbijdragen - NVV",
  "account_type": "Expense Account",
  "description": "Event participation fees"
}
```

#### Validate Account Structure
```http
GET /api/method/verenigingen.api.eboekhouden_account_manager.validate_account_structure
```

**Example Response**:
```json
{
  "message": {
    "valid": true,
    "chart_of_accounts": {
      "total_accounts": 156,
      "mapped_accounts": 141,
      "unmapped_accounts": 15
    },
    "validation_errors": [],
    "recommendations": [
      "Create mapping for account 42308",
      "Review account hierarchy for group 19000"
    ]
  }
}
```

### Document Processing

#### Process Single Transaction
```http
POST /api/method/verenigingen.utils.eboekhouden_rest_full_migration.process_single_mutation
```

**Request Body**:
```json
{
  "mutation_id": 4550,
  "force_reprocess": false,
  "validation_mode": false
}
```

**Example Response**:
```json
{
  "message": {
    "success": true,
    "mutation_id": 4550,
    "document_created": "EBH-Payment-4550",
    "document_type": "Journal Entry",
    "amount": 150.00,
    "party": "Customer ABC",
    "balanced": true
  }
}
```

### System Health

#### Health Check
```http
GET /api/method/verenigingen.api.eboekhouden_account_manager.system_health_check
```

**Example Response**:
```json
{
  "message": {
    "overall_status": "Healthy",
    "api_connectivity": "Connected",
    "database_integrity": "Valid",
    "mapping_coverage": "90.4%",
    "balance_accuracy": "99.8%",
    "last_import": "2025-01-07 09:30:00",
    "recommendations": [
      "Update 15 missing account mappings",
      "Review 3 balance discrepancies"
    ]
  }
}
```

### Error Handling for eBoekhouden API

The eBoekhouden integration includes comprehensive error handling:

```json
{
  "message": {
    "success": false,
    "error": "API_CONNECTION_FAILED",
    "details": {
      "error_code": "AUTH_001",
      "description": "Invalid API credentials",
      "resolution": "Check eBoekhouden Settings and verify API token",
      "retry_possible": true
    }
  }
}
```

**Common Error Codes**:
- `AUTH_001`: Invalid API credentials
- `MAPPING_002`: Missing account mapping
- `VALIDATION_003`: Document validation failed
- `BALANCE_004`: Transaction balance mismatch
- `NETWORK_005`: API connectivity issues

## Volunteer Management API

### Volunteer Information

#### Get Volunteer Profile
```http
GET /api/method/verenigingen.api.volunteer_api.get_volunteer_profile
```

**Parameters**:
- `volunteer_id` (string): Volunteer ID or member email
- `include_assignments` (boolean): Include team assignments
- `include_expenses` (boolean): Include expense history

#### Update Volunteer Availability
```http
PUT /api/method/verenigingen.api.volunteer_api.update_availability
```

**Request Body**:
```json
{
  "volunteer_id": "VOL001",
  "availability": {
    "monday": {"start": "09:00", "end": "17:00"},
    "tuesday": {"start": "09:00", "end": "17:00"},
    "weekend": false
  },
  "preferred_activities": ["fundraising", "events"],
  "skills": ["marketing", "social_media", "event_planning"]
}
```

### Team Management

#### Get Team Information
```http
GET /api/method/verenigingen.api.volunteer_api.get_team_info
```

**Parameters**:
- `team_id` (string): Team identifier
- `include_members` (boolean): Include team member details

#### Assign Volunteer to Team
```http
POST /api/method/verenigingen.api.volunteer_api.assign_to_team
```

**Request Body**:
```json
{
  "volunteer_id": "VOL001",
  "team_id": "TEAM001",
  "role": "Member",
  "start_date": "2024-01-01",
  "responsibilities": ["Social media management", "Event coordination"]
}
```

### Expense Management

#### Submit Volunteer Expense
```http
POST /api/method/verenigingen.api.volunteer_api.submit_expense
```

**Request Body**:
```json
{
  "volunteer_id": "VOL001",
  "team_id": "TEAM001",
  "expense_type": "Travel",
  "amount": 15.50,
  "description": "Train ticket to volunteer event",
  "expense_date": "2024-01-15",
  "receipt_attachment": "base64_encoded_image"
}
```

## Communication API

### Email Management

#### Send Email Template
```http
POST /api/method/verenigingen.api.email_template_manager.send_template_email
```

**Request Body**:
```json
{
  "template_name": "membership_welcome",
  "recipient": "new_member@example.com",
  "context": {
    "member_name": "John Doe",
    "membership_type": "Individual",
    "member_id": "MEMBER001"
  }
}
```

#### Create Email Template
```http
POST /api/method/verenigingen.api.email_template_manager.create_template
```

**Request Body**:
```json
{
  "template_name": "custom_notification",
  "subject": "Important Update - {{ member_name }}",
  "message": "Dear {{ member_name }}, we have an important update...",
  "template_type": "notification"
}
```

### Notification Management

#### Send System Notification
```http
POST /api/method/verenigingen.api.communication.send_notification
```

**Request Body**:
```json
{
  "recipients": ["user1@example.com", "user2@example.com"],
  "subject": "System Maintenance Notice",
  "message": "The system will be under maintenance...",
  "notification_type": "system_alert",
  "priority": "high"
}
```

## Chapter Management API

### Chapter Information

#### Get Chapter Details
```http
GET /api/method/verenigingen.api.chapter_dashboard_api.get_chapter_info
```

**Parameters**:
- `chapter_id` (string): Chapter identifier
- `include_members` (boolean): Include member count and details
- `include_activities` (boolean): Include recent activities

#### Get Chapters by Postal Code
```http
GET /api/method/verenigingen.api.get_user_chapters.get_chapters_by_postal_code
```

**Parameters**:
- `postal_code` (string): Dutch postal code (e.g., "1012LG")

**Example Response**:
```json
{
  "message": {
    "chapters": [
      {
        "name": "Amsterdam",
        "chapter_id": "AMS001",
        "coverage_area": "Amsterdam city center",
        "contact_email": "amsterdam@example.org"
      }
    ]
  }
}
```

## System Administration API

### Brand Management

#### Update Brand Settings
```http
POST /api/method/verenigingen.api.brand_management.update_brand_settings
```

**Request Body**:
```json
{
  "primary_color": "#cf3131",
  "secondary_color": "#01796f",
  "accent_color": "#663399",
  "success_color": "#28a745",
  "warning_color": "#ffc107",
  "error_color": "#dc3545"
}
```

#### Generate Brand CSS
```http
GET /api/method/verenigingen.templates.pages.brand_css.get_brand_css
```

### Analytics and Reporting

#### Get Membership Analytics
```http
GET /api/method/verenigingen.api.member_management.get_membership_analytics
```

**Parameters**:
- `date_range` (string): "last_month", "last_quarter", "last_year"
- `group_by` (string): "membership_type", "chapter", "age_group"
- `include_trends` (boolean): Include trend analysis

**Example Response**:
```json
{
  "message": {
    "total_members": 1250,
    "new_members_this_month": 45,
    "retention_rate": 89.5,
    "revenue_this_month": 31250.00,
    "by_membership_type": {
      "Individual": 800,
      "Student": 300,
      "Senior": 150
    },
    "trends": {
      "growth_rate": 5.2,
      "churn_rate": 2.1
    }
  }
}
```

## Integration Examples

### JavaScript/Node.js Example

```javascript
class VerenigingenAPI {
  constructor(baseUrl, apiKey, apiSecret) {
    this.baseUrl = baseUrl;
    this.auth = Buffer.from(`${apiKey}:${apiSecret}`).toString('base64');
  }

  async getMemberInfo(memberId) {
    const response = await fetch(
      `${this.baseUrl}/api/method/verenigingen.api.member_management.get_member_info`,
      {
        method: 'POST',
        headers: {
          'Authorization': `token ${this.auth}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ member_id: memberId })
      }
    );

    return response.json();
  }

  async createMember(memberData) {
    const response = await fetch(
      `${this.baseUrl}/api/method/verenigingen.api.member_management.create_member`,
      {
        method: 'POST',
        headers: {
          'Authorization': `token ${this.auth}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(memberData)
      }
    );

    return response.json();
  }
}

// Usage
const api = new VerenigingenAPI('https://your-site.com', 'api_key', 'api_secret');
const member = await api.getMemberInfo('MEMBER001');
```

### Python Example

```python
import requests
import base64
import json

class VerenigingenAPI:
    def __init__(self, base_url, api_key, api_secret):
        self.base_url = base_url
        self.auth_header = {
            'Authorization': f'token {api_key}:{api_secret}',
            'Content-Type': 'application/json'
        }

    def get_member_info(self, member_id):
        url = f"{self.base_url}/api/method/verenigingen.api.member_management.get_member_info"
        data = {'member_id': member_id}

        response = requests.post(url, headers=self.auth_header, json=data)
        return response.json()

    def create_sepa_mandate(self, member_id, iban):
        url = f"{self.base_url}/api/method/verenigingen.api.sepa_mandate_fix.create_sepa_mandate"
        data = {
            'member_id': member_id,
            'iban': iban,
            'mandate_type': 'RCUR'
        }

        response = requests.post(url, headers=self.auth_header, json=data)
        return response.json()

# Usage
api = VerenigingenAPI('https://your-site.com', 'api_key', 'api_secret')
member = api.get_member_info('MEMBER001')
```

### PHP Example

```php
<?php
class VerenigingenAPI {
    private $baseUrl;
    private $authHeader;

    public function __construct($baseUrl, $apiKey, $apiSecret) {
        $this->baseUrl = $baseUrl;
        $this->authHeader = [
            'Authorization: token ' . $apiKey . ':' . $apiSecret,
            'Content-Type: application/json'
        ];
    }

    public function getMemberInfo($memberId) {
        $url = $this->baseUrl . '/api/method/verenigingen.api.member_management.get_member_info';
        $data = json_encode(['member_id' => $memberId]);

        $ch = curl_init();
        curl_setopt($ch, CURLOPT_URL, $url);
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_POSTFIELDS, $data);
        curl_setopt($ch, CURLOPT_HTTPHEADER, $this->authHeader);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);

        $response = curl_exec($ch);
        curl_close($ch);

        return json_decode($response, true);
    }
}

// Usage
$api = new VerenigingenAPI('https://your-site.com', 'api_key', 'api_secret');
$member = $api->getMemberInfo('MEMBER001');
?>
```

## Error Handling

### Standard Error Response Format

```json
{
  "message": {
    "success": false,
    "error": {
      "code": "VALIDATION_ERROR",
      "message": "Required field 'email' is missing",
      "details": {
        "field": "email",
        "type": "required"
      }
    }
  }
}
```

### Common Error Codes

- **AUTHENTICATION_ERROR**: Invalid API credentials
- **PERMISSION_DENIED**: Insufficient permissions for operation
- **VALIDATION_ERROR**: Input validation failed
- **NOT_FOUND**: Requested resource not found
- **DUPLICATE_ENTRY**: Attempt to create duplicate record
- **PAYMENT_ERROR**: Payment processing failed
- **SEPA_ERROR**: SEPA mandate or direct debit error
- **SYSTEM_ERROR**: Internal system error

### HTTP Status Codes

- **200**: Success
- **400**: Bad Request (validation error)
- **401**: Unauthorized (authentication error)
- **403**: Forbidden (permission denied)
- **404**: Not Found
- **409**: Conflict (duplicate entry)
- **500**: Internal Server Error

## Rate Limiting

### Default Limits
- **Authenticated requests**: 1000 requests per hour per user
- **Anonymous requests**: 100 requests per hour per IP
- **Bulk operations**: 10 requests per minute per user

### Rate Limit Headers
```http
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 999
X-RateLimit-Reset: 1640995200
```

### Handling Rate Limits
When rate limits are exceeded, the API returns HTTP 429 with:
```json
{
  "message": {
    "success": false,
    "error": {
      "code": "RATE_LIMIT_EXCEEDED",
      "message": "Rate limit exceeded. Try again later.",
      "retry_after": 3600
    }
  }
}
```

## Best Practices

### API Usage Guidelines

1. **Authentication Security**:
   - Store API credentials securely
   - Use HTTPS for all API calls
   - Rotate API keys regularly
   - Implement proper error handling

2. **Request Optimization**:
   - Use appropriate HTTP methods (GET, POST, PUT, DELETE)
   - Batch requests when possible
   - Implement exponential backoff for retries
   - Cache responses when appropriate

3. **Data Handling**:
   - Validate input data before sending
   - Handle partial failures gracefully
   - Implement idempotency for critical operations
   - Use pagination for large datasets

4. **Error Handling**:
   - Check response status codes
   - Parse error messages appropriately
   - Implement retry logic for transient errors
   - Log errors for debugging

### Integration Patterns

1. **Webhook Integration**: Set up webhooks for real-time notifications
2. **Batch Processing**: Use bulk operations for large data sets
3. **Synchronization**: Implement proper sync strategies for data consistency
4. **Monitoring**: Track API usage and performance metrics

---

This API documentation provides comprehensive information for integrating with the Verenigingen system. For specific implementation questions or additional endpoints, refer to the source code or contact the development team.
