# JavaScript Testing Guide for Verenigingen

## Overview

This guide covers the JavaScript testing infrastructure for the Verenigingen app, including unit tests, integration tests, and end-to-end (E2E) tests.

## Testing Stack

### Tools We Use

1. **Jest** - Unit testing framework for JavaScript
2. **Cypress** - E2E testing for UI flows
3. **ESLint** - JavaScript linting
4. **@testing-library** - Better testing utilities
5. **Coverage tools** - Code coverage reporting

### Tools Frappe Uses (That We've Adopted)

Based on Frappe's testing setup:
- **GitHub Actions** for CI/CD
- **Cypress with coverage** for UI testing
- **Codecov** for coverage reporting
- **Pre-commit hooks** for code quality
- **Parallel test execution** for speed

## Running Tests

### Unit Tests (Jest)

```bash
# Run all unit tests
yarn test

# Run tests in watch mode (for development)
yarn test:watch

# Run tests with coverage
yarn test:coverage

# Run specific test file
yarn test expense_validation.spec.js
```

### E2E Tests (Cypress)

```bash
# Open Cypress Test Runner (interactive mode)
yarn cypress:open

# Run all tests headlessly
yarn cypress:run

# Run specific test
yarn cypress:run --spec "cypress/integration/member_application.spec.js"

# Run with coverage
yarn cypress:run --env coverage=true
```

### Linting

```bash
# Check for linting errors
yarn lint

# Auto-fix linting issues
yarn lint:fix

# Format code with Prettier
yarn format
```

## Writing Tests

### Unit Test Example

```javascript
// tests/unit/member_validation.spec.js
describe('Member Validation', () => {
  beforeEach(() => {
    // Setup test environment
  });

  it('should validate email format', () => {
    const validEmail = 'test@example.com';
    expect(isValidEmail(validEmail)).toBe(true);

    const invalidEmail = 'invalid-email';
    expect(isValidEmail(invalidEmail)).toBe(false);
  });
});
```

### Cypress E2E Test Example

```javascript
// cypress/integration/volunteer_flow.spec.js
describe('Volunteer Management', () => {
  beforeEach(() => {
    cy.login();
    cy.visit('/app/volunteer');
  });

  it('should create new volunteer', () => {
    cy.new_doc('Volunteer');
    cy.fill_field('volunteer_name', 'Test Volunteer');
    cy.fill_field('email', 'volunteer@test.com');
    cy.save();
    cy.verify_field('status', 'Active');
  });
});
```

## CI/CD Integration

### GitHub Actions Workflows

1. **UI Tests** (`ui-tests.yml`)
   - Runs Cypress tests in parallel
   - Tests against real database
   - Generates coverage reports

2. **JS Tests** (`js-tests.yml`)
   - Runs ESLint checks
   - Executes Jest unit tests
   - Builds production assets

3. **Pre-commit Hooks**
   - Runs quick tests before commit
   - Ensures code quality

## Coverage Reports

### Viewing Coverage

After running tests with coverage:

```bash
# Jest coverage
open coverage/lcov-report/index.html

# Cypress coverage
open coverage/lcov-report/index.html
```

### Coverage Thresholds

We aim for:
- **Statements**: 80%
- **Branches**: 75%
- **Functions**: 80%
- **Lines**: 80%

## Best Practices

### 1. Test Structure

- Use descriptive test names
- Group related tests with `describe`
- Use `beforeEach` for common setup
- Clean up after tests

### 2. Mocking

```javascript
// Mock frappe calls
jest.mock('frappe', () => ({
  call: jest.fn().mockResolvedValue({ message: 'success' })
}));

// Mock in Cypress
cy.intercept('POST', '/api/method/create_member', {
  statusCode: 200,
  body: { message: { name: 'MEM-0001' } }
});
```

### 3. Selectors

Use data attributes for test selectors:

```html
<button data-test-id="submit-button">Submit</button>
```

```javascript
cy.get('[data-test-id="submit-button"]').click();
```

### 4. Async Testing

```javascript
// Jest
it('should fetch data', async () => {
  const data = await fetchMemberData();
  expect(data).toHaveProperty('name');
});

// Cypress automatically handles async
cy.get('.member-list').should('have.length', 5);
```

## Common Testing Scenarios

### Form Validation

```javascript
it('should show validation errors', () => {
  cy.get('#submit').click();
  cy.get('.error-message').should('contain', 'Email is required');
});
```

### API Testing

```javascript
it('should create member via API', () => {
  cy.request('POST', '/api/method/create_member', {
    first_name: 'Test',
    last_name: 'User'
  }).then((response) => {
    expect(response.status).to.eq(200);
    expect(response.body.message).to.have.property('name');
  });
});
```

### Permission Testing

```javascript
it('should restrict access for non-admin users', () => {
  cy.login('user@example.com', 'password');
  cy.visit('/app/system-settings');
  cy.get('.error-message').should('contain', 'Not Permitted');
});
```

## Debugging Tests

### Jest Debugging

```bash
# Run tests with Node debugger
node --inspect-brk node_modules/.bin/jest --runInBand

# Use console.log in tests
console.log('Debug info:', variable);
```

### Cypress Debugging

```javascript
// Pause test execution
cy.pause();

// Debug specific element
cy.get('.element').debug();

// Take screenshot
cy.screenshot('debug-state');
```

## Integration with VS Code

### Recommended Extensions

1. **Jest Runner** - Run tests from editor
2. **Cypress Snippets** - Code snippets
3. **ESLint** - Real-time linting
4. **Prettier** - Code formatting

### Debug Configuration

```json
// .vscode/launch.json
{
  "configurations": [
    {
      "type": "node",
      "request": "launch",
      "name": "Jest Debug",
      "program": "${workspaceFolder}/node_modules/.bin/jest",
      "args": ["--runInBand"],
      "console": "integratedTerminal"
    }
  ]
}
```

## Resources

- [Jest Documentation](https://jestjs.io/docs/getting-started)
- [Cypress Documentation](https://docs.cypress.io)
- [Testing Library](https://testing-library.com)
- [Frappe Testing Guide](https://frappeframework.com/docs/user/en/testing)
