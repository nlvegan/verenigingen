/**
 * @fileoverview ESLint Plugin for Frappe Framework Development in Verenigingen Association Management
 *
 * This custom ESLint plugin provides specialized linting rules for Frappe framework
 * development, ensuring code quality, security compliance, and adherence to
 * framework-specific patterns within the association management system.
 *
 * @description Business Context:
 * The ESLint plugin enforces development standards and security practices
 * specifically tailored for association management requirements:
 * - Financial data security with SEPA compliance patterns
 * - API error handling for robust member management operations
 * - HTML injection prevention for secure user interface development
 * - DocType field validation for data integrity assurance
 * - Form event pattern enforcement for consistent user experience
 * - Frappe framework best practices for maintainable code
 *
 * @description Key Rules:
 * - require-frappe-call-error-handling: Enforces proper error handling in API calls
 * - no-direct-html-injection: Prevents XSS vulnerabilities in dynamic content
 * - frappe-api-validation: Validates API endpoint usage and parameter handling
 * - doctype-field-validation: Ensures proper DocType field reference validation
 * - form-event-patterns: Enforces consistent form event handling patterns
 * - sepa-security-patterns: Validates SEPA financial data security compliance
 *
 * @description Configuration Profiles:
 * - recommended: Balanced rules for general development with essential security
 * - strict: Comprehensive rules for production-ready code quality assurance
 *
 * @description Integration Benefits:
 * - Prevents common Frappe framework development pitfalls
 * - Ensures security compliance for financial data handling
 * - Maintains code consistency across development team
 * - Reduces debugging time through early error detection
 * - Enforces association management specific best practices
 *
 * @author Verenigingen Development Team
 * @version 2025-01-13
 * @since 1.0.0
 *
 * @requires eslint
 * @requires ./rules/require-frappe-call-error-handling
 * @requires ./rules/no-direct-html-injection
 * @requires ./rules/frappe-api-validation
 * @requires ./rules/doctype-field-validation
 * @requires ./rules/form-event-patterns
 * @requires ./rules/sepa-security-patterns
 *
 * @example
 * // ESLint configuration usage:
 * // {
 * //   "plugins": ["frappe"],
 * //   "extends": ["plugin:frappe/recommended"]
 * // }
 */

module.exports = {
	rules: {
		'require-frappe-call-error-handling': require('./rules/require-frappe-call-error-handling'),
		'no-direct-html-injection': require('./rules/no-direct-html-injection'),
		'frappe-api-validation': require('./rules/frappe-api-validation'),
		'doctype-field-validation': require('./rules/doctype-field-validation'),
		'form-event-patterns': require('./rules/form-event-patterns'),
		'sepa-security-patterns': require('./rules/sepa-security-patterns')
	},
	configs: {
		recommended: {
			plugins: ['frappe'],
			rules: {
				'frappe/require-frappe-call-error-handling': 'error',
				'frappe/no-direct-html-injection': 'error',
				'frappe/frappe-api-validation': 'warn',
				'frappe/doctype-field-validation': 'warn',
				'frappe/form-event-patterns': 'warn',
				'frappe/sepa-security-patterns': 'error'
			}
		},
		strict: {
			plugins: ['frappe'],
			rules: {
				'frappe/require-frappe-call-error-handling': 'error',
				'frappe/no-direct-html-injection': 'error',
				'frappe/frappe-api-validation': 'error',
				'frappe/doctype-field-validation': 'error',
				'frappe/form-event-patterns': 'error',
				'frappe/sepa-security-patterns': 'error'
			}
		}
	}
};
