/**
 * @fileoverview Unit tests for volunteer-interest-area collection on the
 * public membership application form.
 *
 * Business context: the applicant ticks areas of interest on step
 * "Volunteering" of /apply_for_membership, alongside skills (#409). Losing
 * them silently means the association never learns what a new volunteer
 * wants to help with.
 *
 * #410: the collector queried `#volunteer-interests`, an id the page never
 * renders -- the real checkboxes are `name="volunteer_areas[]"`, matching
 * `apply_for_membership.html`. This mirrors
 * membership-application-volunteer-skills.test.js's structure for the
 * sibling bug.
 */

const fs = require('fs');
const path = require('path');

require('../../public/js/membership_application.js');

const { getSelectedVolunteerInterests } = window.MembershipApplication.prototype;

/**
 * Render the interest-areas fieldset the way the Jinja template does.
 *
 * @param {Array<[string, boolean]>} areas - [value, checked]
 */
function renderInterestAreasStep(areas) {
	const boxes = areas
		.map(
			([value, checked]) =>
				`<label><input type="checkbox" name="volunteer_areas[]"
				  value="${value}" ${checked ? 'checked' : ''}><span>${value}</span></label>`
		)
		.join('');

	document.body.innerHTML = `<div id="volunteer-areas">${boxes}</div>`;
}

describe('getSelectedVolunteerInterests', () => {
	afterEach(() => {
		document.body.innerHTML = '';
	});

	it('collects every ticked area of interest', () => {
		renderInterestAreasStep([
			['events', true],
			['communications', false],
			['fundraising', true],
			['outreach', false]
		]);

		expect(getSelectedVolunteerInterests.call({})).toEqual(['events', 'fundraising']);
	});

	it('returns an empty list when nothing is ticked', () => {
		renderInterestAreasStep([
			['events', false],
			['communications', false]
		]);

		expect(getSelectedVolunteerInterests.call({})).toEqual([]);
	});
});

describe('the page this collector reads', () => {
	// A hand-written fixture only agrees with the page by spelling; #201 and
	// #410 were both exactly that mismatch, and nothing compared the two.
	// Read the real template.
	const template = fs.readFileSync(path.join(__dirname, '../../templates/pages/apply_for_membership.html'), 'utf8');

	it('renders name="volunteer_areas[]", which getSelectedVolunteerInterests() queries', () => {
		expect(template).toContain('name="volunteer_areas[]"');
	});

	it('does not render #volunteer-interests as an id (the selector this collector abandoned)', () => {
		expect(template).not.toContain('id="volunteer-interests"');
	});

	it('renders exactly the checkbox values VOLUNTEER_INTEREST_AREA_MAP declares', () => {
		// application_helpers.py's VOLUNTEER_INTEREST_AREA_MAP is a closed set:
		// a checkbox value it does not recognise is silently dropped server-side
		// rather than stored, so a checkbox added or renamed here without
		// updating that map would silently stop reaching any Volunteer record.
		const renderedValues = Array.from(template.matchAll(/name="volunteer_areas\[\]"\s+value="([^"]+)"/g))
			.map((match) => match[1])
			.sort();

		expect(renderedValues).toEqual(['communications', 'events', 'fundraising', 'outreach']);
	});
});
