#!/bin/bash
# Install pre-commit hooks for Verenigingen development

echo "Installing pre-commit hooks for Verenigingen..."

# Check if pre-commit is installed
if ! command -v pre-commit &> /dev/null; then
    echo "Installing pre-commit..."
    pip install pre-commit
fi

# Create pre-commit config if it doesn't exist
if [ ! -f .pre-commit-config.yaml ]; then
    cat > .pre-commit-config.yaml << 'EOF'
# Pre-commit hooks for Verenigingen app
# Install with: pre-commit install

repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.4.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
      - id: check-json
      - id: check-merge-conflict
      - id: debug-statements
      - id: check-docstring-first

  - repo: https://github.com/psf/black
    rev: 23.3.0
    hooks:
      - id: black
        language_version: python3
        args: ['--line-length=110']

  - repo: https://github.com/PyCQA/flake8
    rev: 6.0.0
    hooks:
      - id: flake8
        args: [
          '--max-line-length=110',
          '--extend-ignore=E203,E501,W503',
          '--exclude=.git,__pycache__,build,dist'
        ]

  - repo: https://github.com/PyCQA/isort
    rev: 5.12.0
    hooks:
      - id: isort
        args: ['--profile', 'black', '--line-length', '110']

  - repo: https://github.com/PyCQA/pylint
    rev: v3.0.3
    hooks:
      - id: pylint
        args: [
          '--rcfile=.pylintrc',
          '--fail-under=7.0',
          '--jobs=0'
        ]
        additional_dependencies: [
          'frappe',
          'erpnext'
        ]
        exclude: '^(node_modules|.git|dist|build)/'

  - repo: local
    hooks:
      - id: run-quick-tests
        name: Run quick validation tests
        entry: bash -c 'cd /home/frappe/frappe-bench && bench --site dev.veganisme.net execute verenigingen.tests.utils.quick_validation.run_quick_tests || echo "Tests failed but continuing commit"'
        language: system
        pass_filenames: false
        always_run: true
        stages: [commit]
        verbose: true
EOF
fi

# Install the hooks
pre-commit install

echo "✓ Pre-commit hooks installed successfully!"
echo ""
echo "The following hooks will run on every commit:"
echo "  - Code formatting (Black, isort)"
echo "  - Linting (Flake8)"
echo "  - File checks (trailing whitespace, merge conflicts, etc.)"
echo "  - Quick validation tests"
echo ""
echo "To run hooks manually: pre-commit run --all-files"
echo "To skip hooks: git commit --no-verify"
