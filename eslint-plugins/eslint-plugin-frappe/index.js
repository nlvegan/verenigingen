/**
 * ESLint Plugin for Frappe Framework Development
 * Custom rules for Verenigingen and Frappe development patterns
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
