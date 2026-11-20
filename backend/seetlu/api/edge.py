"""Edge ingest API (device token): register, config, events, heartbeat, commands (docs/04, docs/05)."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from seetlu.api.deps import DB
from seetlu.core.problem import Problem
from seetlu.core.security import hash_token, new_device_token, verify_token
from seetlu.db import models as m
from seetlu.domain.commands import UPLOAD_KINDS, object_key
from seetlu.reports import service as report_service
from seetlu.storage.s3 import presigned_put

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/edge", tags=["edge"])

CLIP_RETENTION_DAYS = 7  # docs/09 rule 4


# ---------- device auth ----------
def make_device_token(kit_id: uuid.UUID) -> tuple[str, str]:
    """Token = '<kit id>.<32 random bytes>' so the kit row is found without scanning hashes."""
    secret = new_device_token()
    return f"{kit_id}.{secret}", hash_token(secret)


def current_kit(request: Request, s: DB) -> m.Kit:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    kit_part, _, secret = token.partition(".")
    if scheme.lower() != "bearer" or not secret:
        raise Problem(401, "unauthorized", "Missing device token")
    try:
        kit_id = uuid.UUID(kit_part)
    except ValueError as exc:
        raise Problem(401, "invalid-token", "Device token is invalid") from exc
    kit = s.get(m.Kit, kit_id)
    if kit is None or kit.device_token_hash is None or not verify_token(kit.device_token_hash, secret):
        raise Problem(401, "invalid-token", "Device token is invalid")
    if kit.status is m.KitStatus.retired:
        raise Problem(403, "kit-retired", "Kit is retired")
    kit.last_seen_at = datetime.now(UTC)
    return kit


CurrentKit = Annotated[m.Kit, Depends(current_kit)]


def _shop_of(s: Session, kit: m.Kit) -> m.Shop:
    shop = s.get(m.Shop, kit.shop_id) if kit.shop_id else None
    if shop is None:
        raise Problem(409, "kit-not-attached", "Kit is not attached to a shop")
    return shop


# ---------- schemas (docs/04 components) ----------
class RegisterIn(BaseModel):
    serial: str = Field(min_length=1, max_length=64)
    claim_token: str = Field(min_length=1, max_length=256)
    agent_version: str | None = None


class RegisterOut(BaseModel):
    kit_id: uuid.UUID
    device_token: str


class Detect(BaseModel):
    width: int
    height: int
    fps: int


class ZoneOut(BaseModel):
    id: uuid.UUID
    type: m.ZoneType
    geometry: list[list[float]]
    inward_side: Literal["left", "right"] | None


class CameraOut(BaseModel):
    name: str
    role: m.CameraRole
    rtsp_main_path: str
    rtsp_sub_path: str
    detect: Detect
    zones: list[ZoneOut]


class ShopConfig(BaseModel):
    timezone: str
    opening_hours: dict[str, Any]
    expected_staff: int
    service_min_s: int
    wait_min_s: int
    unattended_min_s: int


class EdgeConfig(BaseModel):
    config_version: int
    shop: ShopConfig
    cameras: list[CameraOut]
    target_agent_version: str | None


class EdgeEventIn(BaseModel):
    id: uuid.UUID
    type: Literal["entry", "exit", "service", "wait", "unattended", "after_hours_motion"]
    camera: str
    started_at: datetime
    ended_at: datetime | None = None
    is_staff: bool = False
    confidence: float = Field(default=1.0, ge=0, le=1)
    frigate_event_ids: list[str] = []
    meta: dict[str, Any] = {}

    @model_validator(mode="after")
    def _times(self) -> "EdgeEventIn":
        if self.started_at.tzinfo is None or (self.ended_at is not None and self.ended_at.tzinfo is None):
            raise ValueError("timestamps need a UTC offset")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at is before started_at")
        return self


class EventsIn(BaseModel):
    events: list[EdgeEventIn] = Field(max_length=500)


class EventsOut(BaseModel):
    accepted: int
    duplicates: int


class HeartbeatIn(BaseModel):
    at: datetime
    agent_version: str
    power_source: Literal["mains", "battery"] | None = None
    battery_pct: int | None = Field(default=None, ge=0, le=100)
    storage_pct: int | None = Field(default=None, ge=0, le=100)
    cpu_temp_c: float | None = None
    fps: dict[str, float] | None = None
    network: Literal["wifi", "4g", "ethernet"] | None = None
    frigate_version: str | None = None
    queue_depth: int | None = Field(default=None, ge=0)


class EdgeCommandOut(BaseModel):
    id: uuid.UUID
    type: m.CommandType
    params: dict[str, Any]
    upload_url: str | None
    expires_at: datetime


class CommandResultIn(BaseModel):
    status: Literal["done", "failed", "unavailable"]
    result: dict[str, Any] = {}


# ---------- routes ----------
@router.post("/register")
def register(body: RegisterIn, s: DB) -> RegisterOut:
    """First boot: serial + claim token → device token. Only after an installer claimed the kit.
    Re-registration rotates the token (docs/09)."""
    kit = s.scalars(select(m.Kit).where(m.Kit.serial == body.serial).with_for_update()).first()
    if kit is None or not verify_token(kit.claim_token_hash, body.claim_token):
        raise Problem(401, "invalid-claim", "Unknown serial or wrong claim token")
    if kit.shop_id is None or kit.status in (m.KitStatus.in_stock, m.KitStatus.retired):
        raise Problem(403, "not-claimed", "Kit has not been claimed by an installer yet")
    token, token_hash = make_device_token(kit.id)
    kit.device_token_hash = token_hash
    if body.agent_version:
        kit.agent_version = body.agent_version
    kit.last_seen_at = datetime.now(UTC)
    s.commit()
    return RegisterOut(kit_id=kit.id, device_token=token)


def build_config(s: Session, kit: m.Kit) -> EdgeConfig:
    shop = _shop_of(s, kit)
    cameras = s.scalars(select(m.Camera).where(m.Camera.kit_id == kit.id).order_by(m.Camera.name)).all()
    out: list[CameraOut] = []
    for cam in cameras:
        zones = s.scalars(select(m.Zone).where(m.Zone.camera_id == cam.id).order_by(m.Zone.created_at)).all()
        out.append(
            CameraOut(
                name=cam.name,
                role=cam.role,
                rtsp_main_path=cam.rtsp_main_path,
                rtsp_sub_path=cam.rtsp_sub_path,
                detect=Detect(width=cam.detect_width, height=cam.detect_height, fps=cam.detect_fps),
                zones=[
                    ZoneOut(id=z.id, type=z.type, geometry=z.geometry, inward_side=z.inward_side)
                    for z in zones
                ],
            )
        )
    return EdgeConfig(
        config_version=kit.config_version,
        shop=ShopConfig(
            timezone=shop.timezone,
            opening_hours=shop.opening_hours,
            expected_staff=shop.expected_staff,
            service_min_s=shop.service_min_s,
            wait_min_s=shop.wait_min_s,
            unattended_min_s=shop.unattended_min_s,
        ),
        cameras=out,
        target_agent_version=kit.target_agent_version,
    )


@router.get("/config", response_model=EdgeConfig, responses={304: {"description": "unchanged"}})
def get_config(
    kit: CurrentKit, s: DB, if_none_match: Annotated[str | None, Header()] = None
) -> EdgeConfig | Response:
    etag = f'"{kit.config_version}"'
    if if_none_match is not None and etag in {t.strip() for t in if_none_match.split(",")}:
        s.commit()
        return Response(status_code=304, headers={"ETag": etag})
    config = build_config(s, kit)
    s.commit()
    return Response(
        content=config.model_dump_json(
            exclude={"target_agent_version"} if config.target_agent_version is None else None
        ),
        media_type="application/json",
        headers={"ETag": etag},
    )


@router.post("/events")
def post_events(body: EventsIn, kit: CurrentKit, s: DB) -> EventsOut:
    """Idempotent upsert keyed by the edge-generated UUIDv7. Re-sending an event updates the
    mutable fields (is_staff correction, end time, confidence, Frigate ids, meta)."""
    shop = _shop_of(s, kit)
    cameras = {c.name: c.id for c in s.scalars(select(m.Camera).where(m.Camera.kit_id == kit.id))}
    accepted = duplicates = 0
    for ev in body.events:
        stmt = insert(m.Event).values(
            id=ev.id,
            shop_id=shop.id,
            kit_id=kit.id,
            camera_id=cameras.get(ev.camera),
            type=m.EventType(ev.type),
            started_at=ev.started_at,
            ended_at=ev.ended_at,
            is_staff=ev.is_staff,
            confidence=ev.confidence,
            frigate_event_ids=ev.frigate_event_ids,
            meta=ev.meta | ({"camera": ev.camera} if ev.camera not in cameras else {}),
        )
        upsert: Any = stmt.on_conflict_do_update(
            index_elements=[m.Event.id, m.Event.started_at],
            set_={
                "is_staff": stmt.excluded.is_staff,
                "ended_at": stmt.excluded.ended_at,
                "confidence": stmt.excluded.confidence,
                "frigate_event_ids": stmt.excluded.frigate_event_ids,
                "meta": stmt.excluded.meta,
            },
        ).returning(literal_column("(xmax = 0)").label("inserted"))  # xmax = 0: row was inserted
        if s.execute(upsert).scalar_one():
            accepted += 1
        else:
            duplicates += 1
    s.commit()
    _recompute_late(s, shop, [ev.started_at for ev in body.events])
    return EventsOut(accepted=accepted, duplicates=duplicates)


def _recompute_late(s: Session, shop: m.Shop, starts: list[datetime]) -> None:
    """Events for a day whose report was already sent: recompute it now (never resent, docs/06)."""
    try:
        for d in report_service.late_dates(s, shop, starts):
            report_service.recompute(s, shop.id, d)
    except Exception:  # the upload itself succeeded; a failed recompute must not make the edge retry
        s.rollback()
        log.exception("late-data recompute failed for shop %s", shop.id)


@router.post("/heartbeat", status_code=204, response_class=Response)
def heartbeat(body: HeartbeatIn, kit: CurrentKit, s: DB) -> Response:
    if body.at.tzinfo is None:
        raise Problem(422, "validation-error", "at needs a UTC offset")
    stmt = insert(m.Heartbeat).values(kit_id=kit.id, **body.model_dump()).on_conflict_do_nothing()
    s.execute(stmt)
    kit.agent_version = body.agent_version
    if body.frigate_version:
        kit.frigate_version = body.frigate_version
    kit.health = m.KitHealth.ok
    s.commit()
    return Response(status_code=204)


@router.get("/commands")
def get_commands(kit: CurrentKit, s: DB) -> list[EdgeCommandOut]:
    """Queued and already-sent (unfinished) commands; the agent must treat command ids idempotently."""
    now = datetime.now(UTC)
    rows = s.scalars(
        select(m.EdgeCommand)
        .where(
            m.EdgeCommand.kit_id == kit.id,
            m.EdgeCommand.status.in_([m.CommandStatus.queued, m.CommandStatus.sent]),
        )
        .order_by(m.EdgeCommand.created_at)
    ).all()
    out: list[EdgeCommandOut] = []
    for cmd in rows:
        if cmd.expires_at <= now:
            cmd.status = m.CommandStatus.expired
            continue
        cmd.status = m.CommandStatus.sent
        upload_url = None
        if cmd.type in UPLOAD_KINDS and kit.shop_id is not None:
            key = object_key(kit.shop_id, cmd)
            assert key is not None
            upload_url = presigned_put(key, UPLOAD_KINDS[cmd.type][2])
        out.append(
            EdgeCommandOut(
                id=cmd.id, type=cmd.type, params=cmd.params, upload_url=upload_url, expires_at=cmd.expires_at
            )
        )
    s.commit()
    return out


@router.post("/commands/{command_id}/result", status_code=204, response_class=Response)
def command_result(command_id: uuid.UUID, body: CommandResultIn, kit: CurrentKit, s: DB) -> Response:
    cmd = s.get(m.EdgeCommand, command_id, with_for_update=True)
    if cmd is None or cmd.kit_id != kit.id:
        raise Problem(404, "not-found", "Command not found")
    if cmd.status in (m.CommandStatus.done, m.CommandStatus.failed, m.CommandStatus.unavailable):
        s.commit()
        return Response(status_code=204)  # idempotent
    now = datetime.now(UTC)
    cmd.status = m.CommandStatus(body.status)
    cmd.result = body.result
    cmd.completed_at = now
    if body.status == "done" and cmd.type in UPLOAD_KINDS and kit.shop_id is not None:
        key = object_key(kit.shop_id, cmd)
        assert key is not None
        event_id = cmd.params.get("event_id")
        s.add(
            m.Clip(
                shop_id=kit.shop_id,
                event_id=uuid.UUID(event_id) if event_id else None,
                command_id=cmd.id,
                object_key=key,  # server-chosen key; the agent cannot pick another object
                kind=UPLOAD_KINDS[cmd.type][0],
                duration_s=body.result.get("duration_s"),
                size_bytes=body.result.get("size_bytes"),
                expires_at=now + timedelta(days=CLIP_RETENTION_DAYS),
            )
        )
    s.commit()
    return Response(status_code=204)
