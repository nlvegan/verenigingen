/**
 * Rule: doctype-field-validation
 * Validates DocType field references to prevent field name errors
 */

module.exports = {
	meta: {
		type: 'suggestion',
		docs: {
			description: 'Validate DocType field references',
			category: 'Best Practices',
			recommended: true
		},
		fixable: null,
		schema: []
	},

	create(context) {
		// Common field patterns that often have typos
		const commonFieldPatterns = {
			'customer_name': 'customer_name',
			'customername': 'customer_name',
			'customer_id': 'customer',
			'member_name': 'member_name',
			'membername': 'member_name',
			'member_id': 'member',
			'company_name': 'company_name',
			'companyname': 'company_name',
			'first_name': 'first_name',
			'firstname': 'first_name',
			'last_name': 'last_name',
			'lastname': 'last_name',
			'email_id': 'email',
			'emailid': 'email',
			'mobile_no': 'mobile_no',
			'mobileno': 'mobile_no',
			'phone_no': 'phone_no',
			'phoneno': 'phone_no'
		};

		// Deprecated or renamed fields specific to this application
		const deprecatedFields = {
			'compliance_status': 'severity',
			'old_field_name': 'new_field_name'
		};

		return {
			CallExpression(node) {
				// Check frm.set_value and similar methods
				if (
					node.callee.type === 'MemberExpression' &&
					node.callee.object.name === 'frm' &&
					['set_value', 'get_value', 'set_df_property', 'get_field', 'toggle_display', 'toggle_enable', 'toggle_reqd'].includes(node.callee.property.name)
				) {
					const args = node.arguments;
					if (args.length > 0 && args[0].type === 'Literal') {
						const fieldName = args[0].value;

						// Check for deprecated fields
						if (deprecatedFields[fieldName]) {
							context.report({
								node: args[0],
								message: `Field '${fieldName}' has been deprecated. Use '${deprecatedFields[fieldName]}' instead.`
							});
						}

						// Check for common typos
						if (commonFieldPatterns[fieldName] && commonFieldPatterns[fieldName] !== fieldName) {
							context.report({
								node: args[0],
								message: `Possible typo: '${fieldName}' should be '${commonFieldPatterns[fieldName]}'`
							});
						}

						// Check for suspicious patterns
						if (typeof fieldName === 'string') {
							// Fields ending with _id usually reference other doctypes
							if (fieldName.endsWith('_id') && !fieldName.includes('member') && !fieldName.includes('customer')) {
								context.report({
									node: args[0],
									message: `Field '${fieldName}' ends with '_id' which may indicate a Link field. Verify field exists and type is correct.`
								});
							}

							// Check for inconsistent naming
							if (fieldName.includes('-') || fieldName.includes(' ')) {
								context.report({
									node: args[0],
									message: `Field name '${fieldName}' contains hyphens or spaces. DocType fields use underscores.`
								});
							}

							// Check for CamelCase (should be snake_case)
							if (/[A-Z]/.test(fieldName) && fieldName !== fieldName.toLowerCase()) {
								context.report({
									node: args[0],
									message: `Field name '${fieldName}' uses CamelCase. DocType fields should use snake_case.`
								});
							}
						}
					}
				}

				// Check frappe.model.set_value
				if (
					node.callee.type === 'MemberExpression' &&
					node.callee.object.type === 'MemberExpression' &&
					node.callee.object.object.name === 'frappe' &&
					node.callee.object.property.name === 'model' &&
					node.callee.property.name === 'set_value'
				) {
					const args = node.arguments;
					if (args.length >= 3 && args[2].type === 'Literal') {
						const fieldName = args[2].value;

						// Apply same validations as above
						if (deprecatedFields[fieldName]) {
							context.report({
								node: args[2],
								message: `Field '${fieldName}' has been deprecated. Use '${deprecatedFields[fieldName]}' instead.`
							});
						}
					}
				}
			},

			// Check property access on doc objects
			MemberExpression(node) {
				// Check frm.doc.field_name patterns
				if (
					node.object.type === 'MemberExpression' &&
					node.object.object.name === 'frm' &&
					node.object.property.name === 'doc' &&
					node.property.type === 'Identifier'
				) {
					const fieldName = node.property.name;

					// Apply validations
					if (deprecatedFields[fieldName]) {
						context.report({
							node: node.property,
							message: `Field '${fieldName}' has been deprecated. Use '${deprecatedFields[fieldName]}' instead.`
						});
					}

					if (commonFieldPatterns[fieldName] && commonFieldPatterns[fieldName] !== fieldName) {
						context.report({
							node: node.property,
							message: `Possible typo: '${fieldName}' should be '${commonFieldPatterns[fieldName]}'`
						});
					}
				}

				// Check locals[cdt][cdn].field_name patterns (child table access)
				if (
					node.object.type === 'MemberExpression' &&
					node.object.object.type === 'MemberExpression' &&
					node.object.object.object.name === 'locals' &&
					node.property.type === 'Identifier'
				) {
					const fieldName = node.property.name;

					// Apply same validations for child table fields
					if (deprecatedFields[fieldName]) {
						context.report({
							node: node.property,
							message: `Child table field '${fieldName}' has been deprecated. Use '${deprecatedFields[fieldName]}' instead.`
						});
					}
				}
			}
		};
	}
};
