/**
 * Rule: sepa-security-patterns
 * Ensures secure handling of SEPA/financial data
 */

module.exports = {
	meta: {
		type: 'problem',
		docs: {
			description: 'Ensure secure handling of SEPA and financial data',
			category: 'Security',
			recommended: true
		},
		fixable: null,
		schema: []
	},

	create(context) {
		const sensitiveFields = [
			'iban',
			'bic',
			'bank_account',
			'account_number',
			'sort_code',
			'routing_number',
			'swift_code',
			'mandate_reference',
			'credit_card',
			'card_number',
			'cvv',
			'pin'
		];

		const _logMethods = [
			'console.log',
			'console.info',
			'console.warn',
			'console.error',
			'console.debug',
			'frappe.log',
			'frappe.msgprint'
		];

		return {
			// Check for logging of sensitive data
			CallExpression(node) {
				// Check console.log and similar methods
				if (
					(node.callee.type === 'MemberExpression' &&
					node.callee.object.name === 'console') ||
					(node.callee.type === 'MemberExpression' &&
					node.callee.object.name === 'frappe' &&
					['log', 'msgprint'].includes(node.callee.property.name))
				) {
					node.arguments.forEach(arg => {
						if (this.containsSensitiveData(arg)) {
							context.report({
								node: arg,
								message: 'Avoid logging sensitive financial data (IBAN, BIC, account numbers, etc.)'
							});
						}
					});
				}

				// Check for alert/msgprint with sensitive data
				if (
					node.callee.type === 'Identifier' &&
					['alert', 'msgprint'].includes(node.callee.name)
				) {
					node.arguments.forEach(arg => {
						if (this.containsSensitiveData(arg)) {
							context.report({
								node: arg,
								message: 'Avoid displaying sensitive financial data in alerts or messages'
							});
						}
					});
				}

				// Check for IBAN/BIC validation without proper sanitization
				if (
					node.callee.type === 'MemberExpression' &&
					node.callee.property.name === 'validate' &&
					node.arguments.length > 0
				) {
					// Look for IBAN validation patterns
					const firstArg = node.arguments[0];
					if (firstArg.type === 'Identifier' &&
						sensitiveFields.some(field => firstArg.name.toLowerCase().includes(field))) {
						context.report({
							node,
							message: 'Ensure IBAN/BIC validation includes proper sanitization and format checking'
						});
					}
				}
			},

			// Check for direct access to sensitive fields without validation
			MemberExpression(node) {
				if (
					node.object.type === 'MemberExpression' &&
					node.object.object.name === 'frm' &&
					node.object.property.name === 'doc' &&
					node.property.type === 'Identifier'
				) {
					const fieldName = node.property.name.toLowerCase();

					if (sensitiveFields.some(sensitive => fieldName.includes(sensitive))) {
						// Check if this access is inside a validation or sanitization context
						const parent = node.parent;
						if (parent && parent.type === 'AssignmentExpression' && parent.right === node) {
							context.report({
								node,
								message: `Direct assignment to sensitive field '${node.property.name}'. Ensure proper validation and sanitization.`
							});
						}
					}
				}
			},

			// Check for string concatenation with sensitive data
			BinaryExpression(node) {
				if (node.operator === '+') {
					[node.left, node.right].forEach(operand => {
						if (this.containsSensitiveData(operand)) {
							context.report({
								node: operand,
								message: 'Avoid string concatenation with sensitive financial data. Use secure templating instead.'
							});
						}
					});
				}
			},

			// Check template literals with sensitive data
			TemplateLiteral(node) {
				node.expressions.forEach(expr => {
					if (this.containsSensitiveData(expr)) {
						context.report({
							node: expr,
							message: 'Avoid including sensitive financial data in template literals. Consider masking or sanitization.'
						});
					}
				});
			}
		};
	},

	// Helper method to detect sensitive data patterns
	containsSensitiveData(node) {
		if (!node) return false;

		const sensitivePatterns = [
			'iban',
			'bic',
			'bank_account',
			'account_number',
			'mandate_reference',
			'swift',
			'sort_code'
		];

		// Check identifiers
		if (node.type === 'Identifier') {
			return sensitivePatterns.some(pattern =>
				node.name.toLowerCase().includes(pattern)
			);
		}

		// Check member expressions (obj.prop)
		if (node.type === 'MemberExpression' && node.property.type === 'Identifier') {
			return sensitivePatterns.some(pattern =>
				node.property.name.toLowerCase().includes(pattern)
			);
		}

		// Check string literals for patterns like "IBAN: NL91..."
		if (node.type === 'Literal' && typeof node.value === 'string') {
			const value = node.value.toLowerCase();
			return sensitivePatterns.some(pattern => value.includes(pattern)) ||
				/\b[a-z]{2}\d{2}[a-z0-9]{4,30}\b/i.test(node.value) || // IBAN pattern
				/\b[a-z]{4}[a-z]{2}[a-z0-9]{2}([a-z0-9]{3})?\b/i.test(node.value); // BIC pattern
		}

		// Check call expressions (function calls)
		if (node.type === 'CallExpression') {
			return node.arguments.some(arg => this.containsSensitiveData(arg));
		}

		return false;
	}
};
