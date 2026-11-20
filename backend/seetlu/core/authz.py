"""The one authorization function (docs/09-security-privacy.md, permission matrix).

`authorize(subject, action, resource)` is pure: callers load the facts (assignments, account flags,
support grants, kit state) into `Subject` / `Resource`, and this module decides. Exhaustively
tested in `tests/test_authz.py`.
"""

import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from seetlu.db.models import UserRole


class Action(StrEnum):
    # rows of the matrix in docs/09
    report_view = "report.view"
    report_receive = "report.receive"
    counts_view = "counts.view"
    clip_view = "clip.view"
    snapshot_request = "snapshot.request"
    sale_quick_log = "sale.quick_log"
    sale_cash_declaration = "sale.cash_declaration"
    zones_edit = "zones.edit"
    users_manage = "users.manage"
    alerts_manage = "alerts.manage"
    correction_create = "correction.create"
    kit_command = "kit.command"
    # additions needed by the API (docs/decisions.md, M2)
    shop_view = "shop.view"
    shop_create = "shop.create"
    shop_settings = "shop.settings"
    audit_view = "audit.view"
    support_grant_create = "support_grant.create"


@dataclass(frozen=True)
class Subject:
    user_id: uuid.UUID
    role: UserRole
    account_id: uuid.UUID | None
    assigned_shop_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    receives_report: bool = False
    active: bool = True


@dataclass(frozen=True)
class KitFacts:
    installer_id: uuid.UUID | None
    activated: bool


@dataclass(frozen=True)
class Resource:
    """What is being acted on. `shop_id` None = account-level (e.g. creating a shop, audit log)."""

    account_id: uuid.UUID | None
    shop_id: uuid.UUID | None = None
    clip_access_for_managers: bool = False
    support_grant_active: bool = False  # an unexpired grant for this account covering this support user
    kits: tuple[KitFacts, ...] = ()  # kits attached to the shop (or the one kit acted on)


AUDITED_SUPPORT_ACTIONS = frozenset({Action.zones_edit, Action.correction_create})


def _own_account(s: Subject, r: Resource) -> bool:
    return s.account_id is not None and s.account_id == r.account_id


def _assigned(s: Subject, r: Resource) -> bool:
    return _own_account(s, r) and r.shop_id is not None and r.shop_id in s.assigned_shop_ids


def _installing(s: Subject, r: Resource) -> bool:
    """Installer of a kit at this shop that is not yet activated."""
    return any(k.installer_id == s.user_id and not k.activated for k in r.kits)


def authorize(s: Subject, action: Action, r: Resource) -> bool:
    if not s.active:
        return False
    role = s.role

    if role is UserRole.owner:
        if not _own_account(s, r):
            return False
        return action is not Action.kit_command

    if role is UserRole.manager:
        if not _assigned(s, r):
            return False
        match action:
            case Action.report_view | Action.counts_view | Action.shop_view:
                return True
            case Action.report_receive:
                return s.receives_report
            case Action.clip_view | Action.snapshot_request:
                return r.clip_access_for_managers
            case Action.sale_quick_log | Action.sale_cash_declaration | Action.correction_create:
                return True
            case _:
                return False

    if role is UserRole.staff:
        if not _assigned(s, r):
            return False
        return action in (Action.sale_quick_log, Action.shop_view)

    if role is UserRole.installer:
        match action:
            case Action.shop_create:
                return True
            case (
                Action.counts_view
                | Action.zones_edit
                | Action.kit_command
                | Action.shop_view
                | Action.shop_settings
                | Action.clip_view
                | Action.snapshot_request
            ):
                # calibration snapshots/clips, zones, count check, commands: own kits until activation
                return _installing(s, r)
            case _:
                return False

    if role is UserRole.support:
        match action:
            case (
                Action.counts_view
                | Action.zones_edit
                | Action.correction_create
                | Action.kit_command
                | Action.shop_view
                | Action.audit_view
            ):
                return True
            case Action.clip_view | Action.snapshot_request:
                return r.support_grant_active
            case _:
                # report.view: aggregated only (no per-shop report access)
                return False

    return False
