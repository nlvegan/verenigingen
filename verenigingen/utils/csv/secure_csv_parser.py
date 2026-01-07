"""
Secure CSV Parser

Security-hardened CSV and Excel file parser with path traversal protection,
encoding detection, and injection prevention.

Extracted from MijnroodCSVImport to improve testability and reusability.
"""

import csv
import io
import os
import re
from typing import Dict, List, Optional, Tuple

import frappe
from frappe import _

try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


class SecureCSVParser:
    """
    Security-hardened CSV/Excel parser with comprehensive file validation.

    Features:
    - Path traversal attack prevention
    - CSV injection protection (handled by data_transformers)
    - Multiple encoding detection (UTF-8, ISO-8859-1, Windows-1252)
    - Excel file support via pandas
    - Automatic delimiter detection
    - BOM handling for UTF-8 files
    """

    def __init__(self, encoding: Optional[str] = None):
        """
        Initialize parser with optional encoding override.

        Args:
            encoding: Force specific encoding (default: auto-detect)
        """
        self.encoding = encoding

    def read_csv_file(self, file_url: str) -> List[Dict]:
        """
        Read CSV/Excel file from Frappe file URL.

        Args:
            file_url: Frappe File document URL or file path

        Returns:
            List of dictionaries representing CSV rows

        Raises:
            frappe.ValidationError: If file not found, invalid format, or security violation
        """
        if not file_url:
            return []

        try:
            filename = self._sanitize_filename(file_url)
            file_path, file_content = self._resolve_file_location(file_url, filename)
            return self._parse_file_data(file_path, file_content, filename)

        except UnicodeDecodeError:
            frappe.throw(
                _("File encoding error. Please check the encoding setting or try a different encoding.")
            )
        except Exception as e:
            frappe.log_error(
                message=f"CSV file reading error: {str(e)}",
                title="CSV Import Error"
            )
            frappe.throw(_("Error reading CSV file: {0}").format(str(e)))

    def _sanitize_filename(self, file_url: str) -> str:
        """
        Sanitize filename to prevent path traversal and injection attacks.

        Args:
            file_url: Original file URL

        Returns:
            Sanitized filename

        Raises:
            frappe.ValidationError: If file extension is not allowed
        """
        raw_filename = file_url.split("/")[-1] if "/" in file_url else file_url
        filename = os.path.basename(raw_filename)  # Prevent path traversal
        filename = re.sub(r"[^\w\-_\.]", "_", filename)  # Sanitize filename

        # Validate file extension for security
        if not filename.lower().endswith((".csv", ".xlsx", ".xls")):
            frappe.throw(_("Only CSV and Excel files are allowed. File: {0}").format(filename))

        return filename

    def _resolve_file_location(self, file_url: str, filename: str) -> Tuple[Optional[str], Optional[bytes]]:
        """
        Resolve file location using multiple lookup strategies.

        Args:
            file_url: Frappe File URL
            filename: Sanitized filename

        Returns:
            Tuple of (file_path, file_content)

        Raises:
            frappe.ValidationError: If file cannot be found
        """
        file_path, file_content = self._try_file_document_lookup(file_url, filename)

        if not file_path or not os.path.exists(file_path):
            file_path = self._try_direct_path_construction(filename)

        if not file_path and not file_content:
            self._handle_file_not_found(file_url, filename)

        return file_path, file_content

    def _try_file_document_lookup(
        self, file_url: str, filename: str
    ) -> Tuple[Optional[str], Optional[bytes]]:
        """
        Try to find file via Frappe File document lookup.

        Args:
            file_url: Frappe File URL
            filename: Sanitized filename

        Returns:
            Tuple of (file_path, file_content) or (None, None) if not found
        """
        file_path = None
        file_content = None

        # Method 1: Try to get File document by file_url
        try:
            file_doc = frappe.get_doc("File", {"file_url": file_url})
            if file_doc:
                file_path = file_doc.get_full_path()
                if hasattr(file_doc, "get_content"):
                    file_content = file_doc.get_content()
        except frappe.DoesNotExistError:
            pass
        except Exception:
            pass

        # Method 2: Try to find by sanitized file name
        if not file_path:
            try:
                file_doc = frappe.get_doc("File", {"file_name": filename})
                if file_doc:
                    file_path = file_doc.get_full_path()
                    if hasattr(file_doc, "get_content"):
                        file_content = file_doc.get_content()
            except frappe.DoesNotExistError:
                pass
            except Exception:
                pass

        return file_path, file_content

    def _try_direct_path_construction(self, filename: str) -> Optional[str]:
        """
        Try to construct file path directly using common Frappe file locations.

        Args:
            filename: Sanitized filename

        Returns:
            Absolute file path if found and safe, None otherwise
        """
        possible_paths = [
            frappe.get_site_path("public", "files", filename),
            frappe.get_site_path("private", "files", filename),
            os.path.join(frappe.get_site_path(), "public", "files", filename),
            os.path.join(frappe.get_site_path(), "private", "files", filename),
        ]

        for path in possible_paths:
            if os.path.exists(path) and self.validate_file_path(path):
                return path

        return None

    def _handle_file_not_found(self, file_url: str, filename: str):
        """
        Handle file not found with helpful debug information.

        Args:
            file_url: Original file URL
            filename: Sanitized filename

        Raises:
            frappe.ValidationError: Always - this is an error handler
        """
        files = frappe.get_all(
            "File",
            fields=["name", "file_name", "file_url", "is_private"],
            filters=[["file_name", "like", f"%{filename}%"]],
        )

        debug_info = f"File URL: {file_url}\n"
        debug_info += f"Looking for filename: {filename}\n"
        if files:
            debug_info += f"Found {len(files)} similar files:\n"
            for f in files[:5]:  # Show max 5 files
                debug_info += f"  - {f['file_name']} ({f['file_url']})\n"
        else:
            debug_info += "No files found in database.\n"

        frappe.throw(_("File not found. {0}").format(debug_info))

    def _parse_file_data(
        self, file_path: Optional[str], file_content: Optional[bytes], filename: str
    ) -> List[Dict]:
        """
        Parse file data from path or content.

        Args:
            file_path: Absolute file path (if available)
            file_content: File content as bytes (if available)
            filename: Filename for format detection

        Returns:
            List of dictionaries representing rows

        Raises:
            frappe.ValidationError: If file cannot be parsed
        """
        if file_path and os.path.exists(file_path):
            return self._read_file_from_path(file_path)
        elif file_content:
            return self._read_file_from_content(file_content, filename)
        else:
            frappe.throw(_("Could not access file content. File path: {0}").format(file_path))

    def validate_file_path(self, file_path: str) -> bool:
        """
        Validate file path is within allowed directories (security check).

        Prevents path traversal attacks by ensuring file is within site directory.

        Args:
            file_path: Path to validate

        Returns:
            True if path is safe, False otherwise
        """
        try:
            # Get absolute path and resolve any symlinks
            abs_path = os.path.abspath(os.path.realpath(file_path))
            site_path = os.path.abspath(frappe.get_site_path())

            # Ensure file is within site directory structure
            return abs_path.startswith(site_path)
        except OSError:
            return False

    def _read_file_from_path(self, file_path: str) -> List[Dict]:
        """
        Read file from filesystem path.

        Supports CSV and Excel formats with multiple encoding detection.

        Args:
            file_path: Absolute file path

        Returns:
            List of dictionaries

        Raises:
            frappe.ValidationError: If file cannot be read
        """
        # Handle Excel files if pandas is available
        if file_path.lower().endswith(".xlsx") or file_path.lower().endswith(".xls"):
            if not PANDAS_AVAILABLE:
                frappe.throw(
                    _(
                        "Excel files require pandas library. Please install pandas or convert to CSV format first."
                    )
                )

            try:
                # Read Excel file using pandas
                df = pd.read_excel(
                    file_path, engine="openpyxl" if file_path.lower().endswith(".xlsx") else None
                )
                # Convert to list of dictionaries and remove empty rows
                records = df.to_dict("records")
                return [
                    record
                    for record in records
                    if any(str(v).strip() for v in record.values() if v is not None)
                ]
            except Exception as e:
                frappe.throw(
                    _("Error reading Excel file: {0}. Please try converting to CSV format.").format(str(e))
                )

        # Read and parse CSV with BOM handling
        try:
            # Try UTF-8 with BOM first, then common encodings
            encodings_to_try = ["utf-8-sig", "utf-8", "iso-8859-1", "windows-1252"]

            for encoding in encodings_to_try:
                try:
                    with open(file_path, "r", encoding=encoding) as csvfile:
                        return self.parse_csv_content(csvfile)
                except UnicodeDecodeError:
                    continue
                except (UnicodeDecodeError, OSError) as e:
                    # If it's not an encoding issue, re-raise
                    if "codec" not in str(e).lower():
                        raise
                    continue

            frappe.throw(_("Could not read file with any supported encoding. Please check file format."))

        except Exception as e:
            frappe.throw(_("Error reading CSV file: {0}").format(str(e)))

    def _read_file_from_content(self, file_content: bytes, filename: str) -> List[Dict]:
        """
        Read file from content bytes.

        Args:
            file_content: File content as bytes
            filename: Filename for format detection

        Returns:
            List of dictionaries

        Raises:
            frappe.ValidationError: If file cannot be parsed
        """
        # Handle Excel files if pandas is available
        if filename.lower().endswith(".xlsx") or filename.lower().endswith(".xls"):
            if not PANDAS_AVAILABLE:
                frappe.throw(
                    _(
                        "Excel files require pandas library. Please install pandas or convert to CSV format first."
                    )
                )

            try:
                # Read Excel file using pandas from bytes
                df = pd.read_excel(
                    io.BytesIO(file_content),
                    engine="openpyxl" if filename.lower().endswith(".xlsx") else None,
                )
                # Convert to list of dictionaries
                return df.to_dict("records")
            except Exception as e:
                frappe.throw(
                    _("Error reading Excel file: {0}. Please try converting to CSV format.").format(str(e))
                )

        # Read and parse CSV from content
        try:
            # Decode content to string
            content_str = file_content.decode(self.encoding or "utf-8")
            csvfile = io.StringIO(content_str)
            return self.parse_csv_content(csvfile)
        except UnicodeDecodeError:
            frappe.throw(
                _("File encoding error. Please check the encoding setting or try a different encoding.")
            )

    def parse_csv_content(self, csvfile) -> List[Dict]:
        """
        Parse CSV content from file-like object.

        Features:
        - Automatic delimiter detection
        - Filters empty rows
        - Cleans null values

        Args:
            csvfile: File-like object containing CSV data

        Returns:
            List of dictionaries with cleaned data

        Raises:
            frappe.ValidationError: If CSV cannot be parsed
        """
        # Try to detect delimiter, with fallback to common delimiters
        sample = csvfile.read(1024)
        csvfile.seek(0)

        data = []
        reader = None

        # Try to detect delimiter
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            reader = csv.DictReader(csvfile, dialect=dialect)
            data = list(reader)
        except csv.Error:
            # Fallback: try common delimiters one by one
            csvfile.seek(0)
            for delimiter in [",", ";", "\t"]:
                try:
                    csvfile.seek(0)
                    reader = csv.DictReader(csvfile, delimiter=delimiter)
                    # Test if we can read at least one row
                    first_row = next(reader, None)
                    if first_row and len(first_row) > 1:  # At least 2 columns
                        csvfile.seek(0)
                        reader = csv.DictReader(csvfile, delimiter=delimiter)
                        data = [first_row] + list(reader)
                        break
                except (csv.Error, ValueError):
                    continue

            if not data:
                # If all delimiters fail, throw error
                frappe.throw(
                    _(
                        "Could not determine CSV delimiter. Please ensure your file uses comma (,), semicolon (;), or tab delimiters."
                    )
                )

        # Filter out completely empty rows and clean data
        filtered_data = []
        for row in data:
            # Check if row has any meaningful data
            has_data = any(
                value
                and str(value).strip()
                and str(value).strip() != "-"
                and str(value).strip().lower() != "nb"
                for value in row.values()
            )
            if has_data:
                # Clean up the row data
                cleaned_row = {}
                for key, value in row.items():
                    if (
                        value is None
                        or str(value).strip() == ""
                        or str(value).strip() == "-"
                        or str(value).strip().lower() == "nb"
                    ):
                        cleaned_row[key] = None
                    else:
                        cleaned_row[key] = str(value).strip()
                filtered_data.append(cleaned_row)

        return filtered_data
