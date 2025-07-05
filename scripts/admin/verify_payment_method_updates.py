#!/usr/bin/env python3
"""
Payment Method Update Verification Script

This script verifies that all payment method references have been
correctly updated throughout the verenigingen codebase.

Usage:
    python verify_payment_method_updates.py [--verbose]
"""

import argparse
import logging
import os
import re
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class PaymentMethodVerifier:
    """Verifies payment method references in the verenigingen codebase"""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

        # Base directory - script location relative to verenigingen app
        self.base_dir = Path(__file__).parent.parent.parent

        # File patterns to include
        self.include_extensions = {".py", ".js", ".html", ".json", ".md", ".txt"}

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

        # Patterns to check for
        self.patterns = {
            "correct_sepa": r"\bSEPA Direct Debit\b",
            "old_direct_debit": r"\bDirect Debit\b(?!\s+Batch)",  # Not followed by "Batch"
            "old_sepa_dd": r"\bSEPA DD\b",
            "double_sepa": r"\bSEPA\s+SEPA\s+Direct\s+Debit\b",
        }

        # Track results
        self.results = {
            "files_processed": 0,
            "correct_sepa_count": 0,
            "old_direct_debit_count": 0,
            "old_sepa_dd_count": 0,
            "double_sepa_count": 0,
            "old_direct_debit_files": [],
            "old_sepa_dd_files": [],
            "double_sepa_files": [],
        }

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

    def check_file(self, file_path: Path) -> None:
        """Check a single file for payment method patterns"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except (UnicodeDecodeError, IOError) as e:
            if self.verbose:
                logger.warning(f"Skipping {file_path}: {e}")
            return

        self.results["files_processed"] += 1

        # Check for correct SEPA Direct Debit references
        correct_matches = re.findall(self.patterns["correct_sepa"], content)
        self.results["correct_sepa_count"] += len(correct_matches)

        # Check for old Direct Debit references (excluding known valid ones)
        old_dd_matches = re.findall(self.patterns["old_direct_debit"], content)
        # Filter out known valid uses like "Direct Debit Batch"
        filtered_dd_matches = []
        for match in old_dd_matches:
            # Check context around the match
            match_positions = [m.start() for m in re.finditer(re.escape(match), content)]
            for pos in match_positions:
                # Check if it's followed by "Batch" or is "SEPA Direct Debit"
                end_pos = pos + len(match)
                context_after = content[end_pos : end_pos + 20].strip()
                context_before = content[max(0, pos - 20) : pos].strip()

                if (
                    not context_after.startswith(" Batch")
                    and not context_before.endswith("SEPA")
                    and "Direct Debit Batch" not in content[max(0, pos - 50) : pos + 50]
                ):
                    filtered_dd_matches.append(match)

        if filtered_dd_matches:
            self.results["old_direct_debit_count"] += len(filtered_dd_matches)
            self.results["old_direct_debit_files"].append(str(file_path))
            if self.verbose:
                logger.warning(
                    f"Found old 'Direct Debit' in {file_path}: {len(filtered_dd_matches)} instances"
                )

        # Check for old SEPA DD references
        old_sepa_dd_matches = re.findall(self.patterns["old_sepa_dd"], content)
        if old_sepa_dd_matches:
            self.results["old_sepa_dd_count"] += len(old_sepa_dd_matches)
            self.results["old_sepa_dd_files"].append(str(file_path))
            if self.verbose:
                logger.warning(f"Found old 'SEPA DD' in {file_path}: {len(old_sepa_dd_matches)} instances")

        # Check for double SEPA references
        double_sepa_matches = re.findall(self.patterns["double_sepa"], content)
        if double_sepa_matches:
            self.results["double_sepa_count"] += len(double_sepa_matches)
            self.results["double_sepa_files"].append(str(file_path))
            if self.verbose:
                logger.warning(
                    f"Found double 'SEPA Direct Debit' in {file_path}: {len(double_sepa_matches)} instances"
                )

    def scan_directory(self) -> None:
        """Scan the verenigingen directory for files to check"""
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
                        logger.info(f"Checking: {file_path}")

                    self.check_file(file_path)

    def generate_report(self) -> str:
        """Generate a verification report"""
        report = []
        report.append("=" * 80)
        report.append("PAYMENT METHOD UPDATE VERIFICATION REPORT")
        report.append("=" * 80)
        report.append(f"Base directory: {self.base_dir}")
        report.append("")

        # Summary statistics
        report.append("STATISTICS:")
        report.append(f"  Files processed: {self.results['files_processed']}")
        report.append(f"  Correct 'SEPA Direct Debit' references: {self.results['correct_sepa_count']}")
        report.append(f"  Old 'Direct Debit' references: {self.results['old_direct_debit_count']}")
        report.append(f"  Old 'SEPA DD' references: {self.results['old_sepa_dd_count']}")
        report.append(f"  Double 'SEPA Direct Debit' references: {self.results['double_sepa_count']}")
        report.append("")

        # Overall status
        issues_found = (
            self.results["old_direct_debit_count"]
            + self.results["old_sepa_dd_count"]
            + self.results["double_sepa_count"]
        )

        if issues_found == 0:
            report.append("✅ VERIFICATION PASSED")
            report.append("All payment method references have been successfully updated!")
            report.append("No issues found.")
        else:
            report.append("❌ VERIFICATION FAILED")
            report.append(f"Found {issues_found} issues that need attention:")

        # Detailed issues
        if self.results["old_direct_debit_files"]:
            report.append("")
            report.append("FILES WITH OLD 'Direct Debit' REFERENCES:")
            for file_path in sorted(set(self.results["old_direct_debit_files"])):
                report.append(f"  {file_path}")

        if self.results["old_sepa_dd_files"]:
            report.append("")
            report.append("FILES WITH OLD 'SEPA DD' REFERENCES:")
            for file_path in sorted(set(self.results["old_sepa_dd_files"])):
                report.append(f"  {file_path}")

        if self.results["double_sepa_files"]:
            report.append("")
            report.append("FILES WITH DOUBLE 'SEPA Direct Debit' REFERENCES:")
            for file_path in sorted(set(self.results["double_sepa_files"])):
                report.append(f"  {file_path}")

        report.append("")
        report.append("=" * 80)
        return "\n".join(report)

    def run(self) -> bool:
        """Run the verification process and return True if all checks pass"""
        logger.info("Starting payment method verification...")

        # Scan and check files
        self.scan_directory()

        # Generate and display report
        report = self.generate_report()
        print(report)

        # Return success status
        issues_found = (
            self.results["old_direct_debit_count"]
            + self.results["old_sepa_dd_count"]
            + self.results["double_sepa_count"]
        )
        return issues_found == 0


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Verify payment method references in verenigingen codebase",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python verify_payment_method_updates.py          # Basic verification
  python verify_payment_method_updates.py --verbose # Detailed verification
        """,
    )

    parser.add_argument("--verbose", action="store_true", help="Show detailed information about processing")

    args = parser.parse_args()

    # Create and run verifier
    verifier = PaymentMethodVerifier(verbose=args.verbose)

    try:
        success = verifier.run()
        exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
        exit(1)
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        raise


if __name__ == "__main__":
    main()
