"""Request dependencies: DB session, current user, and loading authorization facts."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from seetlu.core.authz import Action, KitFacts, Resource, Subject, authorize
from seetlu.core.problem import Problem
from seetlu.core.tokens import decode_token
from seetlu.db import models as m
from seetlu.db.session import session_factory


def get_db() -> Iterator[Session]:
    with session_factory()() as s:
        yield s


DB = Annotated[Session, Depends(get_db)]


def current_user(request: Request, s: DB) -> m.User:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Problem(401, "unauthorized", "Missing bearer token")
    claims = decode_token(token, "access")
    if claims is None:
        raise Problem(401, "invalid-token", "Token is invalid or expired")
    user = s.get(m.User, claims.user_id)
    if user is None or not user.active:
        raise Problem(401, "invalid-token", "User is not active")
    return user


CurrentUser = Annotated[m.User, Depends(current_user)]


def subject_for(s: Session, user: m.User) -> Subject:
    assigned = frozenset(s.scalars(select(m.UserShop.shop_id).where(m.UserShop.user_id == user.id)))
    return Subject(
        user_id=user.id,
        role=user.role,
        account_id=user.account_id,
        assigned_shop_ids=assigned,
        receives_report=user.receives_report,
        active=user.active,
    )


def _grant_active(s: Session, account_id: uuid.UUID, user: m.User) -> bool:
    if user.role is not m.UserRole.support:
        return False
    now = datetime.now(UTC)
    q = select(m.SupportGrant.id).where(
        m.SupportGrant.account_id == account_id,
        m.SupportGrant.expires_at > now,
        or_(m.SupportGrant.granted_to.is_(None), m.SupportGrant.granted_to == user.id),
    )
    return s.scalars(q).first() is not None


def shop_resource(s: Session, shop: m.Shop, user: m.User) -> Resource:
    account = s.get(m.Account, shop.account_id)
    kits = s.scalars(select(m.Kit).where(m.Kit.shop_id == shop.id)).all()
    return Resource(
        account_id=shop.account_id,
        shop_id=shop.id,
        clip_access_for_managers=bool(account and account.clip_access_for_managers),
        support_grant_active=_grant_active(s, shop.account_id, user),
        kits=tuple(
            KitFacts(installer_id=k.installer_id, activated=k.status is m.KitStatus.active) for k in kits
        ),
    )


def require(s: Session, user: m.User, action: Action, resource: Resource) -> Subject:
    subject = subject_for(s, user)
    if not authorize(subject, action, resource):
        raise Problem(403, "forbidden", f"Not allowed: {action.value}")
    return subject


def load_shop(s: Session, shop_id: uuid.UUID, user: m.User, action: Action) -> m.Shop:
    """404 when the shop is invisible to the user, 403 when visible but the action is not allowed."""
    shop = s.get(m.Shop, shop_id)
    if shop is None:
        raise Problem(404, "not-found", "Shop not found")
    resource = shop_resource(s, shop, user)
    subject = subject_for(s, user)
    if not authorize(subject, Action.shop_view, resource):
        raise Problem(404, "not-found", "Shop not found")
    if not authorize(subject, action, resource):
        raise Problem(403, "forbidden", f"Not allowed: {action.value}")
    return shop
