/**
 * @fileoverview Jest config for the ENFORCED coverage gate.
 *
 * Extends the base jest.config.js and adds coverageThreshold. Used only by
 * `npm run test:coverage` (the full unit suite), so the gate is evaluated
 * against complete coverage. The base config intentionally omits the threshold
 * so targeted `--coverage` runs (e.g. CI contract-test subsets) report coverage
 * without failing on a partial run that never exercises the gated module.
 *
 * Two tiers:
 *   1. A DIRECTORY floor over the whole instrumentable layer (public/js),
 *      guarding against overall regression. Set a few points below measured
 *      reality (stmts 96.5 / branch 89.5 / func 99.1 / lines 96.4 as of the
 *      2026-06-12 ratchet, when every module under public/js gained real
 *      direct-import unit tests).
 *   2. A PER-FILE ratchet on each instrumented module, set just below its
 *      measured coverage so a regression in any one file trips the gate even if
 *      the directory average masks it. Raise these as coverage improves; never
 *      lower one to make a regression pass — fix the test instead.
 *
 * NOTE: per-file (and glob) threshold keys require @jest/reporters to use glob@7
 * — jest 29's threshold checker calls `glob.default.sync()`, which the default
 * glob@10 (exports `globSync`, no `.default.sync`) throws on. That's pinned via
 * the `@jest/reporters > glob` nested override in package.json.
 */

const base = require('./jest.config');

module.exports = {
	...base,
	coverageThreshold: {
		// Tier 1: directory floor over the whole instrumentable layer.
		'./verenigingen/public/js': {
			statements: 94,
			branches: 86,
			functions: 96,
			lines: 94
		},
		// Tier 2: per-file ratchets (measured value in trailing comment).
		'./verenigingen/public/js/services/api-service.js': {
			statements: 96, // 97.89
			branches: 93, // 96.87
			functions: 95, // 96.66
			lines: 96 // 97.82
		},
		'./verenigingen/public/js/services/storage-service.js': {
			statements: 92, // 94.91
			branches: 79, // 82.97
			functions: 98, // 100
			lines: 92 // 94.73
		},
		'./verenigingen/public/js/services/validation-service.js': {
			statements: 95, // 97.01
			branches: 84, // 87.77
			functions: 98, // 100
			lines: 95 // 96.99
		},
		'./verenigingen/public/js/utils/iban-validator.js': {
			statements: 90, // 91.3
			branches: 75, // 77.77
			functions: 90, // 100
			lines: 90 // 91.3
		},
		'./verenigingen/public/js/utils/iban-masking.js': {
			statements: 98, // 100
			branches: 96, // 100
			functions: 100, // 100
			lines: 98 // 100
		},
		'./verenigingen/public/js/utils/operation-result-helpers.js': {
			statements: 98, // 100
			branches: 90, // 93.84
			functions: 100, // 100
			lines: 98 // 100
		},
		'./verenigingen/public/js/utils/password_autofill_suppression.js': {
			statements: 98, // 100
			branches: 96, // 100
			functions: 100, // 100
			lines: 98 // 100
		}
	}
};
