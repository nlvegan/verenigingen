/* global describe, it, expect */
/**
 * Guard for #1475 / #1454: CI runs jest with --testMatch='**\/tests/unit/**\/*.test.js', which
 * REPLACES jest.config.js's testMatch. A unit test saved as test_*.js (no .test.js suffix) is
 * therefore never collected, and its failures are invisible.
 */
const fs = require('fs');
const path = require('path');

function walk(dir) {
	return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
		const full = path.join(dir, entry.name);
		return entry.isDirectory() ? walk(full) : [full];
	});
}

describe('tests/unit file naming', () => {
	it('has no test_*.js file that CI would not collect', () => {
		const files = walk(__dirname);
		expect(files.length).toBeGreaterThan(10); // control: the walk really sees the tree

		const invisible = files
			.filter((f) => /(^|\/)test_[^/]*\.js$/.test(f) && !f.endsWith('.test.js'))
			.map((f) => path.relative(__dirname, f));

		expect(invisible).toEqual([]);
	});
});
