"""One-time rewards and the server-owned first order offer."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import growth_rewards
from .credit_memberships import aware, grant, refresh
from .credit_products import Product
from .errors import ApiError
from .models import (
    AssetRecord,
    CreditGrantRecord,
    CreditLedgerEntryRecord,
    CreditPurchaseRecord,
    JobAssetRecord,
    JobRecord,
    NewcomerOfferRecord,
    PromotionCampaignRecord,
    SignupBonusClaim,
    UserRecord,
    WorkspaceCreditAccountRecord,
    utc_now,
)
from .onboarding import personal_workspace_id

WELCOME = "welcome-credits-v1"
NEWCOMER = "newcomer-pack-v1"
WELCOME_CREDITS = 50
VALIDITY_DAYS = 30
OFFER_DURATION = timedelta(hours=24)
REMINDER_DELAY = timedelta(seconds=30)
PRODUCT = Product("newcomer_pack", "新人首单体验包", 990, 180, "pack")


def register_growth(
    session: Session, user: UserRecord, joined_at: datetime | None, invite_code: str
) -> None:
    if joined_at is None or not growth_rewards.eligible(user):
        return
    campaign = session.get(PromotionCampaignRecord, growth_rewards.REFERRAL)
    if campaign and aware(joined_at) >= aware(campaign.starts_at):
        growth_rewards.bind_signup_invitation(session, user, invite_code)
    campaign = session.get(PromotionCampaignRecord, WELCOME)
    if (
        not campaign
        or not growth_rewards.active(session, WELCOME)
        or aware(joined_at) < aware(campaign.starts_at)
    ):
        return
    key = growth_rewards.email_key(user)
    if session.get(SignupBonusClaim, key):
        return
    try:
        with session.begin_nested():
            session.add(SignupBonusClaim(email_key=key, user_id=user.id))
            session.flush()
    except IntegrityError:
        if session.get(SignupBonusClaim, key) is None:
            raise
        return
    grant(
        session,
        refresh(session, personal_workspace_id(user.id)),
        "signup-welcome",
        WELCOME_CREDITS,
        aware(utc_now()) + timedelta(days=VALIDITY_DAYS),
        "新用户注册赠送 50 积分",
        kind="signup_bonus",
    )


def signup_lot(session: Session, workspace_id: str) -> CreditGrantRecord | None:
    return session.scalar(
        select(CreditGrantRecord).where(
            CreditGrantRecord.workspace_id == workspace_id,
            CreditGrantRecord.kind == "signup_bonus",
        )
    )


def support_lot(session: Session, workspace_id: str) -> CreditGrantRecord | None:
    return session.scalar(
        select(CreditGrantRecord).where(
            CreditGrantRecord.workspace_id == workspace_id,
            CreditGrantRecord.source_key == "support-welcome",
        )
    )


def grant_support_bonus(
    session: Session, workspace_id: str
) -> tuple[CreditGrantRecord, bool]:
    account = refresh(session, workspace_id)
    if signup_lot(session, workspace_id) is None:
        raise ApiError(403, "SUPPORT_BONUS_INELIGIBLE", "此账号未参加新人赠分活动。")
    existing = support_lot(session, workspace_id)
    if existing:
        return existing, False
    return grant(
        session,
        account,
        "support-welcome",
        WELCOME_CREDITS,
        aware(utc_now()) + timedelta(days=VALIDITY_DAYS),
        "添加客服赠送 50 积分",
        kind="support_bonus",
    ), True


def unpaid_signup(
    session: Session, user_id: str, workspace_id: str
) -> CreditGrantRecord | None:
    if workspace_id != personal_workspace_id(user_id) or not growth_rewards.active(
        session, NEWCOMER
    ):
        return None
    lot = signup_lot(session, workspace_id)
    if lot is None:
        return None
    paid = session.scalar(
        select(CreditPurchaseRecord.id)
        .where(
            CreditPurchaseRecord.created_by_user_id == user_id,
            CreditPurchaseRecord.status == "paid",
        )
        .limit(1)
    )
    return None if paid else lot


def eligibility(
    session: Session, user_id: str, workspace_id: str, now: datetime
) -> datetime | None:
    if unpaid_signup(session, user_id, workspace_id) is None:
        return None
    offer = session.get(NewcomerOfferRecord, user_id)
    if offer is None:
        return None
    deadline = aware(offer.first_viewed_at) + OFFER_DURATION
    return deadline if now < deadline else None


def depletion_result_assets(session: Session, signup: CreditGrantRecord) -> list[str]:
    account = session.get(WorkspaceCreditAccountRecord, signup.workspace_id)
    if account is None or account.balance_credits != 0:
        return []
    depleted_job = session.scalar(
        select(CreditLedgerEntryRecord.job_id)
        .where(
            CreditLedgerEntryRecord.workspace_id == signup.workspace_id,
            CreditLedgerEntryRecord.created_at >= signup.created_at,
            CreditLedgerEntryRecord.entry_type == "settle",
            CreditLedgerEntryRecord.delta_balance_credits < 0,
            CreditLedgerEntryRecord.balance_after_credits == 0,
            CreditLedgerEntryRecord.job_id.is_not(None),
        )
        .order_by(CreditLedgerEntryRecord.id.desc())
        .limit(1)
    )
    if not depleted_job:
        return []
    return list(
        session.scalars(
            select(JobAssetRecord.asset_id)
            .join(AssetRecord, AssetRecord.id == JobAssetRecord.asset_id)
            .join(JobRecord, JobRecord.id == JobAssetRecord.job_id)
            .where(
                JobAssetRecord.workspace_id == signup.workspace_id,
                JobAssetRecord.job_id == depleted_job,
                JobAssetRecord.direction == "output",
                JobAssetRecord.is_deliverable.is_(True),
                JobRecord.status.in_(["completed", "partial", "cancelled"]),
                AssetRecord.lifecycle_status == "ready",
                AssetRecord.origin_kind == "generated",
                AssetRecord.media_kind == "image",
            )
            .distinct()
        )
    )


def pending_order(
    session: Session, user_id: str, workspace_id: str
) -> CreditPurchaseRecord | None:
    return session.scalar(
        select(CreditPurchaseRecord)
        .where(
            CreditPurchaseRecord.created_by_user_id == user_id,
            CreditPurchaseRecord.workspace_id == workspace_id,
            CreditPurchaseRecord.package_id == PRODUCT.id,
            CreditPurchaseRecord.status == "pending",
        )
        .limit(1)
    )


def offer_state(
    session: Session,
    user_id: str,
    workspace_id: str,
    *,
    enabled: bool,
    claim: bool = False,
    viewed_asset_id: str | None = None,
) -> dict:
    now = aware(utc_now())
    signup = unpaid_signup(session, user_id, workspace_id) if enabled else None
    offer = session.get(NewcomerOfferRecord, user_id) if signup else None
    candidates = (
        depletion_result_assets(session, signup) if signup and not offer else []
    )
    if viewed_asset_id in candidates:
        offer = NewcomerOfferRecord(user_id=user_id, first_viewed_at=now)
        session.add(offer)
        candidates = []
    deadline = aware(offer.first_viewed_at) + OFFER_DURATION if offer else None
    eligible = bool(deadline and now < deadline)
    ready_at = aware(offer.first_viewed_at) + REMINDER_DELAY if offer else None
    shown = bool(offer and offer.shown_at)
    should_show = bool(eligible and ready_at and now >= ready_at and not shown)
    if claim and should_show and offer:
        offer.shown_at = now
    return {
        "eligible": eligible,
        "reminded": shown,
        "should_show": should_show,
        "waiting_for_result": bool(signup and not offer),
        "result_asset_ids": candidates,
        "server_now": now.isoformat(),
        "ready_at": ready_at.isoformat() if ready_at else None,
        "window_ends_at": deadline.isoformat() if deadline else None,
        "amount_fen": PRODUCT.amount_fen,
        "credits": PRODUCT.credits,
        "validity_days": VALIDITY_DAYS,
    }
