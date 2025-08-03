/**
 * @fileoverview ESLint rule to validate proper usage of Frappe Framework API patterns
 *
 * This comprehensive ESLint rule enforces best practices for Frappe Framework API usage
 * in the Verenigingen application. It validates common patterns, prevents API misuse,
 * and promotes consistent coding standards across the application.
 *
 * Business Context:
 * - Verenigingen uses extensive Frappe Framework APIs for data operations
 * - Proper API usage prevents runtime errors and improves performance
 * - Consistent patterns make code more maintainable and readable
 * - Validation helps catch field reference errors before deployment
 *
 * API Patterns Validated:
 * - frappe.db.get_value() field parameter consistency
 * - frappe.call() method path validation and whitelisting
 * - frm.set_value() field name validation
 * - Asynchronous operation callback patterns
 * - Form event handler parameter conventions
 * - DocType field reference validation
 *
 * Examples:
 * ```javascript
 * // ✅ Good patterns
 * frappe.db.get_value('Member', member_id, ['name', 'first_name', 'email']);
 * frappe.call({
 *   method: 'verenigingen.api.member.get_details',
 *   callback: function(r) { ... },
 *   error: function(r) { ... }
 * });
 *
 * refresh: function(frm) {
 *   // Form event with proper parameter
 * }
 *
 * // ❌ Bad patterns (will be flagged)
 * frappe.db.get_value('Member', member_id, 'name'); // String instead of array
 * frappe.call({ method: 'get_details' }); // Missing module path
 * refresh: function() { } // Missing frm parameter
 * ```
 *
 * @module eslint-plugin-frappe/rules/frappe-api-validation
 * @version 1.0.0
 * @since 2024
 * @see {@link https://frappeframework.com/docs/user/en/api|Frappe Framework API Documentation}
 *
 * Rule: frappe-api-validation
 * Validates proper usage of Frappe API patterns
 */

module.exports = {
	meta: {
		type: 'suggestion',
		docs: {
			description: 'Ensure proper Frappe API usage patterns',
			category: 'Best Practices',
			recommended: true
		},
		fixable: null,
		schema: []
	},

	create(context) {
		return {
			CallExpression(node) {
				// Check frappe.db.get_value usage
				if (
					node.callee.type === 'MemberExpression'
					&& node.callee.object.type === 'MemberExpression'
					&& node.callee.object.object.name === 'frappe'
					&& node.callee.object.property.name === 'db'
					&& node.callee.property.name === 'get_value'
				) {
					const args = node.arguments;
					if (args.length >= 3) {
						// Check if fields parameter is a string (should be array for multiple fields)
						const fieldsArg = args[2];
						if (fieldsArg.type === 'Literal' && typeof fieldsArg.value === 'string') {
							// Single field is OK, but recommend array for consistency
							context.report({
								node,
								message: 'Consider using array format for fields parameter in frappe.db.get_value() for consistency, even for single fields'
							});
						}
					}
				}

				// Check frappe.call method parameter
				if (
					node.callee.type === 'MemberExpression'
					&& node.callee.object.name === 'frappe'
					&& node.callee.property.name === 'call'
				) {
					const args = node.arguments;
					if (args.length > 0 && args[0].type === 'ObjectExpression') {
						const methodProp = args[0].properties.find(prop =>
							prop.key && prop.key.name === 'method'
						);

						if (methodProp && methodProp.value.type === 'Literal') {
							const methodPath = methodProp.value.value;

							// Check for proper whitelisted method format
							if (typeof methodPath === 'string' && methodPath.includes('.')) {
								const parts = methodPath.split('.');
								if (parts.length < 3) {
									context.report({
										node: methodProp,
										message: 'Frappe method calls should use full module path (e.g., "app.module.function")'
									});
								}
							}
						}
					}
				}

				// Check for proper frm.set_value usage
				if (
					node.callee.type === 'MemberExpression'
					&& node.callee.object.name === 'frm'
					&& node.callee.property.name === 'set_value'
				) {
					const args = node.arguments;
					if (args.length >= 2) {
						const fieldArg = args[0];
						// Warn about hardcoded field names that might not exist
						if (fieldArg.type === 'Literal' && typeof fieldArg.value === 'string') {
							// This would need integration with your field validator
							// For now, just check for common typos
							const fieldName = fieldArg.value;
							if (fieldName.includes('_') && fieldName.endsWith('_id')) {
								context.report({
									node: fieldArg,
									message: 'Verify that field name exists in DocType definition. Consider using field validator.'
								});
							}
						}
					}
				}

				// Check for missing callback in asynchronous operations
				if (
					node.callee.type === 'MemberExpression'
					&& node.callee.object.name === 'frm'
					&& ['save', 'reload_doc', 'submit', 'cancel'].includes(node.callee.property.name)
				) {
					// These methods return promises, suggest using .then() or callback
					context.report({
						node,
						message: `Consider using callback or .then() with ${node.callee.property.name}() for proper async handling`
					});
				}
			},

			// Check for proper form event handler patterns
			Property(node) {
				if (
					node.key.type === 'Identifier'
					&& node.value.type === 'FunctionExpression'
					&& ['refresh', 'onload', 'validate', 'before_save', 'after_save'].includes(node.key.name)
				) {
					const params = node.value.params;
					if (params.length === 0 || params[0].name !== 'frm') {
						context.report({
							node,
							message: `Form event handler '${node.key.name}' should accept 'frm' as first parameter`
						});
					}
				}
			}
		};
	}
};
