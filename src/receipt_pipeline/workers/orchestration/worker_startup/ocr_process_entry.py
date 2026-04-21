"""Multiprocessing target: run the OCR worker loop in a child process."""

from __future__ import annotations


def ocr_process_entry(stop_event, worker_id: int) -> None:
    from receipt_pipeline.workers.core.ocr_worker import ocr_worker_loop

    ocr_worker_loop(stop_event, worker_id)
