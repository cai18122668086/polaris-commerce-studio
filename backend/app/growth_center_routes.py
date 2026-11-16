from typing import Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from . import growth_center as center
from . import welcome_credits
from .auth import SessionDependency, WorkspaceDependency, WorkspaceWriteDependency
from .services import credit_enforcement_enabled

router = APIRouter(tags=["growth center"])


class InvitationFriend(BaseModel):
    id: str
    friend: str
    registered_at: str
    payment_status: Literal["unpaid", "paid", "refunded"]
    last_paid_at: str | None
    earned_credits: int


class InvitationCenter(BaseModel):
    invite_code: str
    invite_url: str
    invited_count: int
    paid_count: int
    unpaid_count: int
    refunded_count: int
    earned_credits: int
    reward_percent: int
    validity_days: int
    total: int
    offset: int
    limit: int
    items: list[InvitationFriend]


class NewcomerOffer(BaseModel):
    eligible: bool
    reminded: bool
    should_show: bool
    waiting_for_result: bool
    result_asset_ids: list[str]
    server_now: str
    ready_at: str | None
    window_ends_at: str | None
    amount_fen: int
    credits: int
    validity_days: int


@router.get(
    "/api/v1/workspaces/{workspace_id}/invitations", response_model=InvitationCenter
)
def invitations(
    workspace: WorkspaceDependency,
    session: SessionDependency,
    response: Response,
    status: Literal["all", "unpaid", "paid", "refunded"] = "all",
    offset: int = Query(0, ge=0, le=1000000),
    limit: int = Query(20, ge=1, le=100),
) -> InvitationCenter:
    response.headers["Cache-Control"] = "no-store"
    user = center.personal_user(
        session, workspace.principal.user_id, workspace.workspace_id
    )
    result = center.invitation_center(session, user, offset, limit, status)
    session.commit()
    return InvitationCenter.model_validate(result)


@router.get(
    "/api/v1/workspaces/{workspace_id}/promotions/newcomer-offer",
    response_model=NewcomerOffer,
)
def newcomer_offer(
    workspace: WorkspaceDependency, session: SessionDependency, response: Response
) -> NewcomerOffer:
    response.headers["Cache-Control"] = "no-store"
    result = welcome_credits.offer_state(
        session,
        workspace.principal.user_id,
        workspace.workspace_id,
        enabled=credit_enforcement_enabled(workspace.workspace_id),
    )
    return NewcomerOffer.model_validate(result)


@router.post(
    "/api/v1/workspaces/{workspace_id}/promotions/newcomer-offer/impression",
    response_model=NewcomerOffer,
)
def impression(
    workspace: WorkspaceWriteDependency, session: SessionDependency, response: Response
) -> NewcomerOffer:
    response.headers["Cache-Control"] = "no-store"
    user = center.personal_user(
        session, workspace.principal.user_id, workspace.workspace_id, lock=True
    )
    result = welcome_credits.offer_state(
        session,
        user.id,
        workspace.workspace_id,
        enabled=credit_enforcement_enabled(workspace.workspace_id),
        claim=True,
    )
    session.commit()
    return NewcomerOffer.model_validate(result)


class NewcomerResultView(BaseModel):
    asset_id: str = Field(min_length=1, max_length=40)


@router.post(
    "/api/v1/workspaces/{workspace_id}/promotions/newcomer-offer/viewed",
    response_model=NewcomerOffer,
)
def newcomer_result_viewed(
    payload: NewcomerResultView,
    workspace: WorkspaceWriteDependency,
    session: SessionDependency,
    response: Response,
) -> NewcomerOffer:
    response.headers["Cache-Control"] = "no-store"
    user = center.personal_user(
        session, workspace.principal.user_id, workspace.workspace_id, lock=True
    )
    result = welcome_credits.offer_state(
        session,
        user.id,
        workspace.workspace_id,
        enabled=credit_enforcement_enabled(workspace.workspace_id),
        viewed_asset_id=payload.asset_id,
    )
    session.commit()
    return NewcomerOffer.model_validate(result)
