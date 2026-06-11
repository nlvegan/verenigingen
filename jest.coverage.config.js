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
 *      guarding against overall regression. Set just below measured reality
 *      (stmts 7.6 / branch 7.2 / func 6.4 / lines 7.9).
 *   2. A PER-FILE ratchet on each module with real direct unit tests, set just
 *      below its measured coverage — today iban-validator.js (91.3/77.8/100/91.3).
 *      As services/utils gain direct unit tests, add a per-file key at its
 *      measured floor and raise existing floors.
 *
 * NOTE: per-file (and glob) threshold keys require @jest/reporters to use glob@7
 * — jest 29's threshold checker calls `glob.default.sync()`, which the default
 * glob@10 (exports `globSync`, no `.default.sync`) throws on. That's pinned via
 * the `@jest/reporters > glob` nested override in package.json.
 */

const base = require("./jest.config");

module.exports = {
  ...base,
  coverageThreshold: {
    "./verenigingen/public/js": {
      statements: 7,
      branches: 7,
      functions: 6,
      lines: 7,
    },
    "./verenigingen/public/js/utils/iban-validator.js": {
      statements: 90,
      branches: 75,
      functions: 90,
      lines: 90,
    },
  },
};
