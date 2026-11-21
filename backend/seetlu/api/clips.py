"""Clips, moment clips and live snapshots for signed-in users (docs/04, AC-F5-2..4, docs/09 audit)."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel

from seetlu.api.deps import DB, CurrentUser, load_shop
from seetlu.core.audit import audit
from seetlu.core.authz import Action
from seetlu.core.problem import Problem
from seetlu.db import models as m
from seetlu.messaging import clips
from seetlu.storage.s3 import GET_TTL_S, presigned_get

router = APIRouter(prefix="/v1", tags=["clips"])


class ClipUrlOut(BaseModel):
    id: uuid.UUID
    kind: str
    url: str
    expires_in_s: int
    duration_s: int | None


class ClipRequestOut(BaseModel):
    status: Literal["ready", "queued"]
    clip_id: uuid.UUID | None = None
    command_id: uuid.UUID | None = None


@router.get("/clips/{clip_id}", responses={410: {"description": "expired or unavailable"}})
def get_clip(
    clip_id: uuid.UUID, user: CurrentUser, s: DB, exp: int | None = None, sig: str | None = None
) -> ClipUrlOut:
    """A 15-minute signed URL. Links from WhatsApp carry `exp` + `sig` and stop working after 24 h."""
    clip = s.get(m.Clip, clip_id)
    if clip is None:
        raise Problem(404, "not-found", "Clip not found")
    action = Action.snapshot_request if clip.kind == "snapshot" else Action.clip_view
    shop = load_shop(s, clip.shop_id, user, action)
    now = datetime.now(UTC)
    if (exp is not None or sig is not None) and not (
        exp is not None and sig is not None and clips.link_valid(clip.id, exp, sig, now)
    ):
        raise Problem(410, "link-expired", "This link has expired; ask again from the report")
    if clip.expires_at is not None and clip.expires_at <= now:
        raise Problem(410, "clip-expired", "This clip is no longer stored")
    audit(
        s,
        user,
        "clip.view",
        account_id=shop.account_id,
        target_type="clip",
        target_id=clip.id,
        detail={"kind": clip.kind, "via": "link" if sig else "app"},
    )
    s.commit()
    return ClipUrlOut(
        id=clip.id,
        kind=clip.kind,
        url=presigned_get(clip.object_key),
        expires_in_s=GET_TTL_S,
        duration_s=clip.duration_s,
    )


@router.post("/moments/{report_id}/{rank}/clip", responses={202: {"model": ClipRequestOut}})
def moment_clip(
    report_id: uuid.UUID, rank: int, user: CurrentUser, s: DB, response: Response
) -> ClipRequestOut:
    report = s.get(m.DailyReport, report_id)
    if report is None:
        raise Problem(404, "not-found", "Report not found")
    load_shop(s, report.shop_id, user, Action.clip_view)
    req = clips.request_moment_clip(s, report, rank, None, datetime.now(UTC))
    if req.status == "no_moment":
        raise Problem(404, "not-found", f"No moment {rank} in this report")
    if req.status == "unavailable":
        raise Problem(410, "clip-unavailable", "Older than the 7-day kit buffer, or not cut")
    s.commit()
    if req.status == "ready" and req.clip is not None:
        return ClipRequestOut(
            status="ready", clip_id=req.clip.id, command_id=req.command.id if req.command else None
        )
    response.status_code = 202
    return ClipRequestOut(status="queued", command_id=req.command.id if req.command else None)


@router.post("/shops/{shop_id}/snapshot", status_code=202)
def snapshot(shop_id: uuid.UUID, user: CurrentUser, s: DB) -> ClipRequestOut:
    shop = load_shop(s, shop_id, user, Action.snapshot_request)
    kit = clips.shop_kit(s, shop.id)
    if kit is None:
        raise Problem(409, "no-kit", "No kit installed in this shop")
    from seetlu.domain import commands

    cmd = commands.enqueue(s, kit, m.CommandType.snapshot, {"camera": "counter"}, requested_by=user.id)
    audit(
        s,
        user,
        "snapshot.request",
        account_id=shop.account_id,
        target_type="edge_command",
        target_id=cmd.id,
        detail={"via": "app"},
    )
    s.commit()
    return ClipRequestOut(status="queued", command_id=cmd.id)
