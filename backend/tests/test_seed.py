from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from seetlu.core.security import verify_token
from seetlu.db import models as m
from seetlu.seed.demo import seed_demo


def _counts(s: Session) -> dict[str, int]:
    return {
        t.__tablename__: s.scalar(select(func.count()).select_from(t)) or 0
        for t in (m.Account, m.User, m.Shop, m.Kit, m.Camera, m.Zone, m.AlertRule, m.UserShop)
    }


def test_m1_seed_skeleton_is_idempotent(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as s:
        first = seed_demo(s, claim_token="tok")
        before = _counts(s)
        second = seed_demo(s, claim_token="tok")
        assert _counts(s) == before
        assert first == second

        assert {u.role for u in s.scalars(select(m.User))} >= set(m.UserRole)
        shops = s.scalars(select(m.Shop).where(m.Shop.account_id == first.account_id)).all()
        assert {sh.timezone for sh in shops} == {"Africa/Dakar", "Africa/Abidjan"}
        assert all(sh.cdp_declaration_ref for sh in shops)  # AC-F8-4 precondition for active shops
        kit = s.scalars(select(m.Kit).filter_by(serial="DEV-KIT-0001")).one()
        assert verify_token(kit.claim_token_hash, "tok")
        assert not verify_token(kit.claim_token_hash, "wrong")
