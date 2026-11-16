"""Private invitation reporting for verified personal accounts."""

from datetime import datetime
from hashlib import sha256

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from . import growth_rewards as rewards
from .admin_commerce_models import ManualRefundRecord
from .credit_memberships import aware
from .errors import ApiError
from .models import (
    CreditPurchaseRecord,
    InvitationRecord,
    ReferralRewardRecord,
    UserRecord,
)
from .onboarding import personal_workspace_id


def personal_user(
    session: Session, user_id: str, workspace_id: str, *, lock: bool = False
) -> UserRecord:
    if lock and session.get_bind().dialect.name == "sqlite":
        session.execute(
            update(UserRecord)
            .where(UserRecord.id == user_id)
            .values(status=UserRecord.status)
        )
    user = session.get(
        UserRecord, user_id, with_for_update=lock, populate_existing=lock
    )
    if (
        not rewards.eligible(user)
        or not user
        or workspace_id != personal_workspace_id(user_id)
    ):
        raise ApiError(403, "PERSONAL_REWARDS_REQUIRED", "请使用已验证邮箱的个人账户。")
    return user


def invitation_center(
    session: Session, user: UserRecord, offset: int, limit: int, status: str
) -> dict:
    if not rewards.active(session, rewards.REFERRAL):
        raise ApiError(403, "INVITATIONS_UNAVAILABLE", "邀请活动暂未开放。")
    overview = rewards.state(session, user, personal_workspace_id(user.id))
    refunded = (
        select(
            ManualRefundRecord.purchase_id.label("order_id"),
            func.sum(ManualRefundRecord.amount_fen).label("amount_fen"),
        )
        .where(ManualRefundRecord.status == "completed")
        .group_by(ManualRefundRecord.purchase_id)
        .subquery()
    )
    purchases = (
        select(
            CreditPurchaseRecord.created_by_user_id.label("buyer"),
            func.max(CreditPurchaseRecord.paid_at).label("paid_at"),
            func.sum(
                case(
                    (
                        func.coalesce(refunded.c.amount_fen, 0)
                        < CreditPurchaseRecord.amount_fen,
                        1,
                    ),
                    else_=0,
                )
            ).label("active_count"),
            func.count().label("paid_count"),
        )
        .join(
            InvitationRecord,
            InvitationRecord.invitee_user_id == CreditPurchaseRecord.created_by_user_id,
        )
        .outerjoin(refunded, refunded.c.order_id == CreditPurchaseRecord.id)
        .where(
            CreditPurchaseRecord.workspace_id
            == CreditPurchaseRecord.product_snapshot[
                "referral_workspace_id"
            ].as_string(),
            InvitationRecord.inviter_user_id == user.id,
            CreditPurchaseRecord.status == "paid",
        )
        .group_by(CreditPurchaseRecord.created_by_user_id)
        .subquery()
    )
    totals = (
        select(
            ReferralRewardRecord.invitee_user_id.label("invitee"),
            func.sum(ReferralRewardRecord.amount - ReferralRewardRecord.revoked).label(
                "credits"
            ),
        )
        .where(ReferralRewardRecord.inviter_user_id == user.id)
        .group_by(ReferralRewardRecord.invitee_user_id)
        .subquery()
    )
    paid_status = case(
        (purchases.c.active_count > 0, "paid"),
        (purchases.c.paid_count > 0, "refunded"),
        else_="unpaid",
    )
    statement = (
        select(
            UserRecord,
            InvitationRecord,
            paid_status.label("payment_status"),
            purchases.c.paid_at,
            func.coalesce(totals.c.credits, 0),
        )
        .join(InvitationRecord, InvitationRecord.invitee_user_id == UserRecord.id)
        .outerjoin(purchases, purchases.c.buyer == UserRecord.id)
        .outerjoin(totals, totals.c.invitee == UserRecord.id)
        .where(InvitationRecord.inviter_user_id == user.id)
    )
    counts: dict[str, int] = dict(
        session.execute(
            select(paid_status, func.count())
            .select_from(InvitationRecord)
            .outerjoin(purchases, purchases.c.buyer == InvitationRecord.invitee_user_id)
            .where(InvitationRecord.inviter_user_id == user.id)
            .group_by(paid_status)
        ).all()
    )
    if status != "all":
        statement = statement.where(paid_status == status)
    records = []
    for friend, _invitation, payment_status, paid_at, credits in session.execute(
        statement.order_by(
            InvitationRecord.created_at.desc(), InvitationRecord.invitee_user_id.desc()
        )
        .offset(offset)
        .limit(limit)
    ):
        assert isinstance(friend, UserRecord)
        assert paid_at is None or isinstance(paid_at, datetime)
        local, _, _domain = (friend.email_normalized or "").partition("@")
        records.append(
            {
                "id": sha256(friend.id.encode()).hexdigest()[:16],
                "friend": local[:1] + "****" if local else "受邀好友",
                "registered_at": aware(friend.created_at).isoformat(),
                "payment_status": payment_status,
                "last_paid_at": aware(paid_at).isoformat() if paid_at else None,
                "earned_credits": credits,
            }
        )
    url = overview["invite_url"]
    return {
        "invite_code": url.split("=")[-1] if url else "",
        "invite_url": url or "",
        "invited_count": overview["invited_count"],
        "paid_count": counts.get("paid", 0),
        "unpaid_count": counts.get("unpaid", 0),
        "refunded_count": counts.get("refunded", 0),
        "earned_credits": overview["earned_credits"],
        "reward_percent": overview["reward_percent"],
        "validity_days": overview["validity_days"],
        "total": sum(counts.values()) if status == "all" else counts.get(status, 0),
        "offset": offset,
        "limit": limit,
        "items": records,
    }
