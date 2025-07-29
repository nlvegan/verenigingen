/**
 * Rule: no-direct-html-injection
 * Prevents direct HTML injection that could lead to XSS
 */

module.exports = {
	meta: {
		type: 'problem',
		docs: {
			description: 'Prevent direct HTML injection to avoid XSS vulnerabilities',
			category: 'Security',
			recommended: true
		},
		fixable: null,
		schema: []
	},

	create(context) {
		const dangerousMethods = [
			'html',
			'innerHTML',
			'append',
			'prepend',
			'after',
			'before',
			'replaceWith'
		];

		const _safeMethods = [
			'text',
			'val',
			'attr'
		];

		return {
			CallExpression(node) {
				// Check jQuery methods
				if (
					node.callee.type === 'MemberExpression' &&
					dangerousMethods.includes(node.callee.property.name)
				) {
					const args = node.arguments;
					if (args.length > 0) {
						const firstArg = args[0];

						// Check if argument contains user data or variables
						if (
							firstArg.type === 'Identifier' ||
							firstArg.type === 'MemberExpression' ||
							firstArg.type === 'CallExpression' ||
							(firstArg.type === 'TemplateLiteral' && firstArg.expressions.length > 0)
						) {
							context.report({
								node,
								message: `Avoid using ${node.callee.property.name}() with dynamic content. Consider using text(), sanitization, or frappe.render_template() instead.`
							});
						}
					}
				}

				// Check for document.write
				if (
					node.callee.type === 'MemberExpression' &&
					node.callee.object.name === 'document' &&
					node.callee.property.name === 'write'
				) {
					context.report({
						node,
						message: 'Avoid document.write() as it can be dangerous and blocks parsing'
					});
				}

				// Check for eval-like functions
				if (
					node.callee.type === 'Identifier' &&
					['eval', 'setTimeout', 'setInterval'].includes(node.callee.name)
				) {
					const args = node.arguments;
					if (args.length > 0 && args[0].type === 'Literal' && typeof args[0].value === 'string') {
						context.report({
							node,
							message: `Avoid using ${node.callee.name}() with string arguments. Use function references instead.`
						});
					}
				}
			},

			AssignmentExpression(node) {
				// Check for innerHTML assignments
				if (
					node.left.type === 'MemberExpression' &&
					node.left.property.name === 'innerHTML'
				) {
					context.report({
						node,
						message: 'Avoid direct innerHTML assignment. Use textContent, frappe.render_template(), or proper sanitization.'
					});
				}
			}
		};
	}
};
