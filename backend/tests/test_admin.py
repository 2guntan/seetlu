"""Operator commands for a fresh production database (ops/runbooks/deploy.md)."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from seetlu import admin
from seetlu.core.security import verify_token
from seetlu.db import models as m
from tests.conftest import new_phone


def test_create_owner_makes_an_account_and_an_audited_owner(
    db: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    phone = new_phone()
    assert (
        admin.main(["create-owner", "--account", "Boutique Awa", "--name", "Awa", "--phone", phone], db) == 0
    )
    user = db.scalars(select(m.User).where(m.User.phone_e164 == phone)).one()
    assert user.role is m.UserRole.owner and user.receives_report and user.account_id
    assert (
        db.scalars(select(m.AuditLog).where(m.AuditLog.action == "admin.create_owner")).one().target_id
        == user.id
    )
    assert "created" in capsys.readouterr().out


def test_duplicate_phone_is_refused(db: Session) -> None:
    phone = new_phone()
    assert admin.main(["create-staff", "--role", "installer", "--name", "M", "--phone", phone], db) == 0
    assert admin.main(["create-staff", "--role", "support", "--name", "M", "--phone", phone], db) == 1


def test_register_kit_prints_a_claim_token_that_claims_it(
    db: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    assert admin.main(["register-kit", "--serial", "SN-0042"], db) == 0
    out = capsys.readouterr().out
    token = out.split("claim token (shown once): ")[1].split("\n")[0]
    assert f"QR payload: seetlu:SN-0042:{token}" in out
    kit = db.scalars(select(m.Kit).where(m.Kit.serial == "SN-0042")).one()
    assert kit.shop_id is None and verify_token(kit.claim_token_hash, token)
    assert admin.main(["register-kit", "--serial", "SN-0042"], db) == 1
    assert admin.main(["register-kit", "--serial", "bad serial"], db) == 1
