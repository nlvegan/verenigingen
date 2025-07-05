// Import the functions we need to test
const fs = require('fs');
const path = require('path');

// Read and evaluate the sepa-utils.js file
const sepaUtilsPath = path.join(__dirname, '../../verenigingen/public/js/member/js_modules/sepa-utils.js');
const sepaUtilsCode = fs.readFileSync(sepaUtilsPath, 'utf8');

// Extract just the functions we want to test
const generateMandateReference = eval(`(${sepaUtilsCode.match(/function generateMandateReference[\s\S]*?(?=\n\nfunction|\n\/\/|$)/)[0]})`);

describe('SEPA Utilities', () => {
	describe('generateMandateReference', () => {
		beforeEach(() => {
			// Mock Date to have consistent tests
			jest.useFakeTimers();
			jest.setSystemTime(new Date('2024-01-15'));

			// Mock Math.random for consistent random numbers
			jest.spyOn(Math, 'random').mockReturnValue(0.5);
		});

		afterEach(() => {
			jest.useRealTimers();
			jest.restoreAllMocks();
		});

		it('should generate mandate reference with member_id', () => {
			const memberDoc = {
				member_id: 'MEM123',
				name: 'Assoc-Member-456'
			};

			const result = generateMandateReference(memberDoc);
			expect(result).toBe('M-MEM123-20240115-550');
		});

		it('should use name when member_id is not available', () => {
			const memberDoc = {
				name: 'Assoc-Member-789'
			};

			const result = generateMandateReference(memberDoc);
			expect(result).toBe('M-789-20240115-550');
		});

		it('should handle different date formats correctly', () => {
			// Test with a date in December
			jest.setSystemTime(new Date('2024-12-25'));

			const memberDoc = {
				member_id: 'MEM999'
			};

			const result = generateMandateReference(memberDoc);
			expect(result).toBe('M-MEM999-20241225-550');
		});

		it('should generate different random suffixes', () => {
			const memberDoc = {
				member_id: 'MEM123'
			};

			// Test with different random values
			Math.random.mockReturnValue(0.1);
			const result1 = generateMandateReference(memberDoc);
			expect(result1).toBe('M-MEM123-20240115-190');

			Math.random.mockReturnValue(0.9);
			const result2 = generateMandateReference(memberDoc);
			expect(result2).toBe('M-MEM123-20240115-910');
		});

		it('should handle complex member names', () => {
			const memberDoc = {
				name: 'Assoc-Member-ABC-123-XYZ'
			};

			const result = generateMandateReference(memberDoc);
			expect(result).toBe('M-ABC123XYZ-20240115-550');
		});
	});
});
