"""Demo data (docs/10-testing.md "Seed data"). Idempotent: rows are looked up by natural keys
(phone, serial, shop name) and created only when missing.

M1 seeds the skeleton: account, the 5 role users, 2 shops, 2 kits with cameras and zones, alert
rules. The 30 days of simulated events and sales are added once the report engine exists (M6).
"""

import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from seetlu.core.security import hash_token
from seetlu.db import models as m

WEEK = ("mon", "tue", "wed", "thu", "fri", "sat")
DEMO_ACCOUNT = "Démo Seetlu"

USERS: list[dict[str, Any]] = [
    {
        "name": "Awa Diop (propriétaire)",
        "phone_e164": "+221770000001",
        "role": m.UserRole.owner,
        "receives_report": True,
        "account": True,
    },
    {
        "name": "Moussa Ndiaye (gérant)",
        "phone_e164": "+221770000002",
        "role": m.UserRole.manager,
        "receives_report": False,
        "account": True,
    },
    {
        "name": "Fatou Sarr (vendeuse)",
        "phone_e164": "+221770000003",
        "role": m.UserRole.staff,
        "receives_report": False,
        "account": True,
    },
    {
        "name": "Ibrahima Fall (installateur)",
        "phone_e164": "+221770000004",
        "role": m.UserRole.installer,
        "receives_report": False,
        "account": False,
    },
    {
        "name": "Support Seetlu",
        "phone_e164": "+221770000005",
        "role": m.UserRole.support,
        "receives_report": False,
        "account": False,
    },
]

SHOPS: list[dict[str, Any]] = [
    {
        "name": "Boutique Awa — Médina",
        "category": "boutique",
        "address": "Rue 11, Médina, Dakar",
        "timezone": "Africa/Dakar",
        "gps": ("14.683300", "-17.446700"),
        "kit": "DEV-KIT-0001",
        "hours": {d: [["08:00", "21:00"]] for d in WEEK} | {"sun": [["09:00", "14:00"]]},
        "cdp": "CDP-DEMO-0001",
        "expected_staff": 1,
    },
    {
        "name": "Supérette Plateau — Abidjan",
        "category": "superette",
        "address": "Bd de la République, Plateau",
        "timezone": "Africa/Abidjan",
        "gps": ("5.323000", "-4.019000"),
        "kit": "DEV-KIT-0002",
        "hours": {d: [["07:30", "22:00"]] for d in (*WEEK, "sun")},
        "cdp": "CDP-DEMO-0002",
        "expected_staff": 2,
    },
]

# Normalised (0..1) geometries on a 640x360 detect frame.
DOOR_LINE = {"points": [[0.30, 0.55], [0.70, 0.55]]}
CUSTOMER_SIDE = {"polygon": [[0.10, 0.55], [0.90, 0.55], [0.90, 0.95], [0.10, 0.95]]}
STAFF_SIDE = {"polygon": [[0.10, 0.10], [0.90, 0.10], [0.90, 0.45], [0.10, 0.45]]}


@dataclass
class SeedResult:
    account_id: str
    shop_ids: list[str]
    kit_serials: list[str]


def _get_or_create[T: m.Base](s: Session, model: type[T], where: dict[str, Any], **values: Any) -> T:
    row = s.scalars(select(model).filter_by(**where)).first()
    if row is None:
        row = model(**where, **values)
        s.add(row)
        s.flush()
    return row


def seed_demo(s: Session, claim_token: str | None = None) -> SeedResult:
    claim_token = claim_token or os.environ.get("KIT_CLAIM_TOKEN", "dev-claim-token")
    account = _get_or_create(s, m.Account, {"name": DEMO_ACCOUNT})

    users: dict[m.UserRole, m.User] = {}
    for u in USERS:
        users[u["role"]] = _get_or_create(
            s,
            m.User,
            {"phone_e164": u["phone_e164"]},
            name=u["name"],
            role=u["role"],
            receives_report=u["receives_report"],
            account_id=account.id if u["account"] else None,
        )

    shop_ids: list[str] = []
    for spec in SHOPS:
        shop = _get_or_create(
            s,
            m.Shop,
            {"account_id": account.id, "name": spec["name"]},
            category=spec["category"],
            address=spec["address"],
            timezone=spec["timezone"],
            gps_lat=spec["gps"][0],
            gps_lng=spec["gps"][1],
            opening_hours=spec["hours"],
            cdp_declaration_ref=spec["cdp"],
            expected_staff=spec["expected_staff"],
            status=m.ShopStatus.active,
        )
        shop_ids.append(str(shop.id))
        for role in (m.UserRole.manager, m.UserRole.staff):
            _get_or_create(s, m.UserShop, {"user_id": users[role].id, "shop_id": shop.id})
        for alert in m.AlertType:
            _get_or_create(s, m.AlertRule, {"shop_id": shop.id, "type": alert})

        kit = s.scalars(select(m.Kit).filter_by(serial=spec["kit"])).first()
        if kit is None:
            kit = m.Kit(
                serial=spec["kit"],
                claim_token_hash=hash_token(claim_token),
                shop_id=shop.id,
                installer_id=users[m.UserRole.installer].id,
                status=m.KitStatus.active,
            )
            s.add(kit)
            s.flush()
        door = _get_or_create(
            s,
            m.Camera,
            {"kit_id": kit.id, "name": "door"},
            role=m.CameraRole.door,
            rtsp_main_path="/stream1",
            rtsp_sub_path="/stream2",
        )
        counter = _get_or_create(
            s,
            m.Camera,
            {"kit_id": kit.id, "name": "counter"},
            role=m.CameraRole.counter,
            rtsp_main_path="/stream1",
            rtsp_sub_path="/stream2",
        )
        _get_or_create(
            s,
            m.Zone,
            {"camera_id": door.id, "type": m.ZoneType.door_line},
            geometry=DOOR_LINE,
            inward_side="right",
        )
        _get_or_create(
            s, m.Zone, {"camera_id": counter.id, "type": m.ZoneType.customer_side}, geometry=CUSTOMER_SIDE
        )
        _get_or_create(
            s, m.Zone, {"camera_id": counter.id, "type": m.ZoneType.staff_side}, geometry=STAFF_SIDE
        )

    s.commit()
    return SeedResult(str(account.id), shop_ids, [spec["kit"] for spec in SHOPS])
