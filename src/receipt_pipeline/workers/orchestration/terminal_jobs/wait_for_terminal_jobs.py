
"""Wait until ingested jobs reach a terminal DB state (SUCCESS, NEEDS_REVIEW, or legacy DLQ)."""

from __future__ import annotations  
import time  
from sqlalchemy import select  

from receipt_pipeline.db.models import InvoiceJob, JobStatus  # DB model + status enum
from receipt_pipeline.db.query_retry import scalars_all_with_retry  # safe DB query with retry
from receipt_pipeline.db.session import SessionLocal  
from receipt_pipeline.workers.human_review_store import finalize_needs_human_review
from receipt_pipeline.workers.utils.pipeline_log import pl_info  


_TERMINAL = frozenset(
    {
        JobStatus.SUCCESS.value,        # job completed successfully
        JobStatus.NEEDS_REVIEW.value,  # needs human review
        JobStatus.DLQ.value,           # dead letter queue (failed permanently)
    }
)


def _route_timed_out_jobs_to_human_review(pending_job_ids: set[str], *, timeout_sec: float) -> set[str]:
    """
    Force-route non-terminating jobs to NEEDS_REVIEW so they do not remain PENDING forever.
    Returns the subset successfully rerouted.
    """
    if not pending_job_ids:
        return set()

    session = SessionLocal()
    rerouted: set[str] = set()
    try:
        for jid in sorted(pending_job_ids):
            try:
                finalize_needs_human_review(
                    session,
                    jid,
                    stage="orchestrator_timeout",
                    reason=f"orchestrator_timeout_after_{int(timeout_sec)}s",
                )
                rerouted.add(jid)
            except Exception as e:
                session.rollback()
                pl_info(
                    "orchestrator",
                    "timeout_reroute_failed",
                    job_id=jid,
                    error=str(e),
                )
        return rerouted
    finally:
        session.close()


def wait_for_terminal_jobs(
    job_ids: list[str],
    *,
    timeout_sec: float = 3600.0,  
    poll_sec: float = 1.0,      
) -> tuple[list[str], list[str]]:
    """
    Poll the DB until every job_id is terminal (SUCCESS / NEEDS_REVIEW / DLQ) or timeout.
    Returns (success_ids, needs_review_ids).
    """

    # If no jobs passed → nothing to wait for
    if not job_ids:
        return [], []

    # Remove duplicate job IDs 
    job_ids = list(dict.fromkeys(job_ids))

    # Set timeout deadline using monotonic clock (safe for time comparisons)
    deadline = time.monotonic() + timeout_sec

    # Track jobs that are still not finished
    pending = set(job_ids)

    # Log start of waiting phase
    pl_info(
        "orchestrator",
        "wait_terminal_start",
        jobs=len(job_ids),
        timeout_sec=timeout_sec,
        poll_sec=poll_sec,
        meaning="blocks_until_SUCCESS_or_NEEDS_REVIEW_or_legacy_DLQ",
    )

    # Used to log "still processing" message every 30 seconds (not too frequent)
    last_stall_log = time.monotonic()

    # MAIN LOOP → keep checking DB until:
    # 1. timeout reached OR
    # 2. all jobs finished
    while time.monotonic() < deadline and pending:

        # Create a new DB session (important for fresh reads)
        session = SessionLocal()
        try:
            # Build query → fetch all pending jobs from DB
            stmt = select(InvoiceJob).where(InvoiceJob.job_id.in_(pending))

            # Execute query safely (handles SQLite locking retries)
            rows = scalars_all_with_retry(session, stmt)

            # Convert list → dictionary for fast lookup (job_id → row)
            by_id = {r.job_id: r for r in rows}

            # Check each pending job
            for jid in list(pending):
                row = by_id.get(jid)

                # If job exists and has reached terminal state → remove from pending
                if row and row.status in _TERMINAL:
                    pending.discard(jid)

        finally:
            # Always close session to avoid connection leaks
            session.close()

        # If there are still unfinished jobs
        if pending:
            now = time.monotonic()

            # Log progress every 30 seconds (avoid log spam)
            if now - last_stall_log >= 5.0:
                pl_info(
                    "orchestrator",
                    "still_processing",
                    pending_count=len(pending),
                    sample_job_ids=list(pending)[:8],  # show a few example jobs
                    hint="OCR_rules_LLM_and_validation_still_in_flight",
                )
                last_stall_log = now

            # Wait before next DB poll (prevents CPU overuse)
            time.sleep(poll_sec)

    # If loop exited but some jobs are still pending → timeout occurred
    if pending:
        timed_out = set(pending)
        pl_info(
            "orchestrator",
            "timeout_reroute_start",
            timeout_sec=timeout_sec,
            pending_count=len(timed_out),
            sample_job_ids=sorted(timed_out)[:8],
            action="force_route_to_human_review",
        )
        rerouted = _route_timed_out_jobs_to_human_review(timed_out, timeout_sec=timeout_sec)
        unresolved = timed_out - rerouted
        if unresolved:
            raise TimeoutError(
                "Timed out waiting for jobs and reroute failed for some jobs. "
                f"Still pending: {sorted(unresolved)[:20]}"
            )
        pl_info(
            "orchestrator",
            "timeout_reroute_done",
            rerouted_count=len(rerouted),
            sample_job_ids=sorted(rerouted)[:8],
        )

    # FINAL FETCH → get latest state of all jobs
    session = SessionLocal()
    try:
        stmt = select(InvoiceJob).where(InvoiceJob.job_id.in_(job_ids))
        rows = scalars_all_with_retry(session, stmt)

        # Separate successful jobs
        ok = [r.job_id for r in rows if r.status == JobStatus.SUCCESS.value]

        # Separate jobs needing review or failed
        needs_review = [
            r.job_id
            for r in rows
            if r.status in (JobStatus.NEEDS_REVIEW.value, JobStatus.DLQ.value)
        ]

        # Log completion summary
        pl_info(
            "orchestrator",
            "wait_terminal_done",
            success=len(ok),
            needs_review=len(needs_review),
            job_ids_checked=len(job_ids),
        )

        return ok, needs_review

    finally:
        # Close session after final fetch
        session.close()