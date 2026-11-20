"""Exhaustive test of authorize() against the permission matrix in docs/09-security-privacy.md.

The expected table below is transcribed from the doc (plus the M2 additions in decisions.md) and
evaluated independently of the implementation, for every role x action x combination of facts.
"""

import itertools
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from seetlu.core.authz import Action, KitFacts, Resource, Subject, authorize
from seetlu.db.models import UserRole


@dataclass(frozen=True)
class Facts:
    same_account: bool
    assigned: bool
    receives_report: bool
    clip_flag: bool
    grant: bool
    own_kit: bool
    kit_activated: bool
    active: bool


Rule = Callable[[Facts], bool]
Y: Rule = lambda f: True  # noqa: E731
N: Rule = lambda f: False  # noqa: E731
OWN: Rule = lambda f: f.same_account  # noqa: E731
ASSIGNED: Rule = lambda f: f.same_account and f.assigned  # noqa: E731
ASSIGNED_RECEIVES: Rule = lambda f: f.same_account and f.assigned and f.receives_report  # noqa: E731
ASSIGNED_CLIP: Rule = lambda f: f.same_account and f.assigned and f.clip_flag  # noqa: E731
INSTALLING: Rule = lambda f: f.own_kit and not f.kit_activated  # noqa: E731
GRANT: Rule = lambda f: f.grant  # noqa: E731

O, M, S, I, SUP = (UserRole.owner, UserRole.manager, UserRole.staff, UserRole.installer, UserRole.support)  # noqa: E741

MATRIX: dict[Action, dict[UserRole, Rule]] = {
    #                         owner  manager            staff     installer   support
    Action.report_view:      {O: OWN, M: ASSIGNED,          S: N,        I: N,          SUP: N},
    Action.report_receive:   {O: OWN, M: ASSIGNED_RECEIVES, S: N,        I: N,          SUP: N},
    Action.counts_view:      {O: OWN, M: ASSIGNED,          S: N,        I: INSTALLING, SUP: Y},
    Action.clip_view:        {O: OWN, M: ASSIGNED_CLIP,     S: N,        I: INSTALLING, SUP: GRANT},
    Action.snapshot_request: {O: OWN, M: ASSIGNED_CLIP,     S: N,        I: INSTALLING, SUP: GRANT},
    Action.sale_quick_log:   {O: OWN, M: ASSIGNED,          S: ASSIGNED, I: N,          SUP: N},
    Action.sale_cash_declaration: {O: OWN, M: ASSIGNED,     S: N,        I: N,          SUP: N},
    Action.zones_edit:       {O: OWN, M: N,                 S: N,        I: INSTALLING, SUP: Y},
    Action.users_manage:     {O: OWN, M: N,                 S: N,        I: N,          SUP: N},
    Action.alerts_manage:    {O: OWN, M: N,                 S: N,        I: N,          SUP: N},
    Action.correction_create: {O: OWN, M: ASSIGNED,         S: N,        I: N,          SUP: Y},
    Action.kit_command:      {O: N,   M: N,                 S: N,        I: INSTALLING, SUP: Y},
    # M2 additions
    Action.shop_view:        {O: OWN, M: ASSIGNED,          S: ASSIGNED, I: INSTALLING, SUP: Y},
    Action.shop_create:      {O: OWN, M: N,                 S: N,        I: Y,          SUP: N},
    Action.shop_settings:    {O: OWN, M: N,                 S: N,        I: INSTALLING, SUP: N},
    Action.audit_view:       {O: OWN, M: N,                 S: N,        I: N,          SUP: Y},
    Action.support_grant_create: {O: OWN, M: N,             S: N,        I: N,          SUP: N},
}  # fmt: skip


def _build(role: UserRole, f: Facts) -> tuple[Subject, Resource]:
    me = uuid.uuid4()
    acc, other_acc, shop = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    seetlu_side = role in (UserRole.installer, UserRole.support)
    subject = Subject(
        user_id=me,
        role=role,
        account_id=None if seetlu_side else (acc if f.same_account else other_acc),
        assigned_shop_ids=frozenset({shop}) if f.assigned else frozenset(),
        receives_report=f.receives_report,
        active=f.active,
    )
    kit = KitFacts(installer_id=me if f.own_kit else uuid.uuid4(), activated=f.kit_activated)
    resource = Resource(
        account_id=acc,
        shop_id=shop,
        clip_access_for_managers=f.clip_flag,
        support_grant_active=f.grant,
        kits=(kit,),
    )
    return subject, resource


ALL_FACTS = [Facts(*bits) for bits in itertools.product([False, True], repeat=8)]


def test_m2_matrix_covers_every_action_and_role() -> None:
    assert set(MATRIX) == set(Action)
    for row in MATRIX.values():
        assert set(row) == set(UserRole)


def test_m2_authorize_exhaustive() -> None:
    checked = 0
    for action, row in MATRIX.items():
        for role, rule in row.items():
            for f in ALL_FACTS:
                subject, resource = _build(role, f)
                expected = f.active and rule(f)
                assert authorize(subject, action, resource) is expected, (action, role, f)
                checked += 1
    assert checked == len(Action) * len(UserRole) * 256


def test_m2_seetlu_side_users_never_match_account_by_accident() -> None:
    """Installer/support have account_id NULL; an account-less resource must not match them as owner."""
    subject = Subject(user_id=uuid.uuid4(), role=UserRole.owner, account_id=None)
    assert not authorize(subject, Action.report_view, Resource(account_id=None))
