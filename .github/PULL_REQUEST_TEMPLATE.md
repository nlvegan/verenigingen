# Pull Request

## Description

<!-- Provide a clear and concise description of your changes -->

## Type of Change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Refactoring (code change that neither fixes a bug nor adds a feature)
- [ ] Documentation update
- [ ] Test improvement

## Related Issues

<!-- Link to related issues: Fixes #123, Relates to #456 -->

## Changes Made

<!-- List the specific changes made in this PR -->

-
-
-

## Controller Growth Prevention Checklist

**Required for all PRs that modify DocType controllers** (member.py, volunteer.py, etc.)

- [ ] No new business logic added to controllers (logic belongs in services)
- [ ] New business logic added to service classes (not controllers)
- [ ] Services have unit tests with >80% coverage
- [ ] Controller line counts have not increased (or decreased)
- [ ] Service usage documented (which service, how to test, integration points)

**If controller logic was added**, provide justification:

<!--
Explain why logic must be in controller:
- Frappe framework requirement?
- Performance critical path with benchmarks?
- Exception approved by technical leadership?
Include reference to approval or ADR.
-->

## Testing Checklist

- [ ] All existing tests pass
- [ ] New tests added for new functionality
- [ ] Enhanced Test Factory used for test data (no database mocking)
- [ ] Manual testing completed
- [ ] Edge cases tested

## Code Quality Checklist

- [ ] Code follows project style guidelines (black, isort, flake8, pylint)
- [ ] No security vulnerabilities introduced (bandit checks pass)
- [ ] API endpoints have proper security decorators
- [ ] Field names verified against DocType JSON files (not guessed)
- [ ] Pre-commit hooks pass locally
- [ ] No TODO comments left without tracking tickets

## Documentation Checklist

- [ ] Code comments added for complex logic
- [ ] Docstrings added/updated for public functions
- [ ] README/docs updated if needed
- [ ] Architecture Decision Records (ADRs) created if needed

## Deployment Considerations

- [ ] Database migrations included (if needed)
- [ ] Fixtures updated (if needed)
- [ ] Backwards compatible (or breaking changes documented)
- [ ] Rollback plan considered

## Screenshots/Recordings

<!-- Add screenshots or recordings for UI changes -->

## Additional Notes

<!-- Any additional context, considerations, or notes for reviewers -->

---

## Reviewer Guidelines

**For Reviewers**: Please verify:

1. **Controller Growth**: Run `python scripts/check_controller_size.py` locally
2. **Service Layer**: New business logic is in services, not controllers
3. **Test Quality**: Tests use Enhanced Test Factory, not database mocks
4. **Security**: API endpoints have proper security decorators
5. **Field References**: Field names match DocType JSON files

**Review Priority**:
- 🔴 High: Security issues, data integrity, breaking changes
- 🟡 Medium: Architecture violations, missing tests, documentation gaps
- 🟢 Low: Style issues, minor optimizations, documentation improvements
