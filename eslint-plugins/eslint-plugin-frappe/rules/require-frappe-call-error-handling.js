/**
 * Rule: require-frappe-call-error-handling
 * Ensures frappe.call() includes proper error handling
 */

module.exports = {
	meta: {
		type: 'problem',
		docs: {
			description: 'Require error handling in frappe.call()',
			category: 'Possible Errors',
			recommended: true
		},
		fixable: null,
		schema: []
	},

	create(context) {
		return {
			CallExpression(node) {
				// Check for frappe.call()
				if (
					node.callee.type === 'MemberExpression' &&
					node.callee.object.name === 'frappe' &&
					node.callee.property.name === 'call'
				) {
					const args = node.arguments;
					if (args.length === 0) return;

					const firstArg = args[0];
					if (firstArg.type !== 'ObjectExpression') return;

					// Check if error handler exists
					const hasErrorHandler = firstArg.properties.some(prop =>
						prop.key && prop.key.name === 'error'
					);

					if (!hasErrorHandler) {
						context.report({
							node,
							message: 'frappe.call() should include error handling with an "error" callback'
						});
					}
				}
			}
		};
	}
};
