/**
 * @fileoverview ESLint rule to enforce proper form event handler patterns in Frappe Framework
 *
 * This ESLint rule ensures that Frappe Framework form event handlers follow proper
 * patterns and conventions. It validates parameter naming, event handler structure,
 * and UI component usage for consistent and maintainable form customizations.
 *
 * Business Context:
 * - Verenigingen has extensive form customizations for member management
 * - Proper event handler patterns prevent runtime errors and improve UX
 * - Consistent parameter naming makes code more maintainable
 * - Translation support ensures internationalization compatibility
 * - Proper dialog patterns maintain UI consistency
 *
 * Form Event Patterns Validated:
 * - frappe.ui.form.on() structure and parameter validation
 * - Standard form events: refresh, onload, validate, before_save, after_save
 * - Child table events: fieldname_add, fieldname_remove with (frm, cdt, cdn) params
 * - Field change events with proper frm parameter
 * - Custom button creation with translation support
 * - Dialog function patterns
 *
 * Event Handler Examples:
 * ```javascript
 * // ✅ Correct form event patterns
 * frappe.ui.form.on('Member', {
 *   refresh: function(frm) {
 *     // Form refresh logic
 *   },
 *
 *   first_name: function(frm) {
 *     // Field change handler
 *   },
 *
 *   addresses_add: function(frm, cdt, cdn) {
 *     // Child table row add handler
 *   }
 * });
 *
 * // ✅ Custom button with translation
 * frm.add_custom_button(__('Send Email'), function() {
 *   // Button action
 * });
 *
 * // ❌ Wrong patterns (flagged by rule)
 * frappe.ui.form.on('Member', {
 *   refresh: function() { }, // Missing frm parameter
 *   addresses_add: function(frm) { } // Missing cdt, cdn parameters
 * });
 *
 * frm.add_custom_button('Send Email', function() {}); // Missing translation wrapper
 * ```
 *
 * @module eslint-plugin-frappe/rules/form-event-patterns
 * @version 1.0.0
 * @since 2024
 * @see {@link https://frappeframework.com/docs/user/en/api/form|Frappe Form API}
 * @see {@link https://frappeframework.com/docs/user/en/guides/integration/client-side-scripting|Client-side Scripting}
 *
 * Rule: form-event-patterns
 * Ensures proper form event handler patterns
 */

module.exports = {
	meta: {
		type: 'suggestion',
		docs: {
			description: 'Ensure proper form event handler patterns',
			category: 'Best Practices',
			recommended: true
		},
		fixable: null,
		schema: []
	},

	create(context) {
		return {
			// Check frappe.ui.form.on patterns
			CallExpression(node) {
				if (
					node.callee.type === 'MemberExpression'
					&& node.callee.object.type === 'MemberExpression'
					&& node.callee.object.type === 'MemberExpression'
					&& node.callee.object.object.type === 'MemberExpression'
					&& node.callee.object.object.object.name === 'frappe'
					&& node.callee.object.object.property.name === 'ui'
					&& node.callee.object.property.name === 'form'
					&& node.callee.property.name === 'on'
				) {
					const args = node.arguments;
					if (args.length >= 2) {
						const docTypeArg = args[0];
						const handlersArg = args[1];

						// Check if doctype is a string
						if (docTypeArg.type !== 'Literal' || typeof docTypeArg.value !== 'string') {
							context.report({
								node: docTypeArg,
								message: 'DocType name should be a string literal in frappe.ui.form.on()'
							});
						}

						// Check handlers object
						if (handlersArg.type === 'ObjectExpression') {
							handlersArg.properties.forEach(prop => {
								if (prop.key && prop.value.type === 'FunctionExpression') {
									const eventName = prop.key.name || prop.key.value;
									const func = prop.value;

									// Check for proper parameter names
									if (['refresh', 'onload', 'validate', 'before_save', 'after_save'].includes(eventName)) {
										if (func.params.length === 0 || func.params[0].name !== 'frm') {
											context.report({
												node: func,
												message: `Form event '${eventName}' should have 'frm' as first parameter`
											});
										}
									}

									// Check for child table events
									if (eventName.includes('_add') || eventName.includes('_remove')) {
										if (func.params.length < 3) {
											context.report({
												node: func,
												message: `Child table event '${eventName}' should have (frm, cdt, cdn) parameters`
											});
										} else {
											const [frmParam, cdtParam, cdnParam] = func.params;
											if (frmParam.name !== 'frm' || cdtParam.name !== 'cdt' || cdnParam.name !== 'cdn') {
												context.report({
													node: func,
													message: 'Child table event parameters should be named (frm, cdt, cdn)'
												});
											}
										}
									}

									// Check for field change events
									if (!['refresh', 'onload', 'validate', 'before_save', 'after_save'].includes(eventName)
										&& !eventName.includes('_add') && !eventName.includes('_remove')) {
										// This is likely a field change event
										if (func.params.length === 0 || func.params[0].name !== 'frm') {
											context.report({
												node: func,
												message: `Field change event '${eventName}' should have 'frm' as first parameter`
											});
										}
									}
								}
							});
						}
					}
				}

				// Check for proper return statements in validate handlers
				if (
					node.callee.type === 'Identifier'
					&& node.callee.name === 'validate'
				) {
					// This would need more context analysis to be truly effective
					// For now, just suggest proper return patterns
					context.report({
						node,
						message: 'Validate functions should return false to prevent save, or true/undefined to allow'
					});
				}
			},

			// Check function declarations that might be form handlers
			FunctionDeclaration(node) {
				if (node.id && node.id.name) {
					const funcName = node.id.name;

					// Check for common form handler naming patterns
					if (funcName.startsWith('handle_') || funcName.endsWith('_handler')) {
						if (node.params.length === 0 || node.params[0].name !== 'frm') {
							context.report({
								node,
								message: `Form handler function '${funcName}' should accept 'frm' as first parameter`
							});
						}
					}

					// Check for dialog-related functions
					if (funcName.includes('dialog') && funcName.includes('show')) {
						// Should check for proper dialog patterns
						context.report({
							node,
							message: `Dialog function '${funcName}' should use frappe.ui.Dialog for consistency`
						});
					}
				}
			},

			// Check for proper button adding patterns
			MemberExpression(node) {
				if (
					node.object.name === 'frm'
					&& node.property.name === 'add_custom_button'
				) {
					// This suggests checking the parent CallExpression
					const parent = node.parent;
					if (parent && parent.type === 'CallExpression') {
						const args = parent.arguments;
						if (args.length >= 2) {
							const labelArg = args[0];
							const callbackArg = args[1];

							// Check if label is translatable
							if (labelArg.type === 'Literal' && typeof labelArg.value === 'string') {
								if (!labelArg.value.startsWith('__')) {
									context.report({
										node: labelArg,
										message: 'Button labels should be wrapped with __(label) for translation'
									});
								}
							}

							// Check if callback is a proper function
							if (callbackArg.type !== 'FunctionExpression' && callbackArg.type !== 'ArrowFunctionExpression') {
								context.report({
									node: callbackArg,
									message: 'Button callback should be a function expression'
								});
							}
						}
					}
				}
			}
		};
	}
};
