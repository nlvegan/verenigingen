/**
 * @fileoverview Unit tests for volunteer-skill collection on the public
 * membership application form.
 *
 * Business context: the applicant ticks skills on step "Volunteering" of
 * /apply_for_membership. Those skills are the only thing that lets a chapter
 * match a new volunteer to work, so losing them silently costs the
 * association the whole point of asking.
 *
 * The markup below mirrors what `apply_for_membership.html` renders: skills
 * are CHECKBOXES named `volunteer_skills[]` whose value is
 * `"<category>|<skill>"`, plus one page-wide `#volunteer_skill_level` select.
 * `TestPageApplyForMembership` in tests/backend/portal/test_page_portal_cluster.py
 * checks the same hooks against the RENDERED page, and checks the category
 * and level vocabularies against the Select options they are stored into.
 */

const fs = require('fs');
const path = require('path');

require('../../public/js/membership_application.js');

const { getVolunteerSkills } = window.MembershipApplication.prototype;

/**
 * Render the skills fieldset the way the Jinja template does.
 *
 * @param {Array<[string, string, boolean]>} skills - [category, skill, checked]
 * @param {string} level - value of the page-wide proficiency select
 */
function renderSkillsStep(skills, level) {
	const boxes = skills
		.map(
			([category, skill, checked]) =>
				`<label><input type="checkbox" name="volunteer_skills[]"
				  value="${category}|${skill}" ${checked ? 'checked' : ''}><span>${skill}</span></label>`
		)
		.join('');

	document.body.innerHTML = `
		<div id="skills-selection">${boxes}</div>
		<select id="volunteer_skill_level" name="volunteer_skill_level">
			<option value="">Select your overall experience level...</option>
			<option value="1 - Beginner">1 - Beginner (Learning and eager to help)</option>
			<option value="3 - Intermediate">3 - Intermediate (Solid experience in several areas)</option>
		</select>
	`;
	document.getElementById('volunteer_skill_level').value = level;
}

describe('getVolunteerSkills', () => {
	afterEach(() => {
		document.body.innerHTML = '';
	});

	it('collects every ticked skill with its name, category and level', () => {
		renderSkillsStep(
			[
				['Technical', 'Web Development', true],
				['Communication', 'Public Speaking', true],
				['Financial', 'Bookkeeping', false]
			],
			'3 - Intermediate'
		);

		expect(getVolunteerSkills.call({})).toEqual([
			{ name: 'Web Development', category: 'Technical', level: '3 - Intermediate' },
			{ name: 'Public Speaking', category: 'Communication', level: '3 - Intermediate' }
		]);
	});

	it('ignores skills the applicant did not tick', () => {
		renderSkillsStep([['Technical', 'Web Development', false]], '1 - Beginner');

		expect(getVolunteerSkills.call({})).toEqual([]);
	});

	it('keeps the skill when no overall level was chosen', () => {
		renderSkillsStep([['Technical', 'Web Development', true]], '');

		expect(getVolunteerSkills.call({})).toEqual([{ name: 'Web Development', category: 'Technical', level: '' }]);
	});
});

describe('the page this collector reads', () => {
	// The markup above is a copy, and a copy agrees with the page only by
	// spelling. #201 was exactly that: the collector queried `.skill-row` and
	// `skill_name[]`, selectors apply_for_membership.html has never rendered,
	// and nothing anywhere compared the two. Read the real template.
	const template = fs.readFileSync(path.join(__dirname, '../../templates/pages/apply_for_membership.html'), 'utf8');

	it.each(['name="volunteer_skills[]"', 'id="volunteer_skill_level"'])(
		'renders %s, which getVolunteerSkills() queries',
		(hook) => {
			expect(template).toContain(hook);
		}
	);
});
