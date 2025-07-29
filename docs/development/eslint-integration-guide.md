# ESLint Integration Guide for Verenigingen

This guide covers the comprehensive ESLint integration for the Verenigingen JavaScript codebase, including setup, usage, and best practices.

## Overview

The Verenigingen app now includes comprehensive ESLint integration with:
- **Core ESLint rules** for code quality and consistency
- **Security plugins** for vulnerability detection
- **Custom Frappe plugin** for framework-specific patterns
- **Pre-commit hooks** for automated validation
- **IDE integration** for real-time feedback

## Quick Start

### Prerequisites

```bash
# Ensure you have Node.js and npm installed
node --version  # Should be 14+
npm --version   # Should be 6+

# Install dependencies (from app root)
npm install
```

### Basic Usage

```bash
# Check all JavaScript files
npx eslint verenigingen --ext .js

# Fix automatically fixable issues
npx eslint verenigingen --ext .js --fix

# Check specific file
npx eslint verenigingen/public/js/utils/iban-validator.js

# Generate comprehensive analysis report
python scripts/analysis/eslint_analysis.py --report eslint_report.md
```

## Configuration Files

### Main Configuration (`.eslintrc.json`)

Our ESLint configuration includes:

- **Core Rules**: Best practices, potential errors, stylistic consistency
- **Security Rules**: XSS prevention, unsafe patterns detection
- **Frappe Rules**: Framework-specific patterns and validations
- **Custom Globals**: Frappe framework globals (`frappe`, `frm`, `cur_frm`, etc.)

### Ignored Files (`.eslintignore`)

Files excluded from linting:
- `node_modules/`
- `archived_unused/` and `archived_removal/`
- `*.min.js` and `*.bundle.js`
- Third-party libraries
- Development scripts and analysis tools

## Custom Frappe Plugin Rules

### 1. `frappe/require-frappe-call-error-handling`

**Purpose**: Ensures all `frappe.call()` includes proper error handling.

```javascript
// ❌ Bad - No error handling
frappe.call({
    method: 'my.method',
    callback: function(r) {
        // Handle success only
    }
});

// ✅ Good - Includes error handling
frappe.call({
    method: 'my.method',
    callback: function(r) {
        // Handle success
    },
    error: function(r) {
        console.error('Error:', r);
        frappe.msgprint('An error occurred');
    }
});
```

### 2. `frappe/no-direct-html-injection`

**Purpose**: Prevents XSS vulnerabilities from direct HTML injection.

```javascript
// ❌ Bad - Direct HTML injection
$('#content').html(user_input);
element.innerHTML = user_data;

// ✅ Good - Safe alternatives
$('#content').text(user_input);
element.textContent = user_data;
// or use frappe.render_template() with proper escaping
```

### 3. `frappe/doctype-field-validation`

**Purpose**: Validates DocType field references to prevent typos.

```javascript
// ❌ Bad - Potential typo
frm.set_value('customer_id', value);  // Should be 'customer'

// ✅ Good - Correct field name
frm.set_value('customer', value);

// ❌ Bad - Deprecated field
frm.doc.compliance_status;  // Renamed to 'severity'

// ✅ Good - Current field name
frm.doc.severity;
```

### 4. `frappe/form-event-patterns`

**Purpose**: Ensures proper form event handler patterns.

```javascript
// ❌ Bad - Missing 'frm' parameter
frappe.ui.form.on('Member', {
    refresh: function() {  // Missing frm parameter
        // ...
    }
});

// ✅ Good - Proper parameter
frappe.ui.form.on('Member', {
    refresh: function(frm) {
        // ...
    }
});
```

### 5. `frappe/sepa-security-patterns`

**Purpose**: Ensures secure handling of financial data.

```javascript
// ❌ Bad - Logging sensitive data
console.log('IBAN:', frm.doc.iban);

// ✅ Good - Avoid logging sensitive data
console.log('IBAN validation result:', isValid);

// ❌ Bad - Direct display of sensitive data
frappe.msgprint('Your IBAN: ' + iban);

// ✅ Good - Masked display
frappe.msgprint('IBAN ending in: ***' + iban.slice(-4));
```

## Security Rules

### XSS Prevention

```javascript
// ❌ Dangerous patterns detected
$('#output').html(userInput);
document.write(content);
eval(userCode);

// ✅ Safe alternatives
$('#output').text(userInput);
// Use frappe.render_template() or proper sanitization
```

### Unsafe Patterns

```javascript
// ❌ Detected by security plugin
setTimeout("alert('hello')", 1000);  // String argument
new RegExp(userInput);  // Non-literal regex

// ✅ Safe alternatives
setTimeout(() => alert('hello'), 1000);  // Function argument
new RegExp(escapeRegex(userInput));  // Escaped input
```

## IDE Integration

### VS Code Setup

The repository includes VS Code configuration:

**Features:**
- Real-time ESLint validation
- Auto-fix on save
- Problem highlighting
- Task integration

**Tasks Available:**
- `ESLint Check` - Run full validation
- `ESLint Fix` - Auto-fix issues
- `ESLint Analysis Report` - Generate comprehensive report

### Settings

```json
{
  "eslint.enable": true,
  "eslint.validate": ["javascript", "html"],
  "editor.codeActionsOnSave": {
    "source.fixAll.eslint": true
  },
  "[javascript]": {
    "editor.defaultFormatter": "dbaeumer.vscode-eslint",
    "editor.tabSize": 4,
    "editor.insertSpaces": false
  }
}
```

## Pre-Commit Integration

ESLint runs automatically on commit via pre-commit hooks:

```yaml
- id: eslint
  name: ESLint JavaScript validation
  entry: npx eslint
  language: node
  files: \.js$
  args: [--fix]
```

**What happens:**
1. Pre-commit hook runs ESLint on changed `.js` files
2. Auto-fixes are applied where possible
3. Remaining issues block the commit
4. Developer must fix issues before committing

## Analysis and Reporting

### Comprehensive Analysis

```bash
# Generate detailed report
python scripts/analysis/eslint_analysis.py --report eslint_report.md

# Include auto-fixes
python scripts/analysis/eslint_analysis.py --fix --report eslint_report.md

# Save raw JSON data
python scripts/analysis/eslint_analysis.py --json results.json
```

### Report Contents

The analysis report includes:
- **Summary statistics** (files, errors, warnings)
- **Most common rule violations**
- **Security issues** found
- **Frappe-specific issues**
- **Files needing attention**
- **Actionable recommendations**

## Common Issues and Solutions

### 1. Field Reference Errors

**Issue**: `frappe/doctype-field-validation` warnings
**Solution**: Verify field names in DocType JSON files

### 2. Missing Error Handling

**Issue**: `frappe/require-frappe-call-error-handling` errors
**Solution**: Add `error` callback to `frappe.call()`

### 3. Security Warnings

**Issue**: `security/detect-*` or `no-unsanitized/*` warnings
**Solution**: Use safe alternatives for user input handling

### 4. Indentation Issues

**Issue**: `indent` errors
**Solution**: Use tabs (4 spaces) consistently

### 5. Quote Consistency

**Issue**: `quotes` errors
**Solution**: Use single quotes consistently

## Development Workflow

### 1. Before Writing Code

```bash
# Check current status
npx eslint verenigingen --ext .js
```

### 2. During Development

- Use IDE integration for real-time feedback
- Fix issues as you code
- Run ESLint frequently

### 3. Before Committing

```bash
# Auto-fix what can be fixed
npx eslint verenigingen --ext .js --fix

# Check remaining issues
npx eslint verenigingen --ext .js

# Generate report for review
python scripts/analysis/eslint_analysis.py --report review.md
```

### 4. Pre-commit Hook

The pre-commit hook will:
- Run ESLint on changed files
- Apply auto-fixes
- Block commit if errors remain

## Gradual Adoption Strategy

### Phase 1: New Files Only ✅

- ESLint enforced on new JavaScript files
- Warnings on existing files
- Pre-commit hooks active

### Phase 2: Critical Fixes (Planned)

- Fix security issues in existing files
- Address Frappe-specific violations
- Update deprecated field references

### Phase 3: Full Compliance (Planned)

- All files pass ESLint validation
- Strict mode enabled
- Zero-tolerance for violations

## Exemptions and Overrides

### File-Level Exemptions

```javascript
/* eslint-disable no-console */
// Temporary debugging code
console.log('Debug info');
/* eslint-enable no-console */
```

### Rule-Specific Exemptions

```javascript
// eslint-disable-next-line frappe/require-frappe-call-error-handling
frappe.call({
    method: 'safe.method'  // Known safe method
});
```

### Global Exemptions

Add to `.eslintignore` for permanent exclusions.

## Performance Considerations

### Large Codebase Optimization

- ESLint processes 131 JavaScript files
- Pre-commit hooks only check changed files
- Analysis script includes timeout handling
- IDE integration uses incremental checking

### Caching

- ESLint uses built-in caching for faster subsequent runs
- Pre-commit hooks cache results per file
- IDE integration provides real-time feedback

## Troubleshooting

### Common Problems

1. **ESLint not found**: Run `npm install` to install dependencies
2. **Config errors**: Check `.eslintrc.json` syntax
3. **Plugin errors**: Ensure custom plugin is properly installed
4. **IDE not working**: Check VS Code ESLint extension is installed
5. **Pre-commit failing**: Run `pre-commit install` to setup hooks

### Getting Help

1. Check ESLint documentation: https://eslint.org/docs/
2. Review custom plugin rules in `eslint-plugins/eslint-plugin-frappe/`
3. Run analysis script for detailed insights
4. Check IDE output panel for specific errors

## Best Practices

### 1. Code Quality

- Use meaningful variable names
- Avoid `console.log` in production code
- Handle errors appropriately
- Follow consistent formatting

### 2. Security

- Never log sensitive data (IBAN, BIC, passwords)
- Sanitize user input before display
- Use `frappe.render_template()` for HTML generation
- Avoid `eval()` and similar dangerous functions

### 3. Frappe Patterns

- Always include `frm` parameter in form handlers
- Use proper error handling in `frappe.call()`
- Verify field names against DocType definitions
- Follow framework conventions

### 4. Performance

- Minimize DOM manipulation in loops
- Use event delegation where appropriate
- Cache jQuery selectors
- Avoid unnecessary API calls

## Conclusion

The ESLint integration provides comprehensive code quality validation for the Verenigingen JavaScript codebase. It enforces consistency, prevents security vulnerabilities, validates Frappe-specific patterns, and provides actionable feedback to developers.

The system is designed for gradual adoption while immediately providing value through:
- Real-time IDE feedback
- Automated pre-commit validation
- Comprehensive analysis reporting
- Framework-specific rule validation

This ensures that the JavaScript codebase maintains high quality standards while supporting the complex requirements of the Verenigingen association management system.
