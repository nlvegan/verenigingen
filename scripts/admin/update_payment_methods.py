#!/usr/bin/env python3
"""
Comprehensive Payment Method Update Script for Verenigingen Codebase

This script searches through the entire verenigingen codebase and updates
ALL remaining references to old payment method values:
- "SEPA Direct Debit" → "SEPA Direct Debit"
- "SEPA Direct Debit" → "SEPA Direct Debit"

The script handles various file types (.py, .js, .html, .json) and contexts
while being careful not to update comments explaining old vs new formats.

Usage:
    python update_payment_methods.py [--dry-run] [--verbose] [--include-comments]

Options:
    --dry-run: Show what would be changed without actually making changes
    --verbose: Show detailed information about each file processed
    --include-comments: Also update references in comments (use with caution)
"""

import argparse
import json
import logging
import os
import re
from pathlib import Path
from typing import Tuple

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class PaymentMethodUpdater:
    """Updates payment method references in the verenigingen codebase"""

    def __init__(self, dry_run: bool = False, verbose: bool = False, include_comments: bool = False):
        self.dry_run = dry_run
        self.verbose = verbose
        self.include_comments = include_comments

        # Base directory - script location relative to verenigingen app
        self.base_dir = Path(__file__).parent.parent.parent

        # File patterns to include
        self.include_extensions = {".py", ".js", ".html", ".json", ".md", ".txt", ".css", ".scss"}

        # File/directory patterns to exclude
        self.exclude_patterns = {
            "*.pyc",
            "*.pyo",
            "*.pyd",
            "__pycache__",
            ".git",
            "node_modules",
            ".pytest_cache",
            "dist",
            "build",
            ".mypy_cache",
            ".venv",
            "venv",
            "env",
            ".env",
            "logs",
            "*.log",
            ".DS_Store",
            "Thumbs.db",
            "*.min.js",
            "*.min.css",
            "yarn.lock",
            "package-lock.json",
        }

        # Replacement mappings
        self.replacements = {
            "SEPA Direct Debit": "SEPA Direct Debit",
            "SEPA Direct Debit": "SEPA Direct Debit",
        }

        # Patterns that should NOT be updated (comments explaining old vs new)
        self.comment_exclusion_patterns = [
            r"#.*old.*vs.*new",
            r"#.*Direct Debit.*→.*SEPA",
            r"//.*old.*vs.*new",
            r"//.*Direct Debit.*→.*SEPA",
            r"<!--.*old.*vs.*new",
            r"<!--.*Direct Debit.*→.*SEPA",
            r"/\*.*old.*vs.*new",
            r"/\*.*SEPA Direct Debit.*→.*SEPA",
            r'""".*old.*vs.*new',
            r'""".*Direct Debit.*→.*SEPA',
        ]

        # Track statistics
        self.stats = {
            "files_processed": 0,
            "files_modified": 0,
            "total_replacements": 0,
            "replacements_by_type": {},
        }

        # Track modified files
        self.modified_files = []

    def should_exclude_file(self, file_path: Path) -> bool:
        """Check if a file should be excluded based on patterns"""
        file_str = str(file_path)

        # Check exclude patterns
        for pattern in self.exclude_patterns:
            if pattern.startswith("*"):
                if file_str.endswith(pattern[1:]):
                    return True
            elif pattern in file_str:
                return True

        return False

    def should_exclude_line(self, line: str) -> bool:
        """Check if a line should be excluded from updates (e.g., explanatory comments)"""
        if self.include_comments:
            return False

        line_lower = line.lower()
        for pattern in self.comment_exclusion_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                return True

        return False

    def process_python_file(self, content: str) -> Tuple[str, int]:
        """Process Python files with special handling for strings and comments"""
        lines = content.split("\n")
        modified_lines = []
        replacements_made = 0

        for line in lines:
            original_line = line

            # Skip lines that should be excluded
            if self.should_exclude_line(line):
                modified_lines.append(line)
                continue

            # Process the line
            for old_value, new_value in self.replacements.items():
                # Handle string literals (single and double quotes)
                line = re.sub(rf'(["\']){re.escape(old_value)}(["\'])', rf"\1{new_value}\2", line)
                # Handle list/array contexts
                line = re.sub(rf"\b{re.escape(old_value)}\b", new_value, line)

            if line != original_line:
                replacements_made += 1
                if self.verbose:
                    logger.info(f"  Line changed: {original_line.strip()} → {line.strip()}")

            modified_lines.append(line)

        return "\n".join(modified_lines), replacements_made

    def process_javascript_file(self, content: str) -> Tuple[str, int]:
        """Process JavaScript files with special handling for strings and comments"""
        lines = content.split("\n")
        modified_lines = []
        replacements_made = 0

        for line in lines:
            original_line = line

            # Skip lines that should be excluded
            if self.should_exclude_line(line):
                modified_lines.append(line)
                continue

            # Process the line
            for old_value, new_value in self.replacements.items():
                # Handle string literals (single, double quotes, and template literals)
                line = re.sub(rf'(["\`\']){re.escape(old_value)}(["\`\'])', rf"\1{new_value}\2", line)
                # Handle array contexts
                line = re.sub(rf"\b{re.escape(old_value)}\b", new_value, line)

            if line != original_line:
                replacements_made += 1
                if self.verbose:
                    logger.info(f"  Line changed: {original_line.strip()} → {line.strip()}")

            modified_lines.append(line)

        return "\n".join(modified_lines), replacements_made

    def process_html_file(self, content: str) -> Tuple[str, int]:
        """Process HTML files with special handling for attributes and text"""
        lines = content.split("\n")
        modified_lines = []
        replacements_made = 0

        for line in lines:
            original_line = line

            # Skip lines that should be excluded
            if self.should_exclude_line(line):
                modified_lines.append(line)
                continue

            # Process the line
            for old_value, new_value in self.replacements.items():
                # Handle attribute values
                line = re.sub(rf'([\s=]"){re.escape(old_value)}(")', rf"\1{new_value}\2", line)
                line = re.sub(rf"([\s=]'){re.escape(old_value)}(')", rf"\1{new_value}\2", line)
                # Handle text content
                line = re.sub(rf"\b{re.escape(old_value)}\b", new_value, line)

            if line != original_line:
                replacements_made += 1
                if self.verbose:
                    logger.info(f"  Line changed: {original_line.strip()} → {line.strip()}")

            modified_lines.append(line)

        return "\n".join(modified_lines), replacements_made

    def process_json_file(self, content: str) -> Tuple[str, int]:
        """Process JSON files with special care for structure"""
        try:
            # First try to parse as JSON for structured updates
            data = json.loads(content)
            original_json = json.dumps(data, sort_keys=True)

            # Convert to string for replacement
            json_str = json.dumps(data, indent=2)

            replacements_made = 0
            for old_value, new_value in self.replacements.items():
                # Only replace string values, not keys
                pattern = rf'": "{re.escape(old_value)}"'
                replacement = f'": "{new_value}"'
                if re.search(pattern, json_str):
                    json_str = re.sub(pattern, replacement, json_str)
                    replacements_made += 1

            # Validate the result is still valid JSON
            json.loads(json_str)
            return json_str, replacements_made

        except json.JSONDecodeError:
            # Fall back to line-by-line processing if not valid JSON
            return self.process_generic_file(content)

    def process_generic_file(self, content: str) -> Tuple[str, int]:
        """Process generic text files line by line"""
        lines = content.split("\n")
        modified_lines = []
        replacements_made = 0

        for line in lines:
            original_line = line

            # Skip lines that should be excluded
            if self.should_exclude_line(line):
                modified_lines.append(line)
                continue

            # Process the line
            for old_value, new_value in self.replacements.items():
                line = re.sub(rf"\b{re.escape(old_value)}\b", new_value, line)

            if line != original_line:
                replacements_made += 1
                if self.verbose:
                    logger.info(f"  Line changed: {original_line.strip()} → {line.strip()}")

            modified_lines.append(line)

        return "\n".join(modified_lines), replacements_made

    def process_file(self, file_path: Path) -> bool:
        """Process a single file and return True if modified"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except (UnicodeDecodeError, IOError) as e:
            logger.warning(f"Skipping {file_path}: {e}")
            return False

        # Choose processor based on file extension
        extension = file_path.suffix.lower()
        if extension == ".py":
            new_content, replacements = self.process_python_file(content)
        elif extension == ".js":
            new_content, replacements = self.process_javascript_file(content)
        elif extension == ".html":
            new_content, replacements = self.process_html_file(content)
        elif extension == ".json":
            new_content, replacements = self.process_json_file(content)
        else:
            new_content, replacements = self.process_generic_file(content)

        # Update statistics
        self.stats["files_processed"] += 1

        if replacements > 0:
            self.stats["files_modified"] += 1
            self.stats["total_replacements"] += replacements
            self.modified_files.append(str(file_path))

            if self.verbose or not self.dry_run:
                logger.info(
                    f"{'[DRY RUN] ' if self.dry_run else ''}Modified {file_path}: {replacements} replacements"
                )

            # Write file if not dry run
            if not self.dry_run:
                try:
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(new_content)
                except IOError as e:
                    logger.error(f"Failed to write {file_path}: {e}")
                    return False

            return True

        return False

    def scan_directory(self) -> None:
        """Scan the verenigingen directory for files to process"""
        logger.info(f"Scanning directory: {self.base_dir}")

        for root, dirs, files in os.walk(self.base_dir):
            # Filter out excluded directories
            dirs[:] = [d for d in dirs if not any(pattern in d for pattern in self.exclude_patterns)]

            for file in files:
                file_path = Path(root) / file

                # Check if file should be processed
                if file_path.suffix.lower() in self.include_extensions and not self.should_exclude_file(
                    file_path
                ):
                    if self.verbose:
                        logger.info(f"Processing: {file_path}")

                    self.process_file(file_path)

    def generate_summary(self) -> str:
        """Generate a summary of changes made"""
        summary = []
        summary.append("=" * 80)
        summary.append("PAYMENT METHOD UPDATE SUMMARY")
        summary.append("=" * 80)
        summary.append(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE UPDATE'}")
        summary.append(f"Base directory: {self.base_dir}")
        summary.append(f"Include comments: {self.include_comments}")
        summary.append("")
        summary.append("STATISTICS:")
        summary.append(f"  Files processed: {self.stats['files_processed']}")
        summary.append(f"  Files modified: {self.stats['files_modified']}")
        summary.append(f"  Total replacements: {self.stats['total_replacements']}")
        summary.append("")
        summary.append("REPLACEMENTS MADE:")
        for old_value, new_value in self.replacements.items():
            summary.append(f"  '{old_value}' → '{new_value}'")
        summary.append("")

        if self.modified_files:
            summary.append("MODIFIED FILES:")
            for file_path in sorted(self.modified_files):
                summary.append(f"  {file_path}")
        else:
            summary.append("No files were modified.")

        summary.append("=" * 80)
        return "\n".join(summary)

    def run(self) -> None:
        """Run the payment method update process"""
        logger.info("Starting payment method update process...")

        if self.dry_run:
            logger.info("Running in DRY RUN mode - no changes will be made")

        # Scan and process files
        self.scan_directory()

        # Generate and display summary
        summary = self.generate_summary()
        print(summary)

        if self.dry_run and self.stats["files_modified"] > 0:
            print("\nTo apply these changes, run the script without --dry-run")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Update payment method references in verenigingen codebase",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python update_payment_methods.py --dry-run              # Preview changes
  python update_payment_methods.py --verbose              # Apply with detailed output
  python update_payment_methods.py --include-comments     # Also update comments
        """,
    )

    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be changed without making changes"
    )

    parser.add_argument("--verbose", action="store_true", help="Show detailed information about processing")

    parser.add_argument(
        "--include-comments",
        action="store_true",
        help="Also update references in comments (use with caution)",
    )

    args = parser.parse_args()

    # Create and run updater
    updater = PaymentMethodUpdater(
        dry_run=args.dry_run, verbose=args.verbose, include_comments=args.include_comments
    )

    try:
        updater.run()
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        raise


if __name__ == "__main__":
    main()
