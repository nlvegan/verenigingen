/**
 * @fileoverview Chapter Geographic Management E2E Tests - JavaScript Controller Testing
 *
 * This comprehensive test suite validates the Chapter DocType JavaScript controllers
 * and geographic management functionality within the Frappe framework. Tests focus
 * on real Dutch geographic data, postal code management, and chapter organization
 * workflows without mocking.
 *
 * Business Context:
 * The Chapter system organizes members geographically across the Netherlands,
 * managing postal code ranges, board member assignments, and regional coordination.
 * This is critical for local chapter governance and member service delivery.
 *
 * Test Strategy:
 * - Tests run against real Chapter DocType JavaScript controllers
 * - Uses authentic Dutch postal codes and geographic data
 * - Validates JavaScript postal code validation and overlap detection
 * - Tests geographic assignment algorithms and UI interactions
 * - Verifies board management and governance workflows
 *
 * Prerequisites:
 * - Development server with geographic data configuration
 * - Sample members distributed across Dutch postal codes
 * - Test board members with appropriate roles
 * - Valid chapter configuration templates
 *
 * @author Verenigingen Test Team
 * @version 1.0.0
 * @since 2025-08-19
 */

describe('Chapter Geographic Management - JavaScript Controller Tests', () => {
	beforeEach(() => {
		// Login with chapter management privileges
		cy.login('administrator@example.com', 'admin');

		// Ensure clean state for geographic tests
		cy.clearLocalStorage();
		cy.clearCookies();

		// Clear test data to prevent postal code conflicts
		cy.clear_test_data();
	});

	describe('Chapter Creation and Geographic Configuration', () => {
		it('should create new chapter with postal code validation via JavaScript', () => {
			// Navigate to Chapter DocType
			cy.visit('/app/chapter');
			cy.wait(2000);

			// Create new chapter
			cy.get('button[data-label="Add Chapter"]').should('be.visible').click();
			cy.wait(1000);

			// Test that Chapter JavaScript controller loaded correctly
			cy.window().then((win) => {
				expect(win.frappe.ui.form.get_form('Chapter')).to.exist;
				expect(win.ChapterUtils).to.exist;
				expect(win.PostalCodeUtils).to.exist;
			});

			// Fill chapter details with realistic Dutch data
			const chapterData = {
				chapter_name: 'Amsterdam Noord Chapter',
				description: 'Chapter serving Amsterdam Noord district and surrounding areas',
				city: 'Amsterdam',
				region: 'Noord-Holland',
				meeting_location: 'Gemeenschapscentrum Noord',
				meeting_address: 'Buikslotermeerplein 1, 1025 XE Amsterdam'
			};

			// Fill basic chapter information
			Object.keys(chapterData).forEach(field => {
				if (chapterData[field]) {
					cy.fill_field(field, chapterData[field]);
				}
			});

			// Test postal code range configuration with JavaScript validation
			cy.get('button[data-label="Configure Postal Codes"]').click();
			cy.wait(1000);

			// Add multiple postal code ranges for Amsterdam Noord
			const postalRanges = [
				{ from: '1020', to: '1029', description: 'Amsterdam Noord-West' },
				{ from: '1030', to: '1039', description: 'Amsterdam Noord-Oost' },
				{ from: '1010', to: '1019', description: 'Amsterdam Centrum-Noord' }
			];

			postalRanges.forEach((range, index) => {
				cy.get('button[data-label="Add Postal Range"]').click();

				cy.get(`[data-idx="${index}"] input[data-fieldname="postal_code_from"]`).type(range.from);
				cy.get(`[data-idx="${index}"] input[data-fieldname="postal_code_to"]`).type(range.to);
				cy.get(`[data-idx="${index}"] input[data-fieldname="range_description"]`).type(range.description);

				// Test JavaScript range validation
				cy.get(`[data-idx="${index}"] .range-validation-status`).should('contain', 'Valid range');
			});

			// Test JavaScript overlap detection
			cy.get('button[data-label="Validate Postal Ranges"]').click();
			cy.wait(2000);

			cy.get('.validation-results').should('be.visible');
			cy.get('.overlap-status').should('contain', 'No overlaps detected');
			cy.get('.coverage-summary').should('contain', '30 postal codes covered');

			// Save chapter
			cy.save();
			cy.wait(2000);

			// Verify JavaScript initialization completed
			cy.get('.chapter-overview-card').should('be.visible');
			cy.get('.postal-coverage-map').should('be.visible');
			cy.get('[data-fieldname="total_postal_codes"]').should('have.value', '30');
		});

		it('should detect postal code overlaps with existing chapters', () => {
			// First create an existing chapter with specific postal codes
			cy.createTestChapter({
				chapter_name: 'Existing Amsterdam Chapter',
				postal_ranges: [{ from: '1000', to: '1019' }]
			});

			// Create new chapter that would overlap
			cy.visit('/app/chapter/new');
			cy.wait(2000);

			cy.fill_field('chapter_name', 'Conflicting Chapter');
			cy.fill_field('city', 'Amsterdam');

			// Configure overlapping postal range
			cy.get('button[data-label="Configure Postal Codes"]').click();
			cy.get('button[data-label="Add Postal Range"]').click();

			cy.get('[data-idx="0"] input[data-fieldname="postal_code_from"]').type('1010');
			cy.get('[data-idx="0"] input[data-fieldname="postal_code_to"]').type('1025');

			// Test JavaScript overlap detection
			cy.get('button[data-label="Validate Postal Ranges"]').click();
			cy.wait(2000);

			// Verify JavaScript detects conflict
			cy.get('.validation-results').should('be.visible');
			cy.get('.overlap-warning').should('be.visible');
			cy.get('.overlap-details').should('contain', 'Existing Amsterdam Chapter');
			cy.get('.overlap-codes').should('contain', '1010-1019');

			// Verify save is prevented
			cy.get('button[data-label="Save"]').should('be.disabled');
			cy.get('.save-warning').should('contain', 'Resolve postal code conflicts');
		});
	});

	describe('Member Assignment and Geographic Logic', () => {
		it('should automatically assign members to chapters based on postal codes', () => {
			// Create chapter with specific postal code coverage
			cy.createTestChapter({
				chapter_name: 'Utrecht Central Chapter',
				postal_ranges: [{ from: '3500', to: '3599' }]
			});

			// Create test members in Utrecht area
			const utrechtMembers = [
				{
					first_name: 'Jan',
					last_name: 'Bakker',
					postal_code: '3511 LX',
					city: 'Utrecht',
					email: `jan.bakker.${Date.now()}@example.com`
				},
				{
					first_name: 'Sara',
					last_name: 'de Vries',
					postal_code: '3545 CH',
					city: 'Utrecht',
					email: `sara.devries.${Date.now()}@example.com`
				}
			];

			utrechtMembers.forEach(member => {
				cy.createTestMember(member);
			});

			// Test automatic assignment via Chapter JavaScript
			cy.visit('/app/chapter/Utrecht%20Central%20Chapter');
			cy.wait(2000);

			// Trigger member assignment process
			cy.get('button[data-label="Assign Eligible Members"]').click();
			cy.wait(3000);

			// Verify JavaScript member assignment logic
			cy.get('.assignment-results').should('be.visible');
			cy.get('.members-assigned-count').should('contain', '2');

			// Check member assignment details
			cy.get('.assigned-members-list').should('contain', 'Jan Bakker');
			cy.get('.assigned-members-list').should('contain', 'Sara de Vries');

			// Verify postal code matching logic
			cy.get('.assignment-details').should('contain', '3511 LX → Utrecht Central Chapter');
			cy.get('.assignment-details').should('contain', '3545 CH → Utrecht Central Chapter');

			// Test chapter member count updates
			cy.get('[data-fieldname="active_members_count"]').should('have.value', '2');
			cy.get('.chapter-statistics').should('contain', 'Total Members: 2');
		});

		it('should handle members outside chapter coverage areas', () => {
			// Create chapter with limited coverage
			cy.createTestChapter({
				chapter_name: 'Rotterdam Port Chapter',
				postal_ranges: [{ from: '3000', to: '3099' }]
			});

			// Create members both inside and outside coverage
			const mixedMembers = [
				{
					first_name: 'Inside',
					last_name: 'Coverage',
					postal_code: '3011 AB', // Inside Rotterdam Port range
					city: 'Rotterdam'
				},
				{
					first_name: 'Outside',
					last_name: 'Coverage',
					postal_code: '2500 GA', // Den Haag - outside range
					city: 'Den Haag'
				}
			];

			mixedMembers.forEach(member => {
				cy.createTestMember(member);
			});

			cy.visit('/app/chapter/Rotterdam%20Port%20Chapter');
			cy.wait(2000);

			// Test assignment with exclusions
			cy.get('button[data-label="Assign Eligible Members"]').click();
			cy.wait(3000);

			// Verify JavaScript correctly identifies eligible and ineligible members
			cy.get('.assignment-results').should('be.visible');
			cy.get('.members-assigned-count').should('contain', '1');
			cy.get('.members-excluded-count').should('contain', '1');

			// Check specific assignment details
			cy.get('.assigned-members-list').should('contain', 'Inside Coverage');
			cy.get('.excluded-members-list').should('contain', 'Outside Coverage');
			cy.get('.exclusion-reason').should('contain', '2500 GA not in chapter range');

			// Test suggestion for uncovered members
			cy.get('.coverage-suggestions').should('be.visible');
			cy.get('.suggested-chapter').should('contain', 'Consider creating Den Haag chapter');
		});
	});

	describe('Board Member Management and Governance', () => {
		it('should manage chapter board members with role validation', () => {
			cy.createTestChapter({
				chapter_name: 'Groningen Chapter',
				postal_ranges: [{ from: '9700', to: '9799' }]
			});

			// Create test members eligible for board positions
			const boardCandidates = [
				{
					first_name: 'Board',
					last_name: 'President',
					email: 'president@groningen.chapter.com',
					member_since: '2020-01-01' // Long-standing member
				},
				{
					first_name: 'Board',
					last_name: 'Secretary',
					email: 'secretary@groningen.chapter.com',
					member_since: '2021-06-01'
				}
			];

			boardCandidates.forEach(member => {
				cy.createTestMember(member);
			});

			cy.visit('/app/chapter/Groningen%20Chapter');
			cy.wait(2000);

			// Test board member assignment functionality
			cy.get('button[data-label="Manage Board"]').click();
			cy.wait(1000);

			// Add president
			cy.get('button[data-label="Add Board Member"]').click();
			cy.get('[data-idx="0"] input[data-fieldname="member"]').type('Board President');
			cy.wait(500);
			cy.get('.awesomplete li').first().click();

			cy.get('[data-idx="0"] select[data-fieldname="role"]').select('President');
			cy.get('[data-idx="0"] input[data-fieldname="start_date"]').type('2025-01-01');
			cy.get('[data-idx="0"] input[data-fieldname="end_date"]').type('2026-12-31');

			// Test JavaScript role validation
			cy.get('[data-idx="0"] .role-validation-status').should('contain', 'Valid assignment');

			// Add secretary
			cy.get('button[data-label="Add Board Member"]').click();
			cy.get('[data-idx="1"] input[data-fieldname="member"]').type('Board Secretary');
			cy.wait(500);
			cy.get('.awesomplete li').first().click();

			cy.get('[data-idx="1"] select[data-fieldname="role"]').select('Secretary');
			cy.get('[data-idx="1"] input[data-fieldname="start_date"]').type('2025-01-01');
			cy.get('[data-idx="1"] input[data-fieldname="end_date"]').type('2026-12-31');

			// Test role conflict detection (try to add another president)
			cy.get('button[data-label="Add Board Member"]').click();
			cy.get('[data-idx="2"] input[data-fieldname="member"]').type('Board President');
			cy.wait(500);
			cy.get('.awesomplete li').first().click();

			cy.get('[data-idx="2"] select[data-fieldname="role"]').select('President');

			// Verify JavaScript conflict detection
			cy.get('[data-idx="2"] .role-conflict-warning').should('be.visible');
			cy.get('[data-idx="2"] .role-conflict-warning').should('contain', 'President role already assigned');

			// Save board configuration
			cy.get('button[data-label="Save Board"]').click();
			cy.wait(2000);

			// Verify board member summary
			cy.get('.board-summary-card').should('be.visible');
			cy.get('.board-member-count').should('contain', '2 active board members');
			cy.get('.current-president').should('contain', 'Board President');
			cy.get('.current-secretary').should('contain', 'Board Secretary');
		});

		it('should handle board member term management and transitions', () => {
			cy.createTestChapterWithBoard({
				chapter_name: 'Maastricht Chapter',
				board_members: [
					{
						member_name: 'Outgoing President',
						role: 'President',
						start_date: '2023-01-01',
						end_date: '2025-08-15' // Term ending soon
					}
				]
			});

			cy.visit('/app/chapter/Maastricht%20Chapter');
			cy.wait(2000);

			// Test term expiration warning
			cy.get('.board-alerts').should('be.visible');
			cy.get('.term-expiration-warning').should('contain', 'President term expires in');

			// Test board transition workflow
			cy.get('button[data-label="Manage Board Transitions"]').click();
			cy.wait(1000);

			// Add incoming president
			cy.get('button[data-label="Add Incoming Board Member"]').click();
			cy.get('.incoming-member input[data-fieldname="member"]').type('New President');
			cy.get('.incoming-member select[data-fieldname="role"]').select('President');
			cy.get('.incoming-member input[data-fieldname="start_date"]').type('2025-08-16');
			cy.get('.incoming-member input[data-fieldname="end_date"]').type('2027-08-15');

			// Test JavaScript transition validation
			cy.get('.transition-validation').should('be.visible');
			cy.get('.transition-status').should('contain', 'Smooth transition planned');
			cy.get('.overlap-warning').should('not.exist');

			// Process transition
			cy.get('button[data-label="Process Transition"]').click();
			cy.wait(2000);

			// Verify JavaScript updates board status
			cy.get('.transition-complete').should('be.visible');
			cy.get('.current-president').should('contain', 'New President');
			cy.get('.former-president').should('contain', 'Outgoing President');

			// Check board history tracking
			cy.get('.board-history-timeline').should('contain', 'President transition');
		});
	});

	describe('Chapter JavaScript Controller Integration Tests', () => {
		it('should test Chapter DocType refresh event handlers and module loading', () => {
			cy.createTestChapter({
				chapter_name: 'JavaScript Test Chapter',
				status: 'Active'
			});

			cy.visit('/app/chapter/JavaScript%20Test%20Chapter');
			cy.wait(2000);

			// Test JavaScript controller and module loading
			cy.window().then((win) => {
				expect(win.frappe.ui.form.get_form('Chapter')).to.exist;
				expect(win.ChapterUtils).to.exist;
				expect(win.PostalCodeUtils).to.exist;
				expect(win.BoardManagementUtils).to.exist;
			});

			// Test form refresh triggers JavaScript initialization
			cy.get('button[data-label="Refresh"]').click();
			cy.wait(1000);

			// Verify JavaScript-generated UI components
			cy.get('.chapter-overview-card').should('be.visible');
			cy.get('.postal-coverage-summary').should('be.visible');
			cy.get('.member-statistics-card').should('be.visible');
			cy.get('.board-status-indicator').should('be.visible');

			// Test status-based button visibility
			cy.get('button[data-label="Configure Postal Codes"]').should('be.visible');
			cy.get('button[data-label="Assign Eligible Members"]').should('be.visible');
			cy.get('button[data-label="Manage Board"]').should('be.visible');
		});

		it('should test postal code field validation and geographic calculations', () => {
			cy.visit('/app/chapter/new');
			cy.wait(2000);

			cy.fill_field('chapter_name', 'Postal Code Test Chapter');

			// Test postal code range validation
			cy.get('button[data-label="Configure Postal Codes"]').click();
			cy.get('button[data-label="Add Postal Range"]').click();

			// Test invalid range (from > to)
			cy.get('[data-idx="0"] input[data-fieldname="postal_code_from"]').type('1050');
			cy.get('[data-idx="0"] input[data-fieldname="postal_code_to"]').type('1040');

			// Verify JavaScript validation
			cy.get('[data-idx="0"] .range-validation-status').should('contain', 'Invalid range');
			cy.get('[data-idx="0"] .validation-error').should('contain', 'From code must be less than to code');

			// Test valid range
			cy.get('[data-idx="0"] input[data-fieldname="postal_code_to"]').clear().type('1060');
			cy.get('[data-idx="0"] .range-validation-status').should('contain', 'Valid range');

			// Test JavaScript coverage calculation
			cy.get('.coverage-calculator').should('contain', '11 postal codes');

			// Test adding overlapping range within same chapter
			cy.get('button[data-label="Add Postal Range"]').click();
			cy.get('[data-idx="1"] input[data-fieldname="postal_code_from"]').type('1055');
			cy.get('[data-idx="1"] input[data-fieldname="postal_code_to"]').type('1065');

			// Verify JavaScript internal overlap detection
			cy.get('.internal-overlap-warning').should('be.visible');
			cy.get('.overlap-codes-display').should('contain', '1055-1060');
		});

		it('should test chapter status management and workflow buttons', () => {
			cy.createTestChapter({
				chapter_name: 'Status Test Chapter',
				status: 'Draft'
			});

			cy.visit('/app/chapter/Status%20Test%20Chapter');
			cy.wait(2000);

			// Test status-dependent button availability
			cy.get('[data-fieldname="status"]').should('contain', 'Draft');
			cy.get('button[data-label="Activate Chapter"]').should('be.visible');
			cy.get('button[data-label="Assign Eligible Members"]').should('be.disabled');

			// Test chapter activation
			cy.get('button[data-label="Activate Chapter"]').click();
			cy.wait(2000);

			// Verify JavaScript status update
			cy.get('[data-fieldname="status"]').should('contain', 'Active');
			cy.get('.status-indicator').should('have.class', 'status-active');

			// Verify button availability changes
			cy.get('button[data-label="Assign Eligible Members"]').should('not.be.disabled');
			cy.get('button[data-label="Deactivate Chapter"]').should('be.visible');

			// Test deactivation with member check
			cy.get('button[data-label="Deactivate Chapter"]').click();

			// Should warn about existing members (if any)
			cy.get('.deactivation-warning').should('be.visible');
			cy.get('button[data-label="Confirm Deactivation"]').click();
			cy.wait(2000);

			// Verify status change
			cy.get('[data-fieldname="status"]').should('contain', 'Inactive');
			cy.get('.status-indicator').should('have.class', 'status-inactive');
		});
	});
});

/**
 * Enhanced Custom Commands for Chapter Testing
 */

// Create test chapter with postal code configuration
Cypress.Commands.add('createTestChapter', (chapterConfig) => {
	return cy.request({
		method: 'POST',
		url: '/api/method/verenigingen.tests.create_test_chapter',
		body: chapterConfig
	}).then((response) => {
		return response.body.message;
	});
});

// Create test chapter with board members
Cypress.Commands.add('createTestChapterWithBoard', (chapterConfig) => {
	return cy.request({
		method: 'POST',
		url: '/api/method/verenigingen.tests.create_chapter_with_board',
		body: chapterConfig
	}).then((response) => {
		return response.body.message;
	});
});
