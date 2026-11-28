"""Per-user dispatch lock shared by the talking and editing stages.

Both stages are advanced from several places at once: the page polling every
few seconds, the submit request, and the API's sweeper thread (one per API
process). Without a lock two callers can both see free slots and start more
items than the per-user limit, or both create the same next step.

On PostgreSQL this is a session-level advisory lock held on its own
connection, because the dispatch code commits (and rolls back) its ORM session
several times. On other databases (the SQLite route tests) it always succeeds.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class DispatchLock:
    """``pg_try_advisory_lock`` on ``polaris:video-<stage>-dispatch:<user>``."""

    def __init__(self, session: Session, stage: str, user_id: str) -> None:
        self.bind = session.get_bind()
        self.key = f"polaris:video-{stage}-dispatch:{user_id}"
        self.connection: Any = None

    def acquire(self) -> bool:
        if self.bind.dialect.name != "postgresql":
            return True
        connection = self.bind.connect()  # type: ignore[union-attr]
        try:
            got = bool(
                connection.execute(
                    text("SELECT pg_try_advisory_lock(hashtext(:key))"),
                    {"key": self.key},
                ).scalar()
            )
            # Session-level lock: end the transaction so the lock connection is
            # not left "idle in transaction" while the dispatch runs.
            connection.commit()
        except BaseException:
            connection.close()
            raise
        if not got:
            connection.close()
            return False
        self.connection = connection
        return True

    def release(self) -> None:
        connection, self.connection = self.connection, None
        if connection is None:
            return
        try:
            connection.execute(
                text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": self.key}
            )
            connection.commit()
        except BaseException:
            # A pooled connection keeps session locks: never hand this one back.
            connection.invalidate()
            raise
        finally:
            connection.close()
