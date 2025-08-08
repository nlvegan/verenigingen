"""
Date range chunking for API limits in eBoekhouden migration

Handles automatic splitting of date ranges to respect API limits
and ensures complete data retrieval.
"""

from datetime import datetime, timedelta

import frappe
from frappe.utils import add_days, date_diff, getdate


class DateRangeChunker:
    """Manages date range chunking for API calls"""

    def __init__(self, api_limit=500, safety_margin=0.9):
        """
        Initialize chunker

        Args:
            api_limit: Maximum records per API call (default: 500 for SOAP)
            safety_margin: Use only this fraction of limit for safety (default: 0.9)
        """
        self.api_limit = api_limit
        self.effective_limit = int(api_limit * safety_margin)
        self.chunk_statistics = []

    def calculate_optimal_chunks(self, from_date, to_date, estimated_records_per_day=10):
        """
        Calculate optimal date chunks based on estimated volume

        Args:
            from_date: Start date
            to_date: End date
            estimated_records_per_day: Average records per day estimate

        Returns:
            List of date range tuples
        """
        from_date = getdate(from_date)
        to_date = getdate(to_date)

        # Calculate total days
        total_days = date_diff(to_date, from_date) + 1

        # Estimate total records
        estimated_total = total_days * estimated_records_per_day

        # Calculate chunks needed
        chunks_needed = max(1, int(estimated_total / self.effective_limit) + 1)

        # Calculate days per chunk
        days_per_chunk = max(1, total_days // chunks_needed)

        # Generate chunks
        chunks = []
        current_date = from_date

        while current_date <= to_date:
            chunk_end = min(add_days(current_date, days_per_chunk - 1), to_date)

            chunks.append(
                {
                    "from_date": current_date,
                    "to_date": chunk_end,
                    "estimated_records": date_diff(chunk_end, current_date) * estimated_records_per_day,
                }
            )

            current_date = add_days(chunk_end, 1)

        return chunks

    def adaptive_chunk_processing(self, from_date, to_date, fetch_function, process_function):
        """
        Process data in adaptive chunks that adjust based on actual volumes

        Args:
            from_date: Start date
            to_date: End date
            fetch_function: Function to fetch data (receives from_date, to_date)
            process_function: Function to process fetched data

        Returns:
            Processing results with statistics
        """
        results = {"total_processed": 0, "chunks_processed": 0, "failed_chunks": [], "chunk_details": []}

        # Start with weekly chunks
        current_chunk_size = 7  # days
        current_date = getdate(from_date)
        end_date = getdate(to_date)

        while current_date <= end_date:
            chunk_end = min(add_days(current_date, current_chunk_size - 1), end_date)

            chunk_result = self._process_single_chunk(
                current_date, chunk_end, fetch_function, process_function
            )

            results["chunks_processed"] += 1
            results["chunk_details"].append(chunk_result)

            if chunk_result["success"]:
                results["total_processed"] += chunk_result["records_processed"]

                # Adjust chunk size based on results
                if chunk_result["records_fetched"] > 0:
                    # Calculate optimal chunk size
                    records_per_day = chunk_result["records_fetched"] / chunk_result["days"]
                    optimal_days = (
                        int(self.effective_limit / records_per_day)
                        if records_per_day > 0
                        else current_chunk_size
                    )

                    # Smooth adjustment to avoid drastic changes
                    current_chunk_size = int((current_chunk_size + optimal_days) / 2)
                    current_chunk_size = max(1, min(current_chunk_size, 30))  # Between 1 and 30 days

                    frappe.logger().info(
                        f"Adjusted chunk size to {current_chunk_size} days based on "
                        "{records_per_day:.1f} records/day"
                    )
            else:
                results["failed_chunks"].append(chunk_result)

                # Reduce chunk size on failure
                if chunk_result.get("reason") == "limit_exceeded":
                    current_chunk_size = max(1, current_chunk_size // 2)
                    frappe.logger().warning(f"Reduced chunk size to {current_chunk_size} days due to limit")

                    # Retry the same date range with smaller chunk
                    continue

            # Move to next chunk
            current_date = add_days(chunk_end, 1)

        return results

    def _process_single_chunk(self, from_date, to_date, fetch_function, process_function):
        """Process a single date chunk"""
        chunk_info = {
            "from_date": str(from_date),
            "to_date": str(to_date),
            "days": date_diff(to_date, from_date) + 1,
            "start_time": datetime.now(),
            "success": False,
        }

        try:
            # Fetch data for chunk
            data = fetch_function(from_date, to_date)

            # Count records
            record_count = 0
            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, list):
                        record_count += len(value)
            elif isinstance(data, list):
                record_count = len(data)

            chunk_info["records_fetched"] = record_count

            # Check if we hit the limit
            if record_count >= self.api_limit:
                chunk_info["success"] = False
                chunk_info["reason"] = "limit_exceeded"
                chunk_info["error"] = "Chunk returned {record_count} records, likely hit API limit"
                return chunk_info

            # Process the data
            process_result = process_function(data)

            chunk_info["success"] = True
            chunk_info["records_processed"] = process_result.get("processed", record_count)
            chunk_info["processing_errors"] = process_result.get("errors", [])

        except Exception as e:
            chunk_info["success"] = False
            chunk_info["reason"] = "exception"
            chunk_info["error"] = str(e)
            frappe.logger().error(f"Chunk processing error: {str(e)}")

        finally:
            chunk_info["end_time"] = datetime.now()
            chunk_info["duration"] = (chunk_info["end_time"] - chunk_info["start_time"]).total_seconds()

        return chunk_info

    def split_by_month(self, from_date, to_date):
        """Split date range into monthly chunks"""
        chunks = []
        current_date = getdate(from_date)
        end_date = getdate(to_date)

        while current_date <= end_date:
            # Get last day of current month
            if current_date.month == 12:
                next_month = current_date.replace(year=current_date.year + 1, month=1, day=1)
            else:
                next_month = current_date.replace(month=current_date.month + 1, day=1)

            month_end = add_days(next_month, -1)
            chunk_end = min(month_end, end_date)

            chunks.append(
                {"from_date": current_date, "to_date": chunk_end, "label": current_date.strftime("%B %Y")}
            )

            current_date = next_month

        return chunks

    def estimate_optimal_strategy(self, from_date, to_date, sample_fetch_function):
        """
        Estimate optimal chunking strategy by sampling

        Args:
            from_date: Start date
            to_date: End date
            sample_fetch_function: Function to fetch sample data

        Returns:
            Recommended strategy with estimates
        """
        # Take a small sample (e.g., 7 days)
        sample_days = min(7, date_diff(to_date, from_date) + 1)
        sample_end = add_days(from_date, sample_days - 1)

        try:
            # Fetch sample data
            sample_data = sample_fetch_function(from_date, sample_end)

            # Count records
            sample_count = 0
            if isinstance(sample_data, dict):
                for value in sample_data.values():
                    if isinstance(value, list):
                        sample_count += len(value)
            elif isinstance(sample_data, list):
                sample_count = len(sample_data)

            # Calculate estimates
            records_per_day = sample_count / sample_days if sample_days > 0 else 0
            total_days = date_diff(to_date, from_date) + 1
            estimated_total = records_per_day * total_days

            # Recommend strategy
            if estimated_total <= self.effective_limit:
                strategy = "single_request"
                chunks_needed = 1
            elif records_per_day < 10:
                strategy = "monthly"
                chunks_needed = len(self.split_by_month(from_date, to_date))
            elif records_per_day < 50:
                strategy = "weekly"
                chunks_needed = int(total_days / 7) + 1
            else:
                strategy = "daily"
                chunks_needed = total_days

            return {
                "records_per_day": round(records_per_day, 2),
                "estimated_total": int(estimated_total),
                "recommended_strategy": strategy,
                "chunks_needed": chunks_needed,
                "sample_size": sample_count,
                "confidence": "high" if sample_count > 50 else "medium" if sample_count > 10 else "low",
            }

        except Exception as e:
            frappe.logger().error(f"Error estimating optimal strategy: {str(e)}")
            return {
                "recommended_strategy": "weekly",
                "chunks_needed": int(date_diff(to_date, from_date) / 7) + 1,
                "confidence": "low",
                "error": str(e),
            }


def process_with_date_chunks(
    from_date, to_date, fetch_function, process_function, chunk_strategy="adaptive", api_limit=500
):
    """
    High-level function to process data with automatic date chunking

    Args:
        from_date: Start date
        to_date: End date
        fetch_function: Function to fetch data
        process_function: Function to process data
        chunk_strategy: "adaptive", "monthly", "weekly", or "daily"
        api_limit: API record limit

    Returns:
        Processing results
    """
    chunker = DateRangeChunker(api_limit=api_limit)

    if chunk_strategy == "adaptive":
        return chunker.adaptive_chunk_processing(from_date, to_date, fetch_function, process_function)

    elif chunk_strategy == "monthly":
        chunks = chunker.split_by_month(from_date, to_date)

    elif chunk_strategy == "weekly":
        chunks = []
        current = getdate(from_date)
        while current <= getdate(to_date):
            week_end = min(add_days(current, 6), getdate(to_date))
            chunks.append({"from_date": current, "to_date": week_end})
            current = add_days(week_end, 1)

    elif chunk_strategy == "daily":
        chunks = []
        current = getdate(from_date)
        while current <= getdate(to_date):
            chunks.append({"from_date": current, "to_date": current})
            current = add_days(current, 1)

    else:
        # Single chunk
        chunks = [{"from_date": from_date, "to_date": to_date}]

    # Process chunks
    results = {"total_processed": 0, "chunks_processed": 0, "failed_chunks": [], "chunk_details": []}

    for chunk in chunks:
        chunk_result = chunker._process_single_chunk(
            chunk["from_date"], chunk["to_date"], fetch_function, process_function
        )

        results["chunks_processed"] += 1
        results["chunk_details"].append(chunk_result)

        if chunk_result["success"]:
            results["total_processed"] += chunk_result.get("records_processed", 0)
        else:
            results["failed_chunks"].append(chunk_result)

    return results


@frappe.whitelist()
def estimate_migration_chunks(migration_name):
    """Estimate optimal chunking strategy for a migration"""
    # migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)

    # Create sample fetch function
    def sample_fetch(from_date, to_date):
        # This would call the actual API with date range
        # For now, return estimate based on typical volumes
        days = date_diff(to_date, from_date) + 1
        return {
            "invoices": [{}] * (days * 5),  # Estimate 5 invoices per day
            "payments": [{}] * (days * 10),  # Estimate 10 payments per day
        }

    chunker = DateRangeChunker()
    strategy = chunker.estimate_optimal_strategy(migration_doc.from_date, migration_doc.to_date, sample_fetch)

    return strategy
