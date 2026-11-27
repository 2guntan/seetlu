"""Installer flow (docs/08, docs/13, AC-F8-1..8): claim a kit, check the recorder streams and camera angles,
set cameras and zones, count check, activate."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Path
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, func, select

from seetlu.api.deps import DB, CurrentUser, load_shop, require, shop_resource
from seetlu.core.audit import audit
from seetlu.core.authz import Action
from seetlu.core.problem import Problem
from seetlu.core.security import verify_token
from seetlu.db import models as m
from seetlu.domain import commands, setup_checks

router = APIRouter(prefix="/v1", tags=["installer"])

COUNT_CHECK_MIN_ENTRIES = 20  # AC-F8-3
COUNT_CHECK_MAX_ERROR_PCT = Decimal("10")


class KitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    serial: str
    shop_id: uuid.UUID | None
    status: m.KitStatus
    health: m.KitHealth
    agent_version: str | None
    config_version: int
    last_seen_at: datetime | None


class ClaimIn(BaseModel):
    serial: str = Field(min_length=1, max_length=64)
    claim_token: str = Field(min_length=1, max_length=200)
    shop_id: uuid.UUID


@router.post("/kits/claim")
def claim(body: ClaimIn, user: CurrentUser, s: DB) -> KitOut:
    """AC-F8-1: the QR code carries the serial and claim token; the kit is attached to the shop."""
    if user.role is not m.UserRole.installer:
        raise Problem(403, "forbidden", "Only installers claim kits")
    kit = s.scalars(select(m.Kit).where(m.Kit.serial == body.serial)).first()
    if kit is None or not verify_token(kit.claim_token_hash, body.claim_token):
        raise Problem(404, "not-found", "Unknown kit or wrong claim code")
    if kit.status is m.KitStatus.active or (kit.shop_id is not None and kit.shop_id != body.shop_id):
        raise Problem(409, "kit-taken", "This kit is already attached to another shop")
    shop = s.get(m.Shop, body.shop_id)
    if shop is None:
        raise Problem(404, "not-found", "Shop not found")
    kit.shop_id, kit.installer_id, kit.status = shop.id, user.id, m.KitStatus.installing
    s.flush()
    require(
        s, user, Action.zones_edit, shop_resource(s, shop, user)
    )  # the installer of a kit being installed
    audit(s, user, "kit.claim", account_id=shop.account_id, target_type="kit", target_id=kit.id)
    s.commit()
    return KitOut.model_validate(kit)


class ZoneIn(BaseModel):
    type: m.ZoneType
    geometry: list[list[float]] = Field(min_length=2)
    inward_side: Literal["left", "right"] | None = None

    @model_validator(mode="after")
    def _shape(self) -> "ZoneIn":
        if any(len(p) != 2 or not all(0 <= v <= 1 for v in p) for p in self.geometry):
            raise ValueError("points are [x, y] in 0..1 (normalised to the snapshot)")
        if self.type is m.ZoneType.door_line and (len(self.geometry) != 2 or self.inward_side is None):
            raise ValueError("a door line has 2 points and an inward side")
        if self.type is not m.ZoneType.door_line and len(self.geometry) < 3:
            raise ValueError("a polygon needs at least 3 points")
        return self


class CameraIn(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    role: m.CameraRole
    rtsp_main_path: str = "/stream1"
    rtsp_sub_path: str = "/stream2"
    zones: list[ZoneIn] = []

    @model_validator(mode="after")
    def _zones(self) -> "CameraIn":
        kinds = [z.type for z in self.zones]
        if self.role is m.CameraRole.door and kinds.count(m.ZoneType.door_line) != 1:
            raise ValueError("a door camera needs exactly one door line")
        if self.role is m.CameraRole.counter and not {m.ZoneType.customer_side, m.ZoneType.staff_side} <= set(
            kinds
        ):
            raise ValueError("a counter camera needs a customer side and a staff side")
        return self


class CameraOut(BaseModel):
    name: str
    role: m.CameraRole
    zones: list[dict[str, object]]


def _kit_for(s: DB, kit_id: uuid.UUID, user: m.User, action: Action) -> tuple[m.Kit, m.Shop]:
    kit = s.get(m.Kit, kit_id)
    if kit is None or kit.shop_id is None:
        raise Problem(404, "not-found", "Kit not found")
    return kit, load_shop(s, kit.shop_id, user, action)


@router.put("/kits/{kit_id}/cameras")
def put_cameras(kit_id: uuid.UUID, body: list[CameraIn], user: CurrentUser, s: DB) -> list[CameraOut]:
    """AC-F8-2: replaces cameras and zones; bumps config_version so the agent picks them up."""
    kit, shop = _kit_for(s, kit_id, user, Action.zones_edit)
    if len({c.name for c in body}) != len(body):
        raise Problem(422, "validation-error", "camera names must be unique")
    existing = {c.name: c for c in s.scalars(select(m.Camera).where(m.Camera.kit_id == kit.id))}
    for name, cam in existing.items():
        if name not in {c.name for c in body}:
            s.delete(cam)
    out = []
    for c in body:
        cam = existing.get(c.name) or m.Camera(
            kit_id=kit.id,
            name=c.name,
            role=c.role,
            rtsp_main_path=c.rtsp_main_path,
            rtsp_sub_path=c.rtsp_sub_path,
        )
        cam.role, cam.rtsp_main_path, cam.rtsp_sub_path = c.role, c.rtsp_main_path, c.rtsp_sub_path
        s.add(cam)
        s.flush()
        s.execute(delete(m.Zone).where(m.Zone.camera_id == cam.id))
        for z in c.zones:
            s.add(m.Zone(camera_id=cam.id, type=z.type, geometry=z.geometry, inward_side=z.inward_side))
        out.append(CameraOut(name=c.name, role=c.role, zones=[z.model_dump(mode="json") for z in c.zones]))
    kit.config_version += 1
    audit(
        s,
        user,
        "zone.update",
        account_id=shop.account_id,
        target_type="kit",
        target_id=kit.id,
        detail={"cameras": [c.name for c in body], "config_version": kit.config_version},
    )
    s.commit()
    return out


class StreamOut(BaseModel):
    source: str
    reachable: bool
    codec: str | None
    width: int | None
    height: int | None
    fps: float | None
    checked_at: str
    verdict: setup_checks.StreamVerdict


class AngleOut(BaseModel):
    passed: bool
    failed_items: list[str]
    source: str
    checked_at: str


class CameraSetupOut(BaseModel):
    name: str
    role: Literal["door", "counter"]
    stream: StreamOut | None
    angle: AngleOut | None
    angle_items: list[str]
    angle_passed: bool
    addon_camera_needed: bool


class KitSetupOut(BaseModel):
    cameras: list[CameraSetupOut]
    blockers: list[str]


SETUP_ROLES: tuple[Literal["door", "counter"], ...] = ("door", "counter")


def _setup(s: DB, kit: m.Kit) -> KitSetupOut:
    cameras = list(s.scalars(select(m.Camera).where(m.Camera.kit_id == kit.id)))
    by_role = {c.role.value: c.name for c in cameras}
    out = []
    for role in SETUP_ROLES:
        name = by_role.get(role, role)  # the box names its two slots after the roles
        report = kit.stream_checks.get(name)
        angle = kit.angle_checks.get(name)
        verdict = setup_checks.stream_verdict(report)
        stream = StreamOut.model_validate(report | {"verdict": verdict}) if report and verdict else None
        out.append(
            CameraSetupOut(
                name=name,
                role=role,
                stream=stream,
                angle=AngleOut.model_validate(angle) if angle else None,
                angle_items=list(setup_checks.ANGLE_ITEMS[role]),
                angle_passed=setup_checks.angle_passed(kit, name),
                addon_camera_needed=setup_checks.addon_camera_needed(kit, name),
            )
        )
    return KitSetupOut(cameras=out, blockers=setup_checks.blockers(kit, cameras))


@router.get("/kits/{kit_id}/setup")
def get_setup(kit_id: uuid.UUID, user: CurrentUser, s: DB) -> KitSetupOut:
    """Stream checks reported by the box and angle checks, per role (AC-F8-6..8)."""
    kit, _ = _kit_for(s, kit_id, user, Action.zones_edit)
    return _setup(s, kit)


class AngleCheckIn(BaseModel):
    role: Literal["door", "counter"]
    items: dict[str, bool]


@router.put(
    "/kits/{kit_id}/angle-checks/{camera}",
    responses={409: {"description": "no stream reported by the box yet"}},
)
def put_angle_check(
    kit_id: uuid.UUID,
    camera: Annotated[str, Path(pattern=r"^[a-z][a-z0-9_]{0,31}$")],
    body: AngleCheckIn,
    user: CurrentUser,
    s: DB,
) -> KitSetupOut:
    """AC-F8-8: every item ticked = passed; any item failed records "add-on camera needed" for the
    stream source it was done on. A new channel or an add-on camera gets a new check."""
    kit, shop = _kit_for(s, kit_id, user, Action.zones_edit)
    expected = set(setup_checks.ANGLE_ITEMS[body.role])
    if set(body.items) != expected:
        raise Problem(422, "validation-error", f"items must be exactly {sorted(expected)}")
    report = kit.stream_checks.get(camera)
    if not report:
        raise Problem(409, "stream-check-required", "The box has not reported this camera's stream yet")
    failed = sorted(k for k, ok in body.items.items() if not ok)
    now = datetime.now(UTC)
    kit.angle_checks = {
        **kit.angle_checks,
        camera: {"passed": not failed, "failed_items": failed, "source": report["source"],
                 "checked_at": now.isoformat(), "by": str(user.id)},
    }  # fmt: skip
    audit(s, user, "kit.angle_check", account_id=shop.account_id, target_type="kit", target_id=kit.id,
          detail={"camera": camera, "passed": not failed, "failed_items": failed})  # fmt: skip
    s.commit()
    return _setup(s, kit)


class CountCheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    kit_id: uuid.UUID
    started_at: datetime
    ended_at: datetime | None
    manual_count: int | None
    agent_count: int | None
    error_pct: Decimal | None
    passed: bool | None
    override_reason: str | None


@router.post("/kits/{kit_id}/count-checks", status_code=201)
def start_count_check(kit_id: uuid.UUID, user: CurrentUser, s: DB) -> CountCheckOut:
    kit, _ = _kit_for(s, kit_id, user, Action.kit_command)
    now = datetime.now(UTC)
    check = m.CountCheck(kit_id=kit.id, installer_id=user.id, started_at=now)
    s.add(check)
    s.flush()
    commands.enqueue(
        s, kit, m.CommandType.count_check_start, {"count_check_id": str(check.id)}, requested_by=user.id
    )
    s.commit()
    return CountCheckOut.model_validate(check)


class StopIn(BaseModel):
    manual_count: int = Field(ge=0, le=10_000)
    override_reason: str | None = Field(default=None, max_length=500)


def evaluate(manual: int, agent: int) -> tuple[Decimal | None, bool]:
    """AC-F8-3: error ≤ 10 % on ≥ 20 entries."""
    if manual == 0:
        return None, False
    error = (Decimal(abs(agent - manual)) * 100 / Decimal(manual)).quantize(Decimal("0.01"))
    return error, manual >= COUNT_CHECK_MIN_ENTRIES and error <= COUNT_CHECK_MAX_ERROR_PCT


@router.post("/count-checks/{check_id}/stop")
def stop_count_check(check_id: uuid.UUID, body: StopIn, user: CurrentUser, s: DB) -> CountCheckOut:
    """The agent's count = door entries (staff included: the installer counts every person) uploaded
    for the check window."""
    check = s.get(m.CountCheck, check_id)
    if check is None:
        raise Problem(404, "not-found", "Count check not found")
    kit, shop = _kit_for(s, check.kit_id, user, Action.kit_command)
    if check.ended_at is not None:
        # a failed check can still be overridden afterwards, once, with a reason (AC-F8-3)
        if body.override_reason and not check.passed and not check.override_reason:
            check.override_reason = body.override_reason
            audit(s, user, "count_check.override", account_id=shop.account_id, target_type="count_check",
                  target_id=check.id, detail={"reason": body.override_reason, "manual": check.manual_count,
                  "agent": check.agent_count})  # fmt: skip
            s.commit()
        return CountCheckOut.model_validate(check)
    now = datetime.now(UTC)
    agent = (
        s.scalar(
            select(func.count())
            .select_from(m.Event)
            .where(
                m.Event.kit_id == kit.id,
                m.Event.type == m.EventType.entry,
                m.Event.started_at >= check.started_at,
                m.Event.started_at < now,
            )
        )
        or 0
    )
    check.ended_at, check.manual_count, check.agent_count = now, body.manual_count, agent
    check.error_pct, check.passed = evaluate(body.manual_count, agent)
    if body.override_reason and not check.passed:
        check.override_reason = body.override_reason
        audit(
            s,
            user,
            "count_check.override",
            account_id=shop.account_id,
            target_type="count_check",
            target_id=check.id,
            detail={"reason": body.override_reason, "manual": body.manual_count, "agent": agent},
        )
    commands.enqueue(
        s, kit, m.CommandType.count_check_stop, {"count_check_id": str(check.id)}, requested_by=user.id
    )
    s.commit()
    return CountCheckOut.model_validate(check)


@router.post("/kits/{kit_id}/activate", responses={409: {"description": "preconditions not met"}})
def activate(kit_id: uuid.UUID, user: CurrentUser, s: DB) -> KitOut:
    kit, shop = _kit_for(s, kit_id, user, Action.kit_command)
    if not shop.cdp_declaration_ref:
        raise Problem(409, "cdp-missing", "The shop needs its CDP declaration reference first (AC-F8-4)")
    cameras = list(s.scalars(select(m.Camera).where(m.Camera.kit_id == kit.id)))
    blocking = setup_checks.blockers(kit, cameras)
    if blocking:
        code = blocking[0].split(":")[0]
        raise Problem(409, code, "Recorder setup is not finished (AC-F8-6..8): " + ", ".join(blocking))
    check = s.scalars(
        select(m.CountCheck)
        .where(m.CountCheck.kit_id == kit.id, m.CountCheck.ended_at.is_not(None))
        .order_by(m.CountCheck.ended_at.desc())
    ).first()
    if check is None or not (check.passed or check.override_reason):
        raise Problem(
            409, "count-check-required", "A passed count check (or an override with a reason) is needed"
        )
    now = datetime.now(UTC)
    kit.status, kit.installed_at = m.KitStatus.active, kit.installed_at or now
    kit.config_version += 1  # the box learns it is active and closes its setup page (AC-F10-4)
    if shop.status is not m.ShopStatus.active:
        shop.status, shop.activated_at = m.ShopStatus.active, now
    audit(
        s,
        user,
        "kit.activate",
        account_id=shop.account_id,
        target_type="kit",
        target_id=kit.id,
        detail={"count_check_id": str(check.id), "override": bool(check.override_reason)},
    )
    s.commit()
    return KitOut.model_validate(kit)


class CommandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    type: m.CommandType
    status: m.CommandStatus
    created_at: datetime
    completed_at: datetime | None
    clip_id: uuid.UUID | None = None


@router.get("/commands/{command_id}")
def get_command(command_id: uuid.UUID, user: CurrentUser, s: DB) -> CommandOut:
    """Poll a snapshot/clip request (installer calibration, owner live photo)."""
    cmd = s.get(m.EdgeCommand, command_id)
    kit = s.get(m.Kit, cmd.kit_id) if cmd else None
    if cmd is None or kit is None or kit.shop_id is None:
        raise Problem(404, "not-found", "Command not found")
    action = Action.snapshot_request if cmd.type is m.CommandType.snapshot else Action.clip_view
    load_shop(s, kit.shop_id, user, action)
    out = CommandOut.model_validate(cmd)
    out.clip_id = s.scalar(select(m.Clip.id).where(m.Clip.command_id == cmd.id))
    return out
