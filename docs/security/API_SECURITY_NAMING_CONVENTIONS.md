# API Security Framework Naming Conventions

This document describes the naming conventions expected by the API Security Framework for Critical Operation Rules.

## Overview

The API Security Framework automatically looks up Critical Operation Rules by trying multiple naming patterns for each function. Understanding these patterns is essential for proper security configuration.

## Operation Name Lookup Pattern

When a function decorated with `@critical_api` is called, the framework attempts to find a matching Critical Operation Rule by testing these operation names in order:

1. **Exact function name**: `function_name`
2. **Module-prefixed name**: `module_name_function_name`
3. **API-prefixed name**: `api_function_name`

### Example Lookup Sequence

For a function `get_address_members_html` in module `verenigingen.utils.member_management`:

1. Try: `get_address_members_html`
2. Try: `member_management_get_address_members_html`
3. Try: `api_get_address_members_html`

## Critical Operation Rule Fixture Requirements

In `/fixtures/critical_operation_rule.json`, you need entries for the names that will actually be found:

```json
{
  "doctype": "Critical Operation Rule",
  "name": "member_management_get_address_members_html_api",
  "operation_name": "member_management_get_address_members_html_api",
  "operation_type": "READ",
  "security_level": "low",
  "required_roles": "System Manager\nVerenigingen Manager\nVerenigingen Staff"
}
```

## Common Naming Patterns

### Utility Functions
- Base name: `function_name`
- Expected match: `module_name_function_name`

### API Endpoints
- Base name: `api_function_name`
- Expected match: `api_function_name` or `module_name_api_function_name`

### Member Management Functions
- Base name: `get_member_data`
- Expected match: `member_management_get_member_data`

## Module Name Extraction

The framework extracts module names using `module_name.split('.')[-1]`:

- `verenigingen.utils.member_management` → `member_management`
- `verenigingen.services.customer_service` → `customer_service`
- `verenigingen.hooks.member_hooks` → `member_hooks`

## Debugging Missing Rules

When operation rules aren't found, the framework logs:

```
Critical Operation Rule lookup failed for function 'get_address_members_html' from module 'verenigingen.utils.member_management'.
Tried operation names: ['get_address_members_html', 'member_management_get_address_members_html', 'api_get_address_members_html'].
This indicates either missing Critical Operation Rule fixture data or incorrect naming conventions.
```

## Best Practices

1. **Create rules for the most specific name** that will be found (usually module-prefixed)
2. **Use consistent module naming** in fixture files
3. **Test rule lookup** after adding new `@critical_api` decorated functions
4. **Check logs** for failed lookups during development

## Security Level Mapping

Ensure security levels match the operation type:

- **PUBLIC**: `security_level: "public"` - No authentication required
- **UTILITY**: `security_level: "low"` - Basic role verification
- **MEMBER_DATA**: `security_level: "medium"` - Member data access
- **FINANCIAL**: `security_level: "high"` - Financial operations
- **ADMINISTRATIVE**: `security_level: "critical"` - System administration

## Common Issues

### Missing Prefixed Names
- **Problem**: Function works locally but fails in production
- **Cause**: Missing module-prefixed operation rule name
- **Solution**: Add the prefixed version to fixtures

### Wrong Security Level
- **Problem**: Access denied for authorized users
- **Cause**: Security level too high for operation type
- **Solution**: Review operation classification and adjust security level

### Module Name Mismatch
- **Problem**: Rule exists but not found
- **Cause**: Module path changed but fixture not updated
- **Solution**: Update operation_name in fixture to match current module structure
