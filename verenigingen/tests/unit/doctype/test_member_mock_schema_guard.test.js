/* eslint-env jest */
/**
 * @fileoverview Guard for #1186: Member mock docs must not carry fields that
 * are absent from member.json (see setup/member-schema-guard.js).
 */

const fs = require('fs');
const path = require('path');
const {
	REPO_ROOT,
	memberFieldnames,
	memberDocFieldRefs,
	phantomMemberFields
} = require('../../setup/member-schema-guard');

// Test files whose mock docs / filled fields are Member's.
const MEMBER_MOCK_FILES = [
	'verenigingen/tests/unit/doctype/test_member_controller.test.js',
	'verenigingen/tests/unit/doctype/test_member_controller_refactored.test.js',
	'verenigingen/tests/unit/doctype/test_member_controller_simple_contracts.test.js',
	'verenigingen/tests/unit/doctype/test_member_controller_api_contracts.test.js',
	'cypress/integration/member-controller.spec.js'
];

describe('Member mock docs only use fields that exist on Member (#1186)', () => {
	MEMBER_MOCK_FILES.forEach((rel) => {
		it(`${rel} has no phantom Member fields`, () => {
			const src = fs.readFileSync(path.join(REPO_ROOT, rel), 'utf8');
			const found = phantomMemberFields(src).map((r) => `${rel}:${r.line} ${r.field} (${r.via})`);

			expect(found).toEqual([]);
		});
	});

	describe('the scanner itself', () => {
		const fields = memberFieldnames();

		it('knows real Member fields (control: scan has something to compare against)', () => {
			expect(fields.has('birth_date')).toBe(true);
			expect(fields.has('current_membership_plan')).toBe(true);
			expect(fields.has('primary_chapter')).toBe(false);
		});

		it('flags a phantom key planted in each syntax the files use', () => {
			const planted = [
				"frm.doc.member_number = 'X';",
				'getControllerTest().mockForm.doc.is_volunteer = 1;',
				"cy.fill_frappe_field('auto_renewal', true);",
				"frm = createMockForm({\n\tdoc: {\n\t\tfirst_name: 'Jan',\n\t\tphone: '1'\n\t}\n});",
				"const memberConfig = {\n\tdefaultDoc: {\n\t\tpostal_code: '1012 AB'\n\t}\n};"
			];
			const expected = ['member_number', 'is_volunteer', 'auto_renewal', 'phone', 'postal_code'];

			planted.forEach((src, i) => {
				expect(phantomMemberFields(src, fields).map((r) => r.field)).toEqual([expected[i]]);
			});
		});

		it('does not flag real fields or nested payload keys (control)', () => {
			const src = [
				"frm.doc.birth_date = '1990-01-01';",
				'frm.doc.__islocal = 0;',
				"cy.fill_frappe_field('first_name', 'Jan');",
				"frm = createMockForm({\n\tdoc: {\n\t\tname: 'MEM-1',\n\t\tsepa_mandates: [{\n\t\t\tsepa_mandate: 'S-1'\n\t\t}]\n\t}\n});"
			].join('\n');

			expect(memberDocFieldRefs(src).length).toBeGreaterThanOrEqual(5);
			expect(phantomMemberFields(src, fields)).toEqual([]);
		});
	});
});
