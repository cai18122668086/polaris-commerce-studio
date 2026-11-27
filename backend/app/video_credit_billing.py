"""Hold, settle and release workspace credits for paid video actions.

Video tasks use the same account, lots and ledger as image jobs
(``services.reserve_credits``/``settle_credits``/``release_credits``), with the
hold keyed to the video task (``owner_type``/``owner_id``) and the billed action
(``charge_action``) instead of a job.

* Submit: ``hold()`` runs in the same transaction that creates the task, so an
  insufficient balance (402 ``BUDGET_LIMIT_EXCEEDED``) creates nothing.
* Outcome: ``reconcile_owner()`` reads the task's own status and settles the hold
  on success or releases it on failure, cancel or timeout. Workers call it when
  they finish; the editing maintenance loop sweeps every active hold so a hold
  never outlives a task whose worker crashed or hit a time limit.
* Idempotent: one active hold per task and action (partial unique index), a
  replayed request finds its task and never calls ``hold()`` again, and a retry
  reuses an active hold and never re-charges a settled one. Settle and release
  claim the hold with compare-and-swap under the account row lock.
* Prices come only from ``POLARIS_VIDEO_CREDIT_PRICES``. An action without a
  positive configured price is not charged, as before.
* Enforcement follows the image switch (``credit_enforcement_enabled``): when it
  is off, holds are accounting-only and never reject a request.
"""

import logging
from collections.abc import Callable
from typing import Any, Literal, cast

from fastapi import status
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .domain import CreditReservationStatus
from .errors import ApiError
from .models import (
    CreditLedgerEntryRecord,
    CreditReservationRecord,
    WorkspaceCreditAccountRecord,
    utc_now,
)
from .services import (
    _credit_reservation_is_enforced,
    credit_enforcement_enabled,
    new_id,
    quota_enabled,
)
from .video_credit_prices import ACTIONS, PRICING_VERSION
from .video_editing_task_models import EditingPlanningTaskRecord, EditingTaskRecord
from .video_generation_models import VideoGenerationRecord

logger = logging.getLogger(__name__)

OwnerType = Literal[
    "video_generation",
    "video_assistance",
    "video_voice",
    "video_editing",
    "video_planning",
    "video_cover",
]
Outcome = Literal["settle", "release"] | None

ACTIVE = CreditReservationStatus.ACTIVE.value
SETTLED = CreditReservationStatus.SETTLED.value
RELEASED = CreditReservationStatus.RELEASED.value

LABELS = {
    "lipsync": "数字人口播",
    "avatar_motion": "形象动作生成",
    "avatar_register": "形象入库",
    "voice_clone": "声音克隆",
    "editing_planning": "智能剪辑规划",
    "editing_render": "剪辑预览渲染",
    "benchmark_search": "对标搜索",
    "writing_generate": "文案生成",
    "cover_generate": "AI 封面",
}


def price_for(settings: Settings, action: str) -> int | None:
    """Configured positive price, or None (unpriced actions stay free)."""

    assert action in ACTIONS, action
    value = settings.video_credit_prices.get(action)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _holds(
    session: Session, owner_type: str, owner_id: str, action: str | None = None
) -> list[CreditReservationRecord]:
    query = select(CreditReservationRecord).where(
        CreditReservationRecord.owner_type == owner_type,
        CreditReservationRecord.owner_id == owner_id,
    )
    if action is not None:
        query = query.where(CreditReservationRecord.charge_action == action)
    return list(
        session.scalars(
            query.order_by(
                CreditReservationRecord.created_at.desc(),
                CreditReservationRecord.id.desc(),
            ).execution_options(populate_existing=True)
        )
    )


def _ledger(
    session: Session,
    account: WorkspaceCreditAccountRecord,
    reservation: CreditReservationRecord,
    entry_type: str,
    delta_balance: int,
    delta_reserved: int,
) -> None:
    session.add(
        CreditLedgerEntryRecord(
            workspace_id=account.workspace_id,
            reservation_id=reservation.id,
            job_id=None,
            description="视频创作 · "
            + LABELS.get(reservation.charge_action or "", "视频任务"),
            entry_type=entry_type,
            delta_balance_credits=delta_balance,
            delta_reserved_credits=delta_reserved,
            balance_after_credits=account.balance_credits,
            reserved_after_credits=account.reserved_credits,
        )
    )


def hold(
    session: Session,
    settings: Settings,
    workspace_id: str,
    action: str,
    owner_type: OwnerType,
    owner_id: str,
) -> CreditReservationRecord | None:
    """Reserve the action's price for a task in the caller's transaction.

    Returns the existing hold when the task already has an active or settled
    one for this action, so a retry or replay never charges twice.
    """

    credits = price_for(settings, action)
    if credits is None:
        return None
    enforced = credit_enforcement_enabled(workspace_id)
    if not (quota_enabled() or enforced):
        return None
    account = session.get(
        WorkspaceCreditAccountRecord, workspace_id, with_for_update=True
    )
    if account is None:
        if not enforced:
            return None
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "CREDIT_ACCOUNT_NOT_CONFIGURED",
            "工作区额度账户尚未配置。",
        )
    # The account row lock serialises holds per workspace, so this check and
    # the insert below cannot race with another hold for the same task.
    previous = next(iter(_holds(session, owner_type, owner_id, action)), None)
    if previous is not None and previous.status in {ACTIVE, SETTLED}:
        return previous
    if enforced:
        from .credit_memberships import refresh

        account = refresh(session, workspace_id)
    available = account.balance_credits - account.reserved_credits
    if enforced and available < credits:
        raise ApiError(
            status.HTTP_402_PAYMENT_REQUIRED,
            "BUDGET_LIMIT_EXCEEDED",
            f"当前可用积分不足：{LABELS[action]}需要 {credits} 积分，"
            f"可用 {max(0, available)} 积分，请充值后再试。",
            {
                "required_credits": credits,
                "available_credits": available,
                "action": action,
            },
        )
    reservation = CreditReservationRecord(
        id=new_id("hold"),
        workspace_id=workspace_id,
        job_id=None,
        owner_type=owner_type,
        owner_id=owner_id,
        charge_action=action,
        reserved_credits=credits,
        settled_credits=0,
        status=ACTIVE,
        pricing_snapshot={
            "pricing_version": PRICING_VERSION,
            "action": action,
            "credits": credits,
        },
    )
    if enforced:
        from .credit_memberships import allocate

        allocate(session, account, reservation, utc_now())
        changed = session.execute(
            update(WorkspaceCreditAccountRecord)
            .where(
                WorkspaceCreditAccountRecord.workspace_id == workspace_id,
                WorkspaceCreditAccountRecord.balance_credits
                - WorkspaceCreditAccountRecord.reserved_credits
                >= credits,
            )
            .values(
                reserved_credits=WorkspaceCreditAccountRecord.reserved_credits
                + credits,
                version=WorkspaceCreditAccountRecord.version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        if cast(CursorResult[Any], changed).rowcount != 1:
            raise ApiError(
                402, "BUDGET_LIMIT_EXCEEDED", "当前可用积分不足，请充值后再试。"
            )
        session.refresh(account)
    session.add(reservation)
    session.flush()
    _ledger(session, account, reservation, "reserve", 0, credits if enforced else 0)
    return reservation


def _claim(session: Session, reservation: CreditReservationRecord, values: Any) -> bool:
    claimed = session.execute(
        update(CreditReservationRecord)
        .where(
            CreditReservationRecord.id == reservation.id,
            CreditReservationRecord.status == ACTIVE,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if cast(CursorResult[Any], claimed).rowcount != 1:
        session.expire_all()
        return False
    return True


def settle(session: Session, reservation: CreditReservationRecord) -> None:
    """Charge the held price once; a second call is a no-op."""

    if reservation.status != ACTIVE:
        return
    account = session.get(
        WorkspaceCreditAccountRecord, reservation.workspace_id, with_for_update=True
    )
    if account is None:
        return
    charged = reservation.reserved_credits
    if not _claim(
        session, reservation, {"status": SETTLED, "settled_credits": charged}
    ):
        return
    enforced = _credit_reservation_is_enforced(session, reservation)
    if enforced:
        session.execute(
            update(WorkspaceCreditAccountRecord)
            .where(WorkspaceCreditAccountRecord.workspace_id == account.workspace_id)
            .values(
                reserved_credits=WorkspaceCreditAccountRecord.reserved_credits
                - reservation.reserved_credits,
                balance_credits=WorkspaceCreditAccountRecord.balance_credits - charged,
                version=WorkspaceCreditAccountRecord.version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        session.refresh(account)
    reservation.settled_credits = charged
    reservation.status = SETTLED
    _ledger(
        session,
        account,
        reservation,
        "settle",
        -charged if enforced else 0,
        -reservation.reserved_credits if enforced else 0,
    )
    session.flush()
    if enforced:
        from .credit_memberships import finish_allocation

        finish_allocation(session, account, reservation, charged)


def release(session: Session, reservation: CreditReservationRecord) -> None:
    """Return the held credits without charging; a second call is a no-op."""

    if reservation.status != ACTIVE:
        return
    account = session.get(
        WorkspaceCreditAccountRecord, reservation.workspace_id, with_for_update=True
    )
    if account is None:
        return
    if not _claim(session, reservation, {"status": RELEASED}):
        return
    released = reservation.reserved_credits
    enforced = _credit_reservation_is_enforced(session, reservation)
    if enforced:
        session.execute(
            update(WorkspaceCreditAccountRecord)
            .where(WorkspaceCreditAccountRecord.workspace_id == account.workspace_id)
            .values(
                reserved_credits=WorkspaceCreditAccountRecord.reserved_credits
                - released,
                version=WorkspaceCreditAccountRecord.version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        session.refresh(account)
    reservation.status = RELEASED
    _ledger(session, account, reservation, "release", 0, -released if enforced else 0)
    session.flush()
    if enforced:
        from .credit_memberships import finish_allocation

        finish_allocation(session, account, reservation, 0)


# --- Outcome of each task kind -------------------------------------------------


def _fresh[T](session: Session, model: type[T], key: object) -> T | None:
    """Re-read the row: callers often just changed it with a bulk UPDATE."""
    return session.get(model, key, populate_existing=True)


def _by_status(value: str, success: set[str], failure: set[str]) -> Outcome:
    if value in success:
        return "settle"
    if value in failure:
        return "release"
    return None


def _generation(session: Session, hold_: CreditReservationRecord) -> Outcome:
    from .video_generation_recovery import CONTINUATION_STAGES, TRANSIENT_ERRORS

    row = _fresh(session, VideoGenerationRecord, hold_.owner_id)
    if row is None:
        return "release"
    if (
        row.status == "failed"
        and row.error_code in TRANSIENT_ERRORS
        and row.stage in CONTINUATION_STAGES
    ):
        # Startup recovery resumes these on its own; keep the hold until the
        # resumed run finishes.
        return None
    if hold_.charge_action == "avatar_motion":
        # The motion clip is produced once the review step is reached; a later
        # rejection or registration failure does not undo that work.
        if row.details.get("review_approved"):
            return "settle"
        return _by_status(
            row.status, {"awaiting_review", "rejected", "completed"}, {"failed"}
        )
    return _by_status(row.status, {"completed"}, {"failed"})


def _assistance(session: Session, hold_: CreditReservationRecord) -> Outcome:
    from .video_assistance_models import VideoAssistanceRecord

    row = _fresh(session, VideoAssistanceRecord, hold_.owner_id)
    if row is None:
        return "release"
    return _by_status(row.status, {"completed"}, {"failed"})


def _voice(session: Session, hold_: CreditReservationRecord) -> Outcome:
    from .video_voice_models import VideoClonedVoiceRecord

    row = _fresh(session, VideoClonedVoiceRecord, hold_.owner_id)
    if row is None:
        return "release"
    return _by_status(row.status, {"ready"}, {"failed"})


def _editing_task(task: EditingTaskRecord | None) -> Outcome:
    if task is None:
        return "release"
    return _by_status(
        task.status, {"awaiting_review", "completed"}, {"failed", "cancelled"}
    )


def _editing(session: Session, hold_: CreditReservationRecord) -> Outcome:
    return _editing_task(_fresh(session, EditingTaskRecord, hold_.owner_id))


def _planning(session: Session, hold_: CreditReservationRecord) -> Outcome:
    row = _fresh(session, EditingPlanningTaskRecord, hold_.owner_id)
    if row is None:
        return "release"
    if hold_.charge_action == "editing_planning":
        return _by_status(row.status, {"completed"}, {"failed", "cancelled"})
    # editing_render held on the planning row: follows its linked preview task.
    preview = (row.result or {}).get("preview_task_id")
    if preview:
        return _editing_task(_fresh(session, EditingTaskRecord, str(preview)))
    if row.status in {"failed", "cancelled"} or (row.result or {}).get(
        "auto_preview_error_code"
    ):
        return "release"
    return None


def _cover(session: Session, hold_: CreditReservationRecord) -> Outcome:
    """Settle only an AI-background cover that passed every check."""

    from .video_cover_models import VideoCoverCandidateRecord

    row = _fresh(session, VideoCoverCandidateRecord, hold_.owner_id)
    if row is None:
        return "release"
    if row.status == "ready":
        return "settle" if row.background == "ai" else "release"
    return _by_status(row.status, set(), {"failed"})


CLASSIFIERS: dict[str, Callable[[Session, CreditReservationRecord], Outcome]] = {
    "video_generation": _generation,
    "video_assistance": _assistance,
    "video_voice": _voice,
    "video_editing": _editing,
    "video_planning": _planning,
    "video_cover": _cover,
}


def reconcile_owner(session: Session, owner_type: OwnerType, owner_id: str) -> int:
    """Settle or release every active hold of one task from its current status."""

    done = 0
    for reservation in _holds(session, owner_type, owner_id):
        if reservation.status != ACTIVE:
            continue
        outcome = CLASSIFIERS[owner_type](session, reservation)
        if outcome == "settle":
            settle(session, reservation)
            done += 1
        elif outcome == "release":
            release(session, reservation)
            done += 1
    return done


def reconcile_editing(session: Session, task_id: str) -> int:
    """An editing task plus the planning row whose preview it renders."""

    done = reconcile_owner(session, "video_editing", task_id)
    planning = session.scalar(
        select(EditingPlanningTaskRecord.id).where(
            EditingPlanningTaskRecord.result["preview_task_id"].as_string() == task_id
        )
    )
    if planning:
        done += reconcile_owner(session, "video_planning", planning)
    return done


def settle_after(
    factory: sessionmaker[Session], owner_type: OwnerType, owner_id: str
) -> None:
    """Background hook run after a worker step; never raises into the caller."""

    try:
        with factory() as session:
            reconcile_owner(session, owner_type, owner_id)
            session.commit()
    except Exception:
        logger.exception(
            "video_credit_reconcile_failed owner_type=%s owner_id=%s",
            owner_type,
            owner_id,
        )


def sweep(factory: sessionmaker[Session], limit: int = 200) -> int:
    """Resolve active video holds whose task has finished (crash/timeout safety)."""

    with factory() as session:
        owners = session.execute(
            select(CreditReservationRecord.owner_type, CreditReservationRecord.owner_id)
            .where(
                CreditReservationRecord.status == ACTIVE,
                CreditReservationRecord.owner_type.is_not(None),
            )
            .order_by(CreditReservationRecord.created_at)
            .limit(limit)
        ).all()
    done = 0
    for owner_type, owner_id in {(row[0], row[1]) for row in owners}:
        if owner_type not in CLASSIFIERS or owner_id is None:
            continue
        try:
            with factory() as session:
                done += reconcile_owner(session, cast(OwnerType, owner_type), owner_id)
                session.commit()
        except Exception:
            logger.exception(
                "video_credit_sweep_failed owner_type=%s owner_id=%s",
                owner_type,
                owner_id,
            )
    return done
