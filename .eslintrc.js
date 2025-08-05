/**
 * @fileoverview ESLint configuration for Verenigingen association management system
 *
 * Comprehensive ESLint configuration designed specifically for the Verenigingen Frappe app,
 * providing consistent code quality enforcement across JavaScript files. This configuration
 * balances modern JavaScript best practices with Frappe framework conventions.
 *
 * Configuration Features:
 * - Frappe-specific globals and conventions (snake_case compliance)
 * - Vue.js 3 support for frontend components
 * - Jest/Mocha testing environment support
 * - Custom rules for different file types (DocTypes, public JS, tests)
 * - Security-focused linting rules
 * - Association management utility globals
 *
 * Environment Support:
 * - Browser, Node.js, and jQuery environments
 * - ES2022 features and module syntax
 * - Cypress, Jest, and Mocha testing frameworks
 * - Frappe framework globals (frappe, frm, cur_frm, etc.)
 *
 * Business Context:
 * Enforces code quality standards across the association management system,
 * ensuring maintainable code for membership processing, financial operations,
 * volunteer management, and SEPA payment handling.
 *
 * @author Verenigingen Development Team
 * @version 2.0.0
 * @since 2024-11-01
 */

module.exports = {
	env: {
		browser: true,
		es2022: true,
		node: true,
		jquery: true,
		jest: true,
		mocha: true
	},
	extends: [
		'eslint:recommended',
		'plugin:vue/vue3-recommended'
	],
	parserOptions: {
		ecmaVersion: 2022,
		sourceType: 'module'
	},
	plugins: [
		'vue'
	],
	globals: {
		// Core Frappe globals
		frappe: 'readonly',
		verenigingen: 'readonly',
		frm: 'readonly',
		cur_frm: 'readonly',
		locals: 'readonly',
		__: 'readonly',
		cint: 'readonly',
		cstr: 'readonly',
		flt: 'readonly',
		format_currency: 'readonly',
		$: 'readonly',
		jQuery: 'readonly',
		moment: 'readonly',
		// Frappe UI globals
		Dialog: 'readonly',
		msgprint: 'readonly',
		show_alert: 'readonly',
		// Browser globals
		window: 'readonly',
		document: 'readonly',
		console: 'readonly',
		setTimeout: 'readonly',
		setInterval: 'readonly',
		clearTimeout: 'readonly',
		clearInterval: 'readonly',
		XMLHttpRequest: 'readonly',
		fetch: 'readonly',
		Promise: 'readonly',
		Map: 'readonly',
		Set: 'readonly',
		WeakMap: 'readonly',
		WeakSet: 'readonly',
		Symbol: 'readonly',
		Proxy: 'readonly',
		Reflect: 'readonly',
		// Testing globals
		QUnit: 'readonly',
		Cypress: 'readonly',
		cy: 'readonly',
		it: 'readonly',
		describe: 'readonly',
		before: 'readonly',
		beforeEach: 'readonly',
		after: 'readonly',
		afterEach: 'readonly',
		expect: 'readonly',
		jest: 'readonly',
		// Test utilities
		createTestMember: 'readonly',
		waitForDialogs: 'readonly',
		// Chart library
		Chart: 'readonly',
		// Custom utilities
		update_other_members_at_address: 'readonly',
		IBANValidator: 'readonly',
		PaymentUtils: 'readonly',
		SepaUtils: 'readonly',
		VolunteerUtils: 'readonly',
		ChapterUtils: 'readonly',
		ChapterHistoryUtils: 'readonly',
		ChapterConfig: 'readonly',
		ChapterValidation: 'readonly',
		TerminationUtils: 'readonly',
		UIUtils: 'readonly',
		// Service classes
		APIService: 'readonly',
		ValidationService: 'readonly',
		StorageService: 'readonly',
		ErrorHandler: 'readonly',
		StepManager: 'readonly',
		// Membership application classes
		MembershipApplication: 'readonly',
		PersonalInfoStep: 'readonly',
		AddressStep: 'readonly',
		MembershipStep: 'readonly',
		VolunteerStep: 'readonly',
		PaymentStep: 'readonly',
		ConfirmationStep: 'readonly',
		MembershipAPI: 'readonly',
		membershipApp: 'writable',
		UIManager: 'readonly'
	},
	rules: {
		// Basic formatting
		indent: ['error', 'tab', {
			SwitchCase: 1,
			VariableDeclarator: 1,
			outerIIFEBody: 1,
			MemberExpression: 1,
			FunctionDeclaration: { parameters: 1, body: 1 },
			FunctionExpression: { parameters: 1, body: 1 },
			CallExpression: { arguments: 1 },
			ArrayExpression: 1,
			ObjectExpression: 1,
			ImportDeclaration: 1,
			flatTernaryExpressions: false,
			ignoreComments: false
		}],
		quotes: ['error', 'single', { allowTemplateLiterals: true }],
		semi: ['error', 'always'],
		'linebreak-style': ['error', 'unix'],
		'eol-last': ['error', 'always'],
		// Variable handling
		'no-unused-vars': ['error', {
			vars: 'all',
			args: 'after-used',
			ignoreRestSiblings: false,
			varsIgnorePattern: '^(frappe|frm|cur_frm|locals|__|_)',
			argsIgnorePattern: '^_'
		}],
		'no-undef': ['error', { typeof: false }],
		'no-undef-init': 'error',
		'no-use-before-define': ['error', { functions: false, classes: true, variables: true }],
		// Console and debugging
		'no-console': 'off',
		'no-debugger': 'error',
		'no-alert': 'warn',
		// Best practices
		eqeqeq: ['error', 'always', { null: 'ignore' }],
		curly: ['error', 'all'],
		'no-eval': 'error',
		'no-implied-eval': 'error',
		'no-with': 'error',
		'no-new-func': 'error',
		'no-script-url': 'error',
		'no-return-assign': 'error',
		'no-self-compare': 'error',
		'no-throw-literal': 'error',
		'no-unmodified-loop-condition': 'error',
		'no-unused-expressions': ['error', { allowShortCircuit: true, allowTernary: true }],
		'no-useless-concat': 'error',
		'no-useless-return': 'error',
		radix: 'error',
		yoda: 'error',
		// Code style
		'array-bracket-spacing': ['error', 'never'],
		'block-spacing': ['error', 'always'],
		'brace-style': ['error', '1tbs', { allowSingleLine: true }],
		// Snake_case enforcement for Frappe/ERPNext framework compatibility
		// Replaces camelcase rule to align with framework conventions and E-Boekhouden API
		camelcase: ['error', {
			properties: 'never',
			ignoreDestructuring: true,
			ignoreImports: true,
			ignoreGlobals: true,
			// Allow snake_case patterns (standard for Frappe), PascalCase (classes), and CONSTANTS
			allow: ['^[a-z]+(_[a-z0-9]+)*$', '^[A-Z][a-zA-Z0-9]*$', '^[A-Z_]+$', '^__.*__$']
		}],
		'comma-dangle': ['error', 'never'],
		'comma-spacing': ['error', { before: false, after: true }],
		'comma-style': ['error', 'last'],
		'computed-property-spacing': ['error', 'never'],
		'func-call-spacing': ['error', 'never'],
		'key-spacing': ['error', { beforeColon: false, afterColon: true }],
		'keyword-spacing': ['error', { before: true, after: true }],
		'max-len': ['warn', {
			code: 120,
			tabWidth: 4,
			ignoreUrls: true,
			ignoreComments: false,
			ignoreRegExpLiterals: true,
			ignoreStrings: true,
			ignoreTemplateLiterals: true
		}],
		'new-cap': ['error', { newIsCap: true, capIsNew: false, properties: true }],
		'new-parens': 'error',
		'no-array-constructor': 'error',
		'no-mixed-spaces-and-tabs': 'error',
		'no-multiple-empty-lines': ['error', { max: 2, maxBOF: 0, maxEOF: 0 }],
		'no-new-object': 'error',
		'no-tabs': 'off',
		'no-trailing-spaces': 'error',
		'no-unneeded-ternary': ['error', { defaultAssignment: false }],
		'no-whitespace-before-property': 'error',
		'object-curly-spacing': ['error', 'always'],
		'one-var': ['error', 'never'],
		'operator-assignment': ['error', 'always'],
		'operator-linebreak': ['error', 'before'],
		'padded-blocks': ['error', 'never'],
		'quote-props': ['error', 'as-needed', { keywords: false, unnecessary: true, numbers: false }],
		'semi-spacing': ['error', { before: false, after: true }],
		'space-before-blocks': 'error',
		'space-before-function-paren': ['error', { anonymous: 'always', named: 'never', asyncArrow: 'always' }],
		'space-in-parens': ['error', 'never'],
		'space-infix-ops': 'error',
		'space-unary-ops': ['error', { words: true, nonwords: false }],
		'spaced-comment': ['error', 'always', { line: { markers: ['*package', '!', '/', ',', '='] } }],
		// ES6+
		'arrow-spacing': ['error', { before: true, after: true }],
		'constructor-super': 'error',
		'generator-star-spacing': ['error', { before: false, after: true }],
		'no-class-assign': 'error',
		'no-confusing-arrow': ['error', { allowParens: true }],
		'no-const-assign': 'error',
		'no-dupe-class-members': 'error',
		'no-duplicate-imports': 'error',
		'no-new-symbol': 'error',
		'no-this-before-super': 'error',
		'no-useless-computed-key': 'error',
		'no-useless-constructor': 'error',
		'no-useless-rename': ['error', { ignoreDestructuring: false, ignoreImport: false, ignoreExport: false }],
		'no-var': 'warn',
		'object-shorthand': ['error', 'always', { ignoreConstructors: false, avoidQuotes: true }],
		'prefer-arrow-callback': ['error', { allowNamedFunctions: false, allowUnboundThis: true }],
		'prefer-const': ['error', { destructuring: 'any', ignoreReadBeforeAssign: true }],
		'prefer-numeric-literals': 'error',
		'prefer-rest-params': 'error',
		'prefer-spread': 'error',
		'prefer-template': 'error',
		'rest-spread-spacing': ['error', 'never'],
		'symbol-description': 'error',
		'template-curly-spacing': 'error',
		'yield-star-spacing': ['error', 'after'],
		// Additional best practices
		'no-delete-var': 'error',
		'no-label-var': 'error',
		'no-restricted-globals': ['error', 'event', 'fdescribe'],
		'no-shadow': ['error', { builtinGlobals: false, hoist: 'functions', allow: [] }],
		'no-shadow-restricted-names': 'error',
		'no-new-wrappers': 'error',
		'no-caller': 'error',
		'no-extend-native': 'error',
		'no-extra-bind': 'error',
		'no-invalid-this': 'error',
		'no-multi-spaces': 'error',
		'no-multi-str': 'error',
		'no-global-assign': 'error',
		// Vue-specific rules
		'vue/no-v-html': 'off',
		'vue/no-mutating-props': 'off',
		'vue/multi-word-component-names': 'off',
		'vue/html-indent': ['error', 'tab'],
		'vue/max-attributes-per-line': ['error', {
			singleline: 3,
			multiline: 1
		}]
		// Additional security best practices (already defined above)
		// 'no-eval': 'error',
		// 'no-implied-eval': 'error',
	},
	overrides: [
		{
			files: ['**/*.test.js', '**/*.spec.js', '**/test_*.js', 'cypress/**/*.js'],
			env: {
				jest: true,
				mocha: true
			},
			rules: {
				'no-unused-expressions': 'off',
				'max-len': 'off',
				'no-console': 'off',
				'no-undef': 'off'
			}
		},
		{
			files: ['verenigingen/tests/frontend/**/*.js'],
			env: {
				jest: true,
				mocha: true
			},
			rules: {
				'no-unused-expressions': 'off',
				'max-len': 'off',
				'no-console': 'off',
				'no-undef': 'off'
			}
		},
		{
			files: ['verenigingen/public/js/**/*.js'],
			rules: {
				'no-implicit-globals': 'error',
				'prefer-const': 'warn'
			}
		},
		{
			files: ['verenigingen/verenigingen/doctype/**/*.js'],
			rules: {
				'no-implicit-globals': 'warn'
			}
		}
	]
};
