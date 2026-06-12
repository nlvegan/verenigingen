/**
 * @fileoverview ESLint flat configuration for the Verenigingen association app.
 *
 * Migrated from the legacy `.eslintrc.js` (eslintrc format) to the flat config
 * format required by ESLint v9+. Behaviour is preserved: same recommended bases
 * (eslint:recommended + eslint-plugin-vue Vue 3 recommended), the same Frappe /
 * app globals, the same rule set, and the same per-path overrides — translated
 * one-to-one into flat config entries (env -> languageOptions.globals,
 * extends -> imported config arrays, overrides -> ordered config objects).
 *
 * Notes for maintainers:
 * - `--ext` is gone in flat config; file selection is driven by the `files`
 *   globs here, so `npm run lint` is just `eslint verenigingen`.
 * - Later entries override earlier ones, so the override blocks at the bottom
 *   keep the same precedence they had under eslintrc `overrides`.
 */

const js = require("@eslint/js");
const pluginVue = require("eslint-plugin-vue");
const globals = require("globals");
// Disables every stylistic ESLint rule that could conflict with Prettier.
// MUST be the final entry in the exported config array so it wins. Prettier now
// owns formatting (indent, quotes, semi, comma-dangle, object-curly-spacing,
// max-len, no-mixed-spaces-and-tabs, …); ESLint keeps only correctness rules.
const prettier = require("eslint-config-prettier");

// Frappe framework + Verenigingen app globals (verbatim from the old eslintrc
// `globals` block). Standard browser/node/jquery globals come from the
// `globals` package below, so only the framework/app-specific ones are listed.
const frappeGlobals = {
  frappe: "readonly",
  verenigingen: "readonly",
  frm: "readonly",
  cur_frm: "readonly",
  locals: "readonly",
  __: "readonly",
  cint: "readonly",
  cstr: "readonly",
  flt: "readonly",
  format_currency: "readonly",
  moment: "readonly",
  cur_page: "readonly",
  // Frappe UI globals
  Dialog: "readonly",
  msgprint: "readonly",
  show_alert: "readonly",
  // Testing globals not covered by the jest/mocha sets
  QUnit: "readonly",
  Cypress: "readonly",
  cy: "readonly",
  // Test utilities
  createTestMember: "readonly",
  waitForDialogs: "readonly",
  // Chart library
  Chart: "readonly",
  // Custom utilities
  update_other_members_at_address: "readonly",
  IBANValidator: "readonly",
  PaymentUtils: "readonly",
  SepaUtils: "readonly",
  VolunteerUtils: "readonly",
  ChapterUtils: "readonly",
  ChapterHistoryUtils: "readonly",
  ChapterConfig: "readonly",
  ChapterValidation: "readonly",
  TerminationUtils: "readonly",
  UIUtils: "readonly",
  // Service classes
  APIService: "readonly",
  ValidationService: "readonly",
  StorageService: "readonly",
  ErrorHandler: "readonly",
  StepManager: "readonly",
  // OperationResult helpers (window-attached in
  // public/js/utils/operation-result-helpers.js, consumed bare app-wide)
  unwrapOperationResult: "readonly",
  getErrorMessage: "readonly",
  // Membership application classes
  MembershipApplication: "readonly",
  PersonalInfoStep: "readonly",
  AddressStep: "readonly",
  MembershipStep: "readonly",
  VolunteerStep: "readonly",
  PaymentStep: "readonly",
  ConfirmationStep: "readonly",
  MembershipAPI: "readonly",
  membershipApp: "writable",
  UIManager: "readonly",
};

const mainRules = {
  // Basic formatting
  indent: [
    "error",
    "tab",
    {
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
      ignoreComments: false,
    },
  ],
  quotes: ["error", "single", { allowTemplateLiterals: true }],
  semi: ["error", "always"],
  "linebreak-style": ["error", "unix"],
  "eol-last": ["error", "always"],
  // Variable handling
  "no-unused-vars": [
    "error",
    {
      vars: "all",
      args: "after-used",
      ignoreRestSiblings: false,
      varsIgnorePattern: "^(frappe|frm|cur_frm|locals|__|_)",
      // Allow unused params that are framework-imposed signatures: Frappe form/
      // list handlers (frm, cdt, cdn, doc, df, listview, page) and jQuery ajax
      // callbacks (xhr, status) often carry args a given handler doesn't use.
      argsIgnorePattern:
        "^_|^(r|e|event|state|error|response|data|result|ctx|context|idx|index|frm|cdt|cdn|doc|df|field|listview|page|xhr|status)$|.*_data$|.*_response$|.*_result$",
      // Unused catch bindings (} catch (e) {) are idiomatic; don't flag them.
      caughtErrorsIgnorePattern: "^(e|err|error|_)$",
    },
  ],
  "no-undef": ["error", { typeof: false }],
  "no-undef-init": "error",
  "no-use-before-define": [
    "error",
    { functions: false, classes: false, variables: true },
  ],
  // Console and debugging
  "no-console": ["warn", { allow: ["warn", "error"] }],
  "no-debugger": "error",
  "no-alert": "off", // Allow confirm() and alert() for user interactions
  // Best practices
  eqeqeq: ["error", "always", { null: "ignore" }],
  curly: ["error", "all"],
  "no-eval": "error",
  "no-implied-eval": "error",
  "no-with": "error",
  "no-new-func": "error",
  "no-script-url": "error",
  "no-return-assign": "error",
  "no-self-compare": "error",
  "no-throw-literal": "error",
  "no-unmodified-loop-condition": "error",
  "no-unused-expressions": [
    "error",
    { allowShortCircuit: true, allowTernary: true },
  ],
  "no-useless-concat": "error",
  "no-useless-return": "error",
  radix: "error",
  yoda: "error",
  // Code style
  "array-bracket-spacing": ["error", "never"],
  "block-spacing": ["error", "always"],
  "brace-style": ["error", "1tbs", { allowSingleLine: true }],
  // Disable camelcase rule in favor of id-match for proper regex support
  camelcase: "off",

  // Snake_case enforcement for Frappe/ERPNext framework compatibility
  // Uses regex patterns to allow snake_case (Frappe standard), camelCase (JavaScript standard),
  // PascalCase (classes), and CONSTANTS. Also allows two established app conventions:
  // leading-underscore private members (_camelCase / _snake_case) and jQuery-cached
  // element vars prefixed with $ that may contain underscores ($snake_case).
  "id-match": [
    "error",
    "^([a-z]+(_[a-z0-9]+)*|[a-z][a-zA-Z0-9]*|[A-Z][a-zA-Z0-9]*|[A-Z_]+|__.*__|_[a-zA-Z][a-zA-Z0-9_]*|\\$[a-zA-Z][a-zA-Z0-9_]*)$",
    {
      properties: false,
      onlyDeclarations: false,
      ignoreDestructuring: true,
    },
  ],
  "comma-dangle": ["error", "never"],
  "comma-spacing": ["error", { before: false, after: true }],
  "comma-style": ["error", "last"],
  "computed-property-spacing": ["error", "never"],
  "func-call-spacing": ["error", "never"],
  "key-spacing": ["error", { beforeColon: false, afterColon: true }],
  "keyword-spacing": ["error", { before: true, after: true }],
  "max-len": [
    "warn",
    {
      code: 120,
      tabWidth: 4,
      ignoreUrls: true,
      ignoreComments: false,
      ignoreRegExpLiterals: true,
      ignoreStrings: true,
      ignoreTemplateLiterals: true,
    },
  ],
  "new-cap": ["error", { newIsCap: true, capIsNew: false, properties: true }],
  "new-parens": "error",
  "no-array-constructor": "error",
  "no-mixed-spaces-and-tabs": "error",
  "no-multiple-empty-lines": ["error", { max: 2, maxBOF: 0, maxEOF: 0 }],
  "no-new-object": "error",
  "no-tabs": "off",
  "no-trailing-spaces": "error",
  "no-unneeded-ternary": ["error", { defaultAssignment: false }],
  "no-whitespace-before-property": "error",
  "object-curly-spacing": ["error", "always"],
  "one-var": ["error", "never"],
  "operator-assignment": ["error", "always"],
  "operator-linebreak": ["error", "before"],
  "padded-blocks": ["error", "never"],
  "quote-props": [
    "error",
    "as-needed",
    { keywords: false, unnecessary: true, numbers: false },
  ],
  "semi-spacing": ["error", { before: false, after: true }],
  "space-before-blocks": "error",
  "space-before-function-paren": [
    "error",
    { anonymous: "always", named: "never", asyncArrow: "always" },
  ],
  "space-in-parens": ["error", "never"],
  "space-infix-ops": "error",
  "space-unary-ops": ["error", { words: true, nonwords: false }],
  "spaced-comment": [
    "error",
    "always",
    { line: { markers: ["*package", "!", "/", ",", "="] } },
  ],
  // ES6+
  "arrow-spacing": ["error", { before: true, after: true }],
  "constructor-super": "error",
  "generator-star-spacing": ["error", { before: false, after: true }],
  "no-class-assign": "error",
  "no-confusing-arrow": ["error", { allowParens: true }],
  "no-const-assign": "error",
  "no-dupe-class-members": "error",
  "no-duplicate-imports": "error",
  "no-new-symbol": "error",
  "no-this-before-super": "error",
  "no-useless-computed-key": "error",
  "no-useless-constructor": "error",
  "no-useless-rename": [
    "error",
    { ignoreDestructuring: false, ignoreImport: false, ignoreExport: false },
  ],
  "no-var": "warn",
  "object-shorthand": [
    "error",
    "always",
    { ignoreConstructors: false, avoidQuotes: true },
  ],
  "prefer-arrow-callback": [
    "error",
    { allowNamedFunctions: false, allowUnboundThis: true },
  ],
  "prefer-const": [
    "error",
    { destructuring: "any", ignoreReadBeforeAssign: true },
  ],
  "prefer-numeric-literals": "error",
  "prefer-rest-params": "error",
  "prefer-spread": "error",
  "prefer-template": "error",
  "rest-spread-spacing": ["error", "never"],
  "symbol-description": "error",
  "template-curly-spacing": "error",
  "yield-star-spacing": ["error", "after"],
  // Additional best practices
  "no-delete-var": "error",
  "no-label-var": "error",
  "no-restricted-globals": ["error", "event", "fdescribe"],
  "no-shadow": [
    "error",
    { builtinGlobals: false, hoist: "functions", allow: [] },
  ],
  "no-shadow-restricted-names": "error",
  "no-new-wrappers": "error",
  "no-caller": "error",
  "no-extend-native": "error",
  "no-extra-bind": "error",
  "no-invalid-this": "off", // Allow 'this' in DOM event handlers and jQuery callbacks
  "no-multi-spaces": "error",
  "no-multi-str": "error",
  "no-global-assign": "error",
  // Vue-specific rules
  "vue/no-v-html": "off",
  "vue/no-mutating-props": "off",
  "vue/multi-word-component-names": "off",
  "vue/html-indent": ["error", "tab"],
  "vue/max-attributes-per-line": [
    "error",
    {
      singleline: 3,
      multiline: 1,
    },
  ],
};

const testRules = {
  "no-unused-expressions": "off",
  "max-len": "off",
  "no-console": "off",
  "no-undef": "off",
  "no-use-before-define": "off",
  "no-unused-vars": "warn",
  radix: "off",
};

module.exports = [
  // Files/directories ESLint should not lint. Migrated from the (now
  // unsupported) `.eslintignore`; node_modules is also excluded by default.
  {
    ignores: [
      "**/node_modules/**",
      "package-lock.json",
      "yarn.lock",
      // Build outputs
      "**/dist/**",
      "**/build/**",
      "**/*.min.js",
      "**/*.bundle.js",
      // Archived and legacy code
      "**/archived_unused/**",
      "**/archived_removal/**",
      "**/legacy/**",
      // Third-party libraries
      "verenigingen/public/js/lib/**",
      "verenigingen/public/js/vendor/**",
      "**/vendor/**",
      // Generated files
      "**/*.generated.js",
      "**/*-compiled.js",
      // Test fixtures and mock data
      "verenigingen/tests/fixtures/**",
      "**/__mocks__/**",
      // Temporary files
      "**/*.tmp.js",
      "**/*.temp.js",
      // Documentation
      "docs/**",
      // Config files (different syntax / not app source)
      "*.config.js",
      "**/webpack.config.js",
      "**/rollup.config.js",
      // Scripts meant to be run directly (not through Frappe)
      "scripts/analysis/**",
      "scripts/monitoring/**",
      "scripts/performance/**",
      "scripts/rollback/**",
      "scripts/security/**",
      // Development and debug utilities
      "debug_utils/**",
      "dev_scripts/**",
      // Files with intentional issues for testing
      "**/test_field_validation_gaps.js",
      "**/intentional_errors.js",
      // Cypress artifacts
      "cypress/videos/**",
      "cypress/screenshots/**",
    ],
  },

  // Recommended bases (was: extends eslint:recommended + plugin:vue/vue3-recommended).
  js.configs.recommended,
  ...pluginVue.configs["flat/recommended"],

  // Base config applied to all linted files.
  {
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: {
        ...globals.browser,
        ...globals.node,
        ...globals.jquery,
        ...frappeGlobals,
      },
    },
    rules: mainRules,
  },

  // --- Per-path overrides (same order/precedence as the old eslintrc) ---

  // Test files (jest + mocha environments). Includes the jest setup/helper
  // files under tests/setup that aren't named test_*.js / *.test.js.
  {
    files: [
      "**/*.test.js",
      "**/*.spec.js",
      "**/test_*.js",
      "cypress/**/*.js",
      "verenigingen/tests/**/*.js",
    ],
    languageOptions: {
      globals: { ...globals.jest, ...globals.mocha },
    },
    rules: testRules,
  },
  {
    files: ["verenigingen/tests/frontend/**/*.js"],
    languageOptions: {
      globals: { ...globals.jest, ...globals.mocha },
    },
    rules: testRules,
  },

  // Public JS: forbid implicit globals, relax prefer-const to a warning.
  {
    files: ["verenigingen/public/js/**/*.js"],
    rules: {
      "no-implicit-globals": "error",
      "prefer-const": "warn",
    },
  },

  // DocType client scripts: implicit globals are common, warn only.
  {
    files: ["verenigingen/verenigingen/doctype/**/*.js"],
    rules: {
      "no-implicit-globals": "warn",
    },
  },

  // Large legacy entry points with known style debt.
  {
    files: ["verenigingen/public/js/membership_application.js"],
    rules: {
      "max-len": "off",
      camelcase: "off",
      "no-use-before-define": "off",
    },
  },
  {
    files: ["verenigingen/public/js/member_counter.js"],
    rules: {
      camelcase: "off",
    },
  },

  // eBoekhouden cleanup backups / migration tooling: generated/utility scripts.
  {
    files: ["verenigingen/e_boekhouden/cleanup_backups/**/*.js"],
    rules: {
      "no-console": "off",
      "no-unused-vars": "off",
      "max-len": "off",
      "no-shadow": "off",
      radix: "off",
    },
  },
  {
    files: ["verenigingen/e_boekhouden/doctype/e_boekhouden_migration/**/*.js"],
    rules: {
      "no-unused-vars": "warn",
      "max-len": "warn",
      "no-shadow": "warn",
    },
  },
  {
    files: ["verenigingen/verenigingen/page/system_health_dashboard/**/*.js"],
    rules: {
      "no-console": "off",
    },
  },

  // Testing helper scripts.
  {
    files: ["scripts/testing/**/*.js"],
    rules: {
      "no-unused-vars": "warn",
      "no-global-assign": "warn",
      "no-return-assign": "warn",
      "id-match": "warn",
    },
  },

  // Final broad relaxation for public JS + tests (kept last to win, as in the
  // old eslintrc where it was the final overrides entry).
  {
    files: ["verenigingen/public/js/**/*.js", "verenigingen/tests/**/*.js"],
    rules: {
      "id-match": "off",
      "no-console": "warn",
      "no-unused-vars": "warn",
      "no-redeclare": "warn",
      "no-case-declarations": "warn",
      radix: "warn",
      "max-len": "warn",
    },
  },

  // Prettier owns formatting — keep LAST so it turns off all stylistic rules
  // (see the require at the top of this file).
  prettier,
];
