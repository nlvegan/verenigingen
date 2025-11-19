#!/usr/bin/env python3
"""
Fix Double SEPA References Script

This script fixes the "SEPA Direct Debit" double references that were
created during the initial payment method update process.

Usage:
    python fix_double_sepa_references.py [--dry-run] [--verbose]
"""

import argparse
import logging
import os
import re
from pathlib import Path
from typing import Tuple

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class DoubleSepaFixer:
    """Fixes double SEPA references in the verenigingen codebase"""

    def __init__(self, dry_run: bool = False, verbose: bool = False):
        self.dry_run = dry_run
        self.verbose = verbose

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

        # Track statistics
        self.stats = {"files_processed": 0, "files_modified": 0, "total_replacements": 0}

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

    def fix_double_sepa_in_content(self, content: str) -> Tuple[str, int]:
        """Fix double SEPA references in content"""
        original_content = content

        # Fix the double SEPA issue
        content = re.sub(r"\bSEPA\s+SEPA\s+Direct\s+Debit\b", "SEPA Direct Debit", content)

        # Count replacements made
        replacements = len(re.findall(r"\bSEPA\s+SEPA\s+Direct\s+Debit\b", original_content))

        return content, replacements

    def process_file(self, file_path: Path) -> bool:
        """Process a single file and return True if modified"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except (UnicodeDecodeError, IOError) as e:
            logger.warning(f"Skipping {file_path}: {e}")
            return False

        # Fix double SEPA references
        new_content, replacements = self.fix_double_sepa_in_content(content)

        # Update statistics
        self.stats["files_processed"] += 1

        if replacements > 0:
            self.stats["files_modified"] += 1
            self.stats["total_replacements"] += replacements
            self.modified_files.append(str(file_path))

            if self.verbose or not self.dry_run:
                logger.info(
                    f"{'[DRY RUN] ' if self.dry_run else ''}Fixed {file_path}: {replacements} double SEPA references"
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
        summary.append("DOUBLE SEPA REFERENCE FIX SUMMARY")
        summary.append("=" * 80)
        summary.append(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE UPDATE'}")
        summary.append(f"Base directory: {self.base_dir}")
        summary.append("")
        summary.append("STATISTICS:")
        summary.append(f"  Files processed: {self.stats['files_processed']}")
        summary.append(f"  Files modified: {self.stats['files_modified']}")
        summary.append(f"  Total replacements: {self.stats['total_replacements']}")
        summary.append("")
        summary.append("REPLACEMENT MADE:")
        summary.append("  'SEPA Direct Debit' → 'SEPA Direct Debit'")
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
        """Run the double SEPA reference fix process"""
        logger.info("Starting double SEPA reference fix process...")

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
        description="Fix double SEPA references in verenigingen codebase",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python fix_double_sepa_references.py --dry-run    # Preview changes
  python fix_double_sepa_references.py --verbose    # Apply with detailed output
        """,
    )

    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be changed without making changes"
    )

    parser.add_argument("--verbose", action="store_true", help="Show detailed information about processing")

    args = parser.parse_args()

    # Create and run fixer
    fixer = DoubleSepaFixer(dry_run=args.dry_run, verbose=args.verbose)

    try:
        fixer.run()
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        raise


if __name__ == "__main__":
    main()
