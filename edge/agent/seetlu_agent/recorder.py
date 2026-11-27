"""The shop's existing recorder (docs/13, AC-F8-5..7): brand presets, channel scan, stream check.

The box only reads sub streams over RTSP; it never changes recorder settings (decision D3). Logins stay
in secrets.json on the box; the `source` label sent to the cloud never contains them.
"""

import json
import shutil
import subprocess
from typing import Any, Literal
from urllib.parse import quote

Brand = Literal["hikvision", "dahua", "xiongmai", "other"]
BRANDS: tuple[Brand, ...] = ("hikvision", "dahua", "xiongmai", "other")
MAX_CHANNELS = 16
SCAN_STOP_AFTER_MISSES = 4  # recorders number channels from 1; stop after a run of empty ones

USABLE_CODECS = {"h264", "hevc"}  # same rules as the cloud (seetlu.domain.setup_checks)
MIN_WIDTH, MIN_HEIGHT, MIN_FPS = 640, 360, 5.0


def sub_path(brand: Brand, channel: int, username: str = "", password: str = "") -> str:
    """RTSP path of a channel's sub stream for a recorder brand (docs/13 section 3.1)."""
    if brand == "hikvision":
        return f"/Streaming/Channels/{channel}02"
    if brand == "dahua":
        return f"/cam/realmonitor?channel={channel}&subtype=1"
    if brand == "xiongmai":  # XMeye: the login is part of the path, not of the URL authority
        return (
            f"/user={quote(username, safe='')}&password={quote(password, safe='')}"
            f"&channel={channel}&stream=1.sdp?real_stream"
        )
    raise ValueError(f"no preset for {brand}")


def url_for(secret: dict[str, Any], default_path: str) -> str:
    """Full RTSP URL of one camera slot from what the installer saved on the LAN page."""
    brand: Brand = secret.get("brand") or "other"
    user, pw = str(secret.get("username") or ""), str(secret.get("password") or "")
    if brand == "other":
        path = str(secret.get("path") or default_path)
    else:
        path = sub_path(brand, int(secret.get("channel") or 1), user, pw)
    auth = f"{quote(user, safe='')}:{quote(pw, safe='')}@" if user and brand != "xiongmai" else ""
    return f"rtsp://{auth}{secret['host']}:{int(secret.get('port') or 554)}{path}"


def source_label(secret: dict[str, Any], default_path: str = "") -> str:
    """What the cloud stores to know which stream an angle check was done on. No credentials."""
    brand = secret.get("brand") or "other"
    host = secret.get("host", "")
    if brand == "other":
        path = str(secret.get("path") or default_path).split("?")[0]
        return f"other {host}{path}"[:200]
    return f"{brand} {host} ch{int(secret.get('channel') or 1)}"


def _fps(rate: str | None) -> float | None:
    if not rate or rate in ("0/0", "0"):
        return None
    num, _, den = rate.partition("/")
    try:
        return round(float(num) / float(den or 1), 2)
    except (ValueError, ZeroDivisionError):
        return None


def stream_info(url: str, timeout: float = 15) -> dict[str, Any]:
    """ffprobe the first video stream: {reachable, codec, width, height, fps}."""
    exe = shutil.which("ffprobe")
    if not exe:
        return {"reachable": False}
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv; the URL is built from validated fields
            [exe, "-v", "error", "-rtsp_transport", "tcp", "-select_streams", "v:0", "-show_entries",
             "stream=codec_name,width,height,avg_frame_rate,r_frame_rate", "-of", "json", url],
            check=True, capture_output=True, timeout=timeout,
        )  # fmt: skip
        streams = json.loads(out.stdout or b"{}").get("streams") or []
    except (subprocess.SubprocessError, OSError, ValueError):
        return {"reachable": False}
    if not streams:
        return {"reachable": False}
    s = streams[0]
    return {
        "reachable": True,
        "codec": s.get("codec_name"),
        "width": s.get("width"),
        "height": s.get("height"),
        "fps": _fps(s.get("avg_frame_rate")) or _fps(s.get("r_frame_rate")),
    }


def grab_frame(url: str, timeout: float = 10) -> bytes | None:
    """One JPEG from the stream, scaled to 320 px wide, for the channel list (AC-F8-6)."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return None
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv
            [exe, "-v", "error", "-rtsp_transport", "tcp", "-i", url, "-frames:v", "1", "-vf", "scale=320:-2",
             "-f", "image2", "-c:v", "mjpeg", "pipe:1"],
            check=True, capture_output=True, timeout=timeout,
        )  # fmt: skip
    except (subprocess.SubprocessError, OSError):
        return None
    return out.stdout or None


def verdict(info: dict[str, Any]) -> str:
    """ok | low_fps (warning) | unreachable | bad_codec | too_small, as the cloud computes it."""
    if not info.get("reachable"):
        return "unreachable"
    if str(info.get("codec") or "").lower() not in USABLE_CODECS:
        return "bad_codec"
    if int(info.get("width") or 0) < MIN_WIDTH or int(info.get("height") or 0) < MIN_HEIGHT:
        return "too_small"
    if float(info.get("fps") or 0) < MIN_FPS:
        return "low_fps"
    return "ok"
