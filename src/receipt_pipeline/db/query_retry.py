"""SQLite-friendly session execution (brief retry on database locked)."""

from __future__ import annotations

import time

from sqlalchemy.exc import OperationalError


def scalars_all_with_retry(session, stmt, *, attempts: int = 12) -> list:
    delay = 0.05
    #Stores the last error to raise later if all retries fail
    last: OperationalError | None = None
    for i in range(attempts):
        try:
            #Executes SQL query
            return list(session.scalars(stmt).all())
        except OperationalError as e:
            last = e
            #if not locked or busy error → raise immediately, don't retry
            if "locked" not in str(e).lower() and "busy" not in str(e).lower():
                raise
            #If it's the final attempt → stop retrying
            if i == attempts - 1:
                break
            #wait before trying again
            time.sleep(delay)
            #exponential backoff
            delay = min(delay * 1.5, 1.0)
    assert last is not None
    raise last
