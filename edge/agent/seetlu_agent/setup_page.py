"""Installer-only LAN setup page (docs/05): port 8080, LAN clients only, PIN = last 6 of the claim token.

Network status, ONVIF camera discovery, RTSP credentials (stored on the box in secrets.json, chmod 600,
never sent to the cloud), stream test and live snapshot. Zones are drawn in the web app (F8).
"""

import html
import ipaddress
import json
import logging
import re
import secrets
import shutil
import socket
import subprocess
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

from seetlu_agent import __version__, heartbeat
from seetlu_agent.edge_config import EdgeConfig

log = logging.getLogger(__name__)
LOCALES = Path(__file__).resolve().parent / "locales"
WS_DISCOVERY = ("239.255.255.250", 3702)


def load_locale(lang: str) -> dict[str, str]:
    fr: dict[str, str] = json.loads((LOCALES / "fr.json").read_text())
    path = LOCALES / f"{lang}.json"
    if lang != "fr" and path.exists():
        other: dict[str, str] = json.loads(path.read_text())
        return fr | other
    return fr  # French is the default (CLAUDE.md)


class SecretsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"cameras": {}}
        data: dict[str, Any] = json.loads(self.path.read_text())
        data.setdefault("cameras", {})
        return data

    def set_camera(self, name: str, value: dict[str, Any]) -> None:
        data = self.load()
        data["cameras"][name] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.touch(mode=0o600)
        tmp.chmod(0o600)
        tmp.write_text(json.dumps(data))
        tmp.replace(self.path)


class CameraCredentials(BaseModel):
    host: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9.\-:]+$")
    port: int = Field(default=554, ge=1, le=65535)
    username: str = Field(default="", max_length=128)
    password: str = Field(default="", max_length=128)


def ws_discover(timeout: float = 3.0) -> list[dict[str, str]]:
    """ONVIF WS-Discovery probe for network video transmitters on the LAN."""
    probe = f"""<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
<e:Header><w:MessageID>uuid:{uuid.uuid4()}</w:MessageID><w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
<w:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action></e:Header>
<e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body></e:Envelope>"""
    found: dict[str, dict[str, str]] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(timeout)
    try:
        sock.sendto(probe.encode(), WS_DISCOVERY)
        while True:
            data, (addr, _port) = sock.recvfrom(65535)
            xaddrs = re.findall(r"<[^>]*XAddrs>([^<]+)</", data.decode(errors="replace"))
            found[addr] = {"host": addr, "xaddrs": xaddrs[0].strip() if xaddrs else ""}
    except (TimeoutError, OSError):
        pass
    finally:
        sock.close()
    return sorted(found.values(), key=lambda d: d["host"])


def ffprobe_ok(url: str) -> bool:
    exe = shutil.which("ffprobe")
    if not exe:
        return False
    try:
        subprocess.run(  # noqa: S603 - fixed argv, url built from validated fields
            [exe, "-v", "error", "-rtsp_transport", "tcp", "-i", url, "-show_entries", "stream=codec_type"],
            check=True, capture_output=True, timeout=15,
        )  # fmt: skip
    except (subprocess.SubprocessError, OSError):
        return False
    return True


def is_lan(host: str | None) -> bool:
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host == "testclient"  # FastAPI TestClient
    return ip.is_private or ip.is_loopback or ip.is_link_local


def create_app(
    pin: str,
    serial: str,
    secrets_store: SecretsStore,
    get_config: Callable[[], EdgeConfig],
    registered: Callable[[], bool],
    on_change: Callable[[], None],
    frigate: httpx.Client,
    discover: Callable[[], list[dict[str, str]]] = ws_discover,
    probe: Callable[[str], bool] = ffprobe_ok,
) -> FastAPI:
    app = FastAPI(title="seetlu-agent setup", docs_url=None, redoc_url=None, openapi_url=None)
    basic = HTTPBasic(realm="seetlu-setup")

    def guard(request: Request, creds: Annotated[HTTPBasicCredentials, Depends(basic)]) -> None:
        client = request.client.host if request.client else None
        if not is_lan(client):
            log.warning("setup page: refused client %s (not on the LAN)", client)
            raise HTTPException(403, "LAN only")
        if not pin or not secrets.compare_digest(creds.password.encode(), pin.encode()):
            raise HTTPException(401, "wrong PIN", headers={"WWW-Authenticate": 'Basic realm="seetlu-setup"'})

    Guarded = Annotated[None, Depends(guard)]  # noqa: N806 - type alias

    def camera_names() -> list[str]:
        return [c.name for c in get_config().cameras]

    def status() -> dict[str, Any]:
        saved = secrets_store.load()["cameras"]
        return {
            "serial": serial,
            "agent_version": __version__,
            "registered": registered(),
            "network": heartbeat.network(),
            "cameras": [{"name": n, "ready": bool(saved.get(n, {}).get("host"))} for n in camera_names()],
        }

    @app.get("/api/status")
    def api_status(_: Guarded) -> dict[str, Any]:
        return status()

    @app.get("/api/discover")
    def api_discover(_: Guarded) -> list[dict[str, str]]:
        return discover()

    @app.put("/api/cameras/{name}", status_code=204, response_class=Response)
    def save_camera(name: str, body: CameraCredentials, _: Guarded) -> Response:
        if name not in camera_names():
            raise HTTPException(404, "unknown camera")
        secrets_store.set_camera(name, body.model_dump())
        on_change()
        return Response(status_code=204)

    @app.post("/api/cameras/{name}/test")
    def test_camera(name: str, _: Guarded) -> dict[str, bool]:
        cam = next((c for c in get_config().cameras if c.name == name), None)
        s = secrets_store.load()["cameras"].get(name)
        if cam is None or not s:
            raise HTTPException(404, "unknown camera or no credentials")
        creds = CameraCredentials.model_validate(s)
        auth = f"{creds.username}:{creds.password}@" if creds.username else ""
        return {"ok": probe(f"rtsp://{auth}{creds.host}:{creds.port}{cam.rtsp_sub_path}")}

    @app.get("/api/cameras/{name}/snapshot.jpg")
    def snapshot(name: str, _: Guarded) -> Response:
        if name not in camera_names():
            raise HTTPException(404, "unknown camera")
        r = frigate.get(f"/api/{name}/latest.jpg", timeout=10)
        if r.status_code != 200:
            raise HTTPException(502, "no picture from Frigate")
        return Response(r.content, media_type="image/jpeg")

    @app.get("/", response_class=HTMLResponse)
    def page(_: Guarded, lang: str = "fr") -> str:
        t = load_locale(lang if lang in ("fr", "en", "wo") else "fr")
        st = status()
        e = html.escape
        cams = "".join(
            f"""<section><h3>{e(c["name"])} — {e(t["setup.camera.ready"] if c["ready"] else t["setup.camera.missing"])}</h3>
<form data-cam="{e(c["name"])}"><input name="host" placeholder="{e(t["setup.host"])}" required>
<input name="port" type="number" value="554" placeholder="{e(t["setup.port"])}">
<input name="username" placeholder="{e(t["setup.username"])}"><input name="password" type="password" placeholder="{e(t["setup.password"])}">
<button>{e(t["setup.save"])}</button> <button type="button" data-test>{e(t["setup.test"])}</button></form>
<p><a href="/api/cameras/{e(c["name"])}/snapshot.jpg" target="_blank">{e(t["setup.snapshot"])}</a></p></section>"""
            for c in st["cameras"]
        )
        cloud = t["setup.cloud.ok"] if st["registered"] else t["setup.cloud.pending"]
        msgs = json.dumps({k: t[k] for k in ("setup.saved", "setup.test.ok", "setup.test.fail",
                                             "setup.discover.none")})  # fmt: skip
        return f"""<!doctype html><html lang="{e(lang)}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(t["setup.title"])}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:40rem;margin:1rem auto;padding:0 1rem}}
input{{display:block;margin:.3rem 0;padding:.5rem;width:100%}}button{{padding:.5rem 1rem}}</style></head><body>
<h1>{e(t["setup.title"])}</h1>
<p>{e(t["setup.kit"])}: <b>{e(st["serial"])}</b> · v{e(st["agent_version"])}</p>
<p>{e(t["setup.network"])}: {e(st["network"] or t["setup.network.none"])} · {e(t["setup.cloud"])}: {e(cloud)}</p>
<h2>{e(t["setup.cameras"])}</h2><button id="disc">{e(t["setup.discover"])}</button><pre id="found"></pre>{cams}
<p><small>{e(t["setup.zones"])}</small></p>
<script>const T={msgs};
document.getElementById('disc').onclick=async()=>{{const r=await fetch('/api/discover');const d=await r.json();
document.getElementById('found').textContent=d.length?d.map(x=>x.host+' '+x.xaddrs).join('\\n'):T['setup.discover.none']}};
for(const f of document.querySelectorAll('form[data-cam]')){{const cam=f.dataset.cam;
f.onsubmit=async ev=>{{ev.preventDefault();const b=Object.fromEntries(new FormData(f));b.port=Number(b.port||554);
const r=await fetch('/api/cameras/'+cam,{{method:'PUT',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(b)}});
alert(r.ok?T['setup.saved']:r.status)}};
f.querySelector('[data-test]').onclick=async()=>{{const r=await fetch('/api/cameras/'+cam+'/test',{{method:'POST'}});
const d=r.ok?await r.json():{{ok:false}};alert(d.ok?T['setup.test.ok']:T['setup.test.fail'])}}}}
</script></body></html>"""

    return app
