/**
 * @fileoverview ESLint rule to enforce error handling in frappe.call() invocations
 *
 * This custom ESLint rule ensures that all frappe.call() invocations include proper
 * error handling callbacks. This is critical for robust applications that need to
 * handle API failures gracefully and provide meaningful feedback to users.
 *
 * Business Context:
 * - Verenigingen relies heavily on frappe.call() for server-client communication
 * - API failures can occur due to network issues, server errors, or validation failures
 * - Proper error handling improves user experience and system reliability
 * - Prevents silent failures that could lead to data inconsistency
 *
 * Rule Requirements:
 * - All frappe.call() invocations must include an 'error' callback function
 * - Error handlers should provide meaningful user feedback or fallback behavior
 * - Prevents unhandled promise rejections and silent API failures
 *
 * Examples:
 * ```javascript
 * // ❌ Bad - No error handling
 * frappe.call({
 *   method: 'my_app.api.some_method',
 *   callback: function(r) { ... }
 * });
 *
 * // ✅ Good - Includes error handling
 * frappe.call({
 *   method: 'my_app.api.some_method',
 *   callback: function(r) { ... },
 *   error: function(r) {
 *     frappe.msgprint(__('An error occurred. Please try again.'));
 *   }
 * });
 * ```
 *
 * @module eslint-plugin-frappe/rules/require-frappe-call-error-handling
 * @version 1.0.0
 * @since 2024
 * @see {@link https://frappeframework.com/docs/user/en/api/frappe-client|Frappe Client API}
 *
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
					node.callee.type === 'MemberExpression'
					&& node.callee.object.name === 'frappe'
					&& node.callee.property.name === 'call'
				) {
					const args = node.arguments;
					if (args.length === 0) { return; }

					const firstArg = args[0];
					if (firstArg.type !== 'ObjectExpression') { return; }

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
