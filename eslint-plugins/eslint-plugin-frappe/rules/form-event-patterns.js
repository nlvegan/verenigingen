/**
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
					node.callee.type === 'MemberExpression' &&
					node.callee.object.type === 'MemberExpression' &&
					node.callee.object.type === 'MemberExpression' &&
					node.callee.object.object.type === 'MemberExpression' &&
					node.callee.object.object.object.name === 'frappe' &&
					node.callee.object.object.property.name === 'ui' &&
					node.callee.object.property.name === 'form' &&
					node.callee.property.name === 'on'
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
									if (!['refresh', 'onload', 'validate', 'before_save', 'after_save'].includes(eventName) &&
										!eventName.includes('_add') && !eventName.includes('_remove')) {
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
					node.callee.type === 'Identifier' &&
					node.callee.name === 'validate'
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
					node.object.name === 'frm' &&
					node.property.name === 'add_custom_button'
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
