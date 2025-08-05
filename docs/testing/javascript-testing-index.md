# JavaScript Testing Documentation Index

## Quick Navigation

This index helps you find the right JavaScript testing documentation for your specific needs. The Verenigingen app has three complementary JavaScript testing guides, each focusing on different aspects of the testing ecosystem.

## Documentation Structure

### 📋 [Testing Strategy Overview](../testing-strategy.md)
**When to use:** Understanding our overall testing philosophy and approach
- **Focus:** Strategic overview, coverage goals, performance benchmarks
- **Best for:** Project managers, team leads, new developers understanding the big picture
- **Content:** Testing philosophy, coverage requirements, performance goals, security testing approach

### 🔧 [JavaScript Testing Infrastructure](javascript-testing-guide.md)
**When to use:** Setting up testing infrastructure, CI/CD integration, and development workflows
- **Focus:** Tools, configuration, CI/CD pipelines, development environment setup
- **Best for:** DevOps engineers, developers setting up testing environments
- **Content:** Jest/Cypress setup, GitHub Actions workflows, coverage reporting, debugging tools

### 📝 [DocType JavaScript Testing](../javascript-testing-guide.md)
**When to use:** Writing tests for specific DocType form controllers and business logic
- **Focus:** Practical testing patterns for Frappe DocType JavaScript files
- **Best for:** Frontend developers writing tests for form controllers and business logic
- **Content:** DocType-specific test examples, mocking patterns, form testing strategies

## Use Case Quick Reference

### "I want to..."

#### Set Up JavaScript Testing
→ **Start with:** [JavaScript Testing Infrastructure](javascript-testing-guide.md)
- Install dependencies and configure Jest/Cypress
- Set up CI/CD workflows
- Configure coverage reporting

#### Test DocType Form Controllers
→ **Start with:** [DocType JavaScript Testing](../javascript-testing-guide.md)
- Learn DocType-specific testing patterns
- See examples for Member, Chapter, Volunteer forms
- Understand mocking strategies for Frappe framework

#### Understand Testing Philosophy
→ **Start with:** [Testing Strategy Overview](../testing-strategy.md)
- Learn our testing approach and coverage goals
- Understand performance benchmarks
- See security testing requirements

#### Debug Test Issues
→ **Check:** [JavaScript Testing Infrastructure](javascript-testing-guide.md) → Debugging section
- Jest debugging techniques
- Cypress debugging tools
- VS Code integration

#### Write Integration Tests
→ **Check:** [DocType JavaScript Testing](../javascript-testing-guide.md) → Integration Tests section
- Cross-DocType workflow testing
- Multi-component interaction patterns

#### Set Up CI/CD
→ **Check:** [JavaScript Testing Infrastructure](javascript-testing-guide.md) → CI/CD Integration section
- GitHub Actions configuration
- Automated test execution
- Coverage reporting integration

#### Understand Coverage Requirements
→ **Check:** [Testing Strategy Overview](../testing-strategy.md) → Coverage Goals section
- Current coverage thresholds: 70% (branches, functions, lines, statements)
- Coverage reporting locations
- Performance benchmarks

## File Organization Reference

```
docs/
├── testing-strategy.md                    # Strategic overview and philosophy
├── javascript-testing-guide.md           # DocType-specific testing patterns
└── testing/
    ├── javascript-testing-guide.md       # Infrastructure and CI/CD setup
    └── javascript-testing-index.md       # This navigation file
```

## Testing Command Quick Reference

### Development Commands
```bash
# Unit tests with Jest
npm test                    # Run all tests
npm run test:watch         # Watch mode for development
npm run test:coverage      # Generate coverage reports

# E2E tests with Cypress
yarn cypress:open         # Interactive test runner
yarn cypress:run          # Headless execution
```

### CI/CD Commands
```bash
# From project root
node tests/run-js-tests.js           # Custom test runner
node tests/run-js-tests.js unit      # Unit tests only
node tests/run-js-tests.js member    # DocType-specific tests
```

## Related Documentation

- **Python Testing:** See `/docs/testing/` directory for Python test documentation
- **API Testing:** Check the infrastructure guide for API testing patterns
- **Performance Testing:** Referenced in the strategy overview
- **Security Testing:** Covered in the strategy document

## Contributing to Documentation

When updating JavaScript testing documentation:

1. **Infrastructure changes** → Update [javascript-testing-guide.md](javascript-testing-guide.md)
2. **DocType patterns** → Update [../javascript-testing-guide.md](../javascript-testing-guide.md)
3. **Strategy changes** → Update [../testing-strategy.md](../testing-strategy.md)
4. **New navigation needs** → Update this index file

## Support and Resources

- **Jest Documentation:** https://jestjs.io/docs/getting-started
- **Cypress Documentation:** https://docs.cypress.io
- **Frappe Testing Guide:** https://frappeframework.com/docs/user/en/testing
- **Internal Support:** Check the troubleshooting sections in each guide
