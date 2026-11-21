"""Operator commands for a fresh production database (ops/runbooks/deploy.md). Everything else is done in
the apps: owners create their shops and users, installers claim kits.

    python -m seetlu.admin create-owner --account "Boutique Awa" --name "Awa Ndiaye" --phone +221770000001
    python -m seetlu.admin create-staff --role installer --name "Moussa" --phone +221770000004
    python -m seetlu.admin register-kit --serial SN-0042      # prints the one-time claim token

Each command writes an audit row (rule 5) with no actor: the operator is identified by the server login.
"""

import argparse
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from seetlu.api.auth import normalize_phone
from seetlu.core.audit import audit
from seetlu.core.security import hash_token, new_device_token
from seetlu.db import models as m
from seetlu.db.session import session_factory


class AdminError(Exception):
    pass


def _phone(value: str) -> str:
    try:
        return normalize_phone(value)
    except ValueError as exc:
        raise AdminError(str(exc)) from exc


def _new_user(s: Session, phone: str, **fields: object) -> m.User:
    if s.scalars(select(m.User).where(m.User.phone_e164 == phone)).first():
        raise AdminError(f"a user with phone {phone} already exists")
    user = m.User(phone_e164=phone, **fields)
    s.add(user)
    s.flush()
    return user


def create_owner(s: Session, account: str, name: str, phone: str) -> m.User:
    acc = m.Account(name=account)
    s.add(acc)
    s.flush()
    user = _new_user(
        s, _phone(phone), name=name, role=m.UserRole.owner, account_id=acc.id, receives_report=True
    )
    audit(s, None, "admin.create_owner", account_id=acc.id, target_type="user", target_id=user.id)
    return user


def create_staff(s: Session, role: str, name: str, phone: str) -> m.User:
    """Seetlu-side people: installers and support agents (no account)."""
    if role not in ("installer", "support"):
        raise AdminError("role must be installer or support")
    user = _new_user(s, _phone(phone), name=name, role=m.UserRole(role))
    detail = {"role": role}
    audit(
        s, None, "admin.create_staff", account_id=None, target_type="user", target_id=user.id, detail=detail
    )
    return user


@dataclass(frozen=True)
class KitRegistration:
    kit_id: uuid.UUID
    serial: str
    claim_token: str

    @property
    def qr_payload(self) -> str:  # what the installer app scans (docs/08)
        return f"seetlu:{self.serial}:{self.claim_token}"


def register_kit(s: Session, serial: str) -> KitRegistration:
    if not serial or len(serial) > 64 or not all(c.isalnum() or c == "-" for c in serial):
        raise AdminError("serial: letters, digits and '-' only (it becomes the box hostname)")
    if s.scalars(select(m.Kit).where(m.Kit.serial == serial)).first():
        raise AdminError(f"kit {serial} already registered")
    token = new_device_token()
    kit = m.Kit(serial=serial, claim_token_hash=hash_token(token))
    s.add(kit)
    s.flush()
    audit(s, None, "admin.register_kit", account_id=None, target_type="kit", target_id=kit.id)
    return KitRegistration(kit.id, serial, token)


def main(argv: Sequence[str] | None = None, session: Session | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m seetlu.admin", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("create-owner")
    o.add_argument("--account", required=True)
    o.add_argument("--name", required=True)
    o.add_argument("--phone", required=True)
    st = sub.add_parser("create-staff")
    st.add_argument("--role", required=True, choices=["installer", "support"])
    st.add_argument("--name", required=True)
    st.add_argument("--phone", required=True)
    k = sub.add_parser("register-kit")
    k.add_argument("--serial", required=True)
    args = p.parse_args(argv)

    s = session or session_factory()()
    try:
        if args.cmd == "create-owner":
            u = create_owner(s, args.account, args.name, args.phone)
            out = f"owner {u.phone_e164} created (account {u.account_id}); they sign in with a one-time code"
        elif args.cmd == "create-staff":
            u = create_staff(s, args.role, args.name, args.phone)
            out = f"{args.role} {u.phone_e164} created"
        else:
            reg = register_kit(s, args.serial)
            out = "\n".join(
                [
                    f"kit {reg.serial} registered ({reg.kit_id})",
                    f"claim token (shown once): {reg.claim_token}",
                    f"QR payload: {reg.qr_payload}",
                ]
            )
        s.commit()
    except AdminError as exc:
        s.rollback()
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if session is None:
            s.close()
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
