# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
Queue Management Utilities

Provides queue-aware processing utilities to prevent RQ queue overload
during bulk operations like CSV imports.

Key Features:
- Check queue capacity before operations
- Wait for queue to drain when full
- Configure queue limits via site config
- Synchronous fallback when queue is overloaded
"""

import time
from typing import Callable, Optional, TypeVar

import frappe
from frappe import _
from frappe.utils import cint

# Default limits
DEFAULT_MAX_QUEUE_DEPTH = 400  # Stay well below Frappe's 500 default
DEFAULT_QUEUE_WAIT_TIMEOUT = 120  # Maximum seconds to wait for queue capacity
DEFAULT_CHECK_INTERVAL = 2.0  # Seconds between queue depth checks

T = TypeVar("T")


def get_queue_depth(queue_name: str = "long") -> int:
    """
    Get current depth of specified Redis queue.

    Args:
        queue_name: Name of queue to check (default, short, long)

    Returns:
        Number of jobs currently in the queue, or 0 if check fails
    """
    try:
        from frappe.utils.background_jobs import get_bench_id, get_redis_conn

        conn = get_redis_conn()
        bench_id = get_bench_id()
        queue_key = f"rq:queue:{bench_id}:{queue_name}"

        # Get queue length (number of jobs waiting to be processed)
        queue_length = conn.llen(queue_key)
        return queue_length or 0

    except Exception as e:
        frappe.logger().warning(f"Could not check queue depth: {str(e)}")
        return 0


def get_total_queue_depth() -> int:
    """Get total depth across all queues (default, short, long)"""
    total = 0
    for queue in ["default", "short", "long"]:
        total += get_queue_depth(queue)
    return total


def get_max_queue_depth() -> int:
    """
    Get maximum allowed queue depth from config.

    Checks:
    1. Site-specific config: max_queued_jobs
    2. Common site config: max_queued_jobs
    3. Falls back to DEFAULT_MAX_QUEUE_DEPTH

    Returns:
        Maximum allowed queue depth
    """
    # Try site config first
    max_jobs = cint(frappe.conf.get("max_queued_jobs"))
    if max_jobs > 0:
        # Use 80% of configured max to leave buffer
        return int(max_jobs * 0.8)

    return DEFAULT_MAX_QUEUE_DEPTH


def has_queue_capacity(
    queue_name: str = "long",
    required_capacity: int = 1,
    max_depth: Optional[int] = None,
) -> bool:
    """
    Check if queue has capacity for additional jobs.

    Args:
        queue_name: Name of queue to check
        required_capacity: Number of jobs we want to add
        max_depth: Maximum depth to allow (defaults to get_max_queue_depth())

    Returns:
        True if queue has capacity, False otherwise
    """
    if max_depth is None:
        max_depth = get_max_queue_depth()

    current_depth = get_queue_depth(queue_name)
    available = max_depth - current_depth

    return available >= required_capacity


def wait_for_queue_capacity(
    queue_name: str = "long",
    max_depth: Optional[int] = None,
    timeout: int = DEFAULT_QUEUE_WAIT_TIMEOUT,
    check_interval: float = DEFAULT_CHECK_INTERVAL,
    log_prefix: str = "",
) -> bool:
    """
    Wait for queue to have capacity before proceeding.

    Uses exponential backoff with configurable maximum wait time.

    Args:
        queue_name: Name of queue to check
        max_depth: Maximum depth to allow
        timeout: Maximum seconds to wait
        check_interval: Initial interval between checks (will increase)
        log_prefix: Prefix for log messages

    Returns:
        True if capacity became available, False if timeout reached
    """
    # Skip during tests
    if frappe.flags.in_test:
        return True

    if max_depth is None:
        max_depth = get_max_queue_depth()

    current_depth = get_queue_depth(queue_name)

    if current_depth < max_depth:
        return True  # Already has capacity

    frappe.logger().info(
        f"{log_prefix}Queue throttling: {current_depth} jobs in {queue_name} queue "
        f"(max: {max_depth}), waiting for capacity..."
    )

    wait_start = time.time()
    current_interval = check_interval
    max_interval = 10.0  # Cap at 10 seconds between checks

    while True:
        elapsed = time.time() - wait_start

        if elapsed >= timeout:
            frappe.logger().warning(
                f"{log_prefix}Queue throttling timeout after {elapsed:.1f}s, "
                f"queue depth still at {current_depth}"
            )
            return False

        time.sleep(current_interval)
        current_depth = get_queue_depth(queue_name)

        if current_depth < max_depth:
            frappe.logger().info(
                f"{log_prefix}Queue capacity available after {elapsed:.1f}s "
                f"(depth: {current_depth}/{max_depth})"
            )
            return True

        # Exponential backoff
        current_interval = min(current_interval * 1.5, max_interval)

        frappe.logger().debug(
            f"{log_prefix}Queue still full ({current_depth} jobs), "
            f"waiting {current_interval:.1f}s before retry"
        )


def enqueue_with_throttle(
    method: str,
    queue: str = "long",
    timeout: int = 300,
    max_queue_depth: Optional[int] = None,
    queue_wait_timeout: int = DEFAULT_QUEUE_WAIT_TIMEOUT,
    fallback_sync: bool = False,
    **kwargs,
) -> Optional[str]:
    """
    Enqueue a job with queue capacity checking.

    If the queue is full:
    - Waits for capacity up to queue_wait_timeout
    - If fallback_sync is True and timeout reached, executes synchronously
    - Otherwise raises frappe.QueueOverloaded

    Args:
        method: Method path to enqueue
        queue: Queue name (default, short, long)
        timeout: Job timeout in seconds
        max_queue_depth: Maximum queue depth to allow
        queue_wait_timeout: How long to wait for capacity
        fallback_sync: If True, run synchronously when queue is overloaded
        **kwargs: Arguments to pass to the method

    Returns:
        Job ID if enqueued, None if executed synchronously

    Raises:
        frappe.QueueOverloaded: If queue is full and fallback_sync is False
    """
    # Wait for capacity
    has_capacity = wait_for_queue_capacity(
        queue_name=queue,
        max_depth=max_queue_depth,
        timeout=queue_wait_timeout,
        log_prefix=f"[{method}] ",
    )

    if not has_capacity:
        if fallback_sync:
            frappe.logger().warning(f"Queue overloaded, executing {method} synchronously")
            # Execute synchronously
            frappe.call(method, **kwargs)
            return None
        else:
            current_depth = get_queue_depth(queue)
            frappe.throw(
                _("Background job queue is overloaded ({0} jobs). " "Please wait and try again.").format(
                    current_depth
                ),
                exc=frappe.QueueOverloaded,
            )

    # Enqueue the job
    job = frappe.enqueue(
        method=method,
        queue=queue,
        timeout=timeout,
        **kwargs,
    )

    return job.id if job else None


def process_in_batches_with_throttle(
    items: list,
    process_func: Callable[[list], T],
    batch_size: int = 50,
    queue_check_interval: int = 5,
    max_queue_depth: Optional[int] = None,
    log_prefix: str = "",
) -> list:
    """
    Process items in batches, pausing when queue gets full.

    This is useful for bulk operations that might trigger background jobs.
    Between batches, it checks queue depth and waits if necessary.

    Args:
        items: List of items to process
        process_func: Function to process each batch, takes list and returns result
        batch_size: Number of items per batch
        queue_check_interval: Check queue every N batches
        max_queue_depth: Maximum queue depth before pausing
        log_prefix: Prefix for log messages

    Returns:
        List of results from each batch
    """
    results = []
    total_items = len(items)
    total_batches = (total_items + batch_size - 1) // batch_size

    for batch_num, batch_start in enumerate(range(0, total_items, batch_size), 1):
        batch_end = min(batch_start + batch_size, total_items)
        batch = items[batch_start:batch_end]

        frappe.logger().info(
            f"{log_prefix}Processing batch {batch_num}/{total_batches} "
            f"(items {batch_start + 1}-{batch_end} of {total_items})"
        )

        # Check queue capacity periodically
        if batch_num % queue_check_interval == 0:
            wait_for_queue_capacity(
                max_depth=max_queue_depth,
                log_prefix=f"{log_prefix}[Batch {batch_num}] ",
            )

        # Process the batch
        result = process_func(batch)
        results.append(result)

        # Commit after each batch to avoid long transactions
        frappe.db.commit()

    return results


def get_queue_status() -> dict:
    """
    Get comprehensive queue status for monitoring.

    Returns:
        Dictionary with queue depths, limits, and health status
    """
    status = {
        "queues": {},
        "total_depth": 0,
        "max_allowed": get_max_queue_depth(),
        "capacity_available": True,
        "workers_active": 0,
    }

    for queue_name in ["default", "short", "long"]:
        depth = get_queue_depth(queue_name)
        status["queues"][queue_name] = depth
        status["total_depth"] += depth

    # Check if we have capacity
    status["capacity_available"] = status["total_depth"] < status["max_allowed"]

    # Try to get worker count
    try:
        from frappe.utils.background_jobs import get_workers

        workers = get_workers()
        status["workers_active"] = len([w for w in workers if w.state == "busy"])
    except Exception:
        pass

    return status
