"""Cloud commands (docs/05 "Commands"): clip, snapshot, count check, agent update, reboot.

Each command id is executed at most once (ids are remembered in the outbox database), because the
server keeps returning `sent` commands until it receives their result.
"""

import logging
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from seetlu_agent.engine import Engine
from seetlu_agent.outbox import Outbox

log = logging.getLogger(__name__)

CLIP_MAX_S = 20
SNAPSHOT_WIDTH = 960
# ffmpeg's JPEG scale is 2 (best) .. 31; 4 is close to libjpeg quality 70 (docs/decisions.md)
SNAPSHOT_QSCALE = 4

Runner = Callable[[list[str]], None]


def run_cmd(argv: list[str]) -> None:
    subprocess.run(argv, check=True, capture_output=True, timeout=120)  # noqa: S603 - fixed argv


def clip_argv(src: Path, dst: Path, max_s: float) -> list[str]:
    """H.264 480p, CRF 28, preset veryfast, <= 20 s, no audio (docs/05)."""
    return ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(src), "-t", f"{max_s:.3f}", "-an",
            "-vf", "scale=-2:480", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)]  # fmt: skip


def snapshot_argv(src: Path, dst: Path) -> list[str]:
    return ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(src),
            "-vf", f"scale={SNAPSHOT_WIDTH}:-2", "-q:v", str(SNAPSHOT_QSCALE),
            "-frames:v", "1", str(dst)]  # fmt: skip


def epoch(value: Any) -> float:
    if isinstance(value, int | float):
        return float(value)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()


def key_from_upload_url(url: str) -> str | None:
    """Presigned path-style URL `/bucket/key...` → key (the server chose it, we only echo it back)."""
    parts = unquote(urlparse(url).path).lstrip("/").split("/", 1)
    return parts[1] if len(parts) == 2 else None


VERSION_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]{0,127}")  # a valid image tag


def write_env_var(path: Path, key: str, value: str) -> None:
    """Set KEY=value in a dotenv file, keeping the other lines."""
    lines = path.read_text().splitlines() if path.exists() else []
    lines = [ln for ln in lines if not ln.startswith(f"{key}=")] + [f"{key}={value}"]
    path.write_text("\n".join(lines) + "\n")


class UnavailableError(Exception):
    """The footage is not in the edge buffer any more (AC-F5-4)."""


class CommandRunner:
    def __init__(
        self,
        engine: Engine,
        outbox: Outbox,
        frigate: httpx.Client,
        uploads: httpx.Client | None = None,
        run: Runner = run_cmd,
        compose_file: str = "/data/agent/docker-compose.edge.yml",
        host_dir: Path = Path("/data/agent/host"),
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.engine, self.outbox, self.frigate = engine, outbox, frigate
        self.uploads = uploads or httpx.Client(timeout=120)
        self.run, self.compose_file, self.host_dir = run, compose_file, host_dir
        self.clock = clock or (lambda: engine.last_ts or 0.0)

    def execute(self, cmd: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        """Run one command; returns (status, result) or None when it was already executed."""
        cid = str(cmd["id"])
        if self.outbox.command_done(cid):
            return None
        kind = str(cmd["type"])
        params: dict[str, Any] = cmd.get("params") or {}
        try:
            handler = getattr(self, f"_{kind}")
            status, result = "done", handler(params, cmd.get("upload_url"))
        except UnavailableError as exc:
            status, result = "unavailable", {"reason": str(exc)}
        except Exception as exc:
            log.exception("command %s (%s) failed", cid, kind)
            status, result = "failed", {"error": type(exc).__name__, "detail": str(exc)[:500]}
        self.outbox.mark_command_done(cid)
        return status, result

    # ---------- media ----------
    def _fetch(self, path: str, dst: Path) -> None:
        r = self.frigate.get(path, timeout=120)
        if r.status_code == 404:
            raise UnavailableError("not in the edge buffer")
        r.raise_for_status()
        dst.write_bytes(r.content)

    def _put(self, url: str | None, src: Path, content_type: str) -> int:
        if not url:
            raise ValueError("command has no upload_url")
        data = src.read_bytes()
        r = self.uploads.put(url, content=data, headers={"Content-Type": content_type})
        r.raise_for_status()
        return len(data)

    def _clip(self, params: dict[str, Any], upload_url: str | None) -> dict[str, Any]:
        camera = str(params.get("camera") or self.engine.counter_camera)
        start, end = epoch(params["start"]), epoch(params["end"])
        end = min(end, start + CLIP_MAX_S)
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "src.mp4", Path(tmp) / "clip.mp4"
            self._fetch(f"/api/{camera}/start/{int(start)}/end/{int(end + 0.999)}/clip.mp4", src)
            self.run(clip_argv(src, dst, end - start))
            size = self._put(upload_url, dst, "video/mp4")
        return {"object_key": key_from_upload_url(upload_url or ""), "duration_s": round(end - start, 1),
                "size_bytes": size}  # fmt: skip

    def _snapshot(self, params: dict[str, Any], upload_url: str | None) -> dict[str, Any]:
        camera = str(params.get("camera") or self.engine.counter_camera)
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "latest.jpg", Path(tmp) / "snapshot.jpg"
            self._fetch(f"/api/{camera}/latest.jpg", src)
            self.run(snapshot_argv(src, dst))
            size = self._put(upload_url, dst, "image/jpeg")
        return {"object_key": key_from_upload_url(upload_url or ""), "size_bytes": size}

    # ---------- install ----------
    def _count_check_start(self, params: dict[str, Any], _url: str | None) -> dict[str, Any]:
        self.engine.count_check_start(self.clock())
        return {"started_at": self.clock()}

    def _count_check_stop(self, params: dict[str, Any], _url: str | None) -> dict[str, Any]:
        return {"agent_count": self.engine.count_check_stop()}

    # ---------- maintenance ----------
    def _update_agent(self, params: dict[str, Any], _url: str | None) -> dict[str, Any]:
        """Pin the new image tag in the compose project's `.env` (read by `docker compose` and by the
        boot unit), pull, recreate. A failed pull restores the previous tag (docs/05, AC-F10-3)."""
        version = str(params.get("version") or "")
        if not VERSION_RE.fullmatch(version):
            raise ValueError(f"invalid agent version {version!r}")
        docker = shutil.which("docker") or "docker"
        base = [docker, "compose", "-f", self.compose_file]
        env_file = Path(self.compose_file).parent / ".env"
        previous = env_file.read_text() if env_file.exists() else None
        write_env_var(env_file, "SEETLU_AGENT_VERSION", version)
        try:
            self.run([*base, "pull", "seetlu-agent"])
        except Exception:
            if previous is None:
                env_file.unlink(missing_ok=True)
            else:
                env_file.write_text(previous)
            raise
        # `up -d` replaces this container; the new version is reported in the next heartbeat
        self.run([*base, "up", "-d", "--no-deps", "seetlu-agent"])
        return {"requested_version": version}

    def _reboot(self, params: dict[str, Any], _url: str | None) -> dict[str, Any]:
        """The host helper (systemd path unit installed by provision.sh) runs `systemctl reboot`."""
        self.host_dir.mkdir(parents=True, exist_ok=True)
        (self.host_dir / "reboot-requested").write_text(str(self.clock()))
        return {"requested": True}
