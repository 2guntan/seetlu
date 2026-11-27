"""Installer-only LAN setup page (docs/05, docs/13): port 8080, LAN clients only, PIN = last 6 of the claim
token; closed once the kit is active, reopened 30 min by holding the box button (AC-F10-4).

Network status, ONVIF discovery, recorder login (stored on the box in secrets.json, chmod 600, never sent
to the cloud), brand preset + channel per slot (AC-F8-5), channel scan with thumbnails (AC-F8-6), stream
check reported to the cloud without credentials (AC-F8-7) and live snapshot. Zones are drawn in the web app.
"""

import html
import ipaddress
import json
import logging
import re
import secrets
import socket
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

from seetlu_agent import __version__, heartbeat, recorder
from seetlu_agent.edge_config import EdgeConfig

log = logging.getLogger(__name__)
LOCALES = Path(__file__).resolve().parent / "locales"
WS_DISCOVERY = ("239.255.255.250", 3702)
SLOTS = ("door", "counter")  # AC-F8-6: exactly one door and one counter channel


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


class RecorderLogin(BaseModel):
    brand: recorder.Brand = "other"
    host: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9.\-:]+$")
    port: int = Field(default=554, ge=1, le=65535)
    username: str = Field(default="", max_length=128)
    password: str = Field(default="", max_length=128)


class CameraCredentials(RecorderLogin):
    """One camera slot: a recorder channel (brand preset) or a raw RTSP path ("other")."""

    channel: int = Field(default=1, ge=1, le=64)
    path: str | None = Field(default=None, max_length=300, pattern=r"^/[A-Za-z0-9/_\-.?=&%]*$")

    def same_stream(self, other: "CameraCredentials") -> bool:
        if (self.host, self.brand) != (other.host, other.brand):
            return False
        return self.path == other.path if self.brand == "other" else self.channel == other.channel


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
    stream_check: Callable[[str], dict[str, Any]] = recorder.stream_info,
    grab: Callable[[str], bytes | None] = recorder.grab_frame,
    on_stream: Callable[[str, dict[str, Any]], None] = lambda _name, _report: None,
    is_open: Callable[[], bool] = lambda: True,
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
        if not is_open():
            raise HTTPException(403, "setup closed: hold the button on the box for 10 s (opens 30 min)")

    Guarded = Annotated[None, Depends(guard)]  # noqa: N806 - type alias

    def camera_names() -> list[str]:
        return list(dict.fromkeys([*SLOTS, *(c.name for c in get_config().cameras)]))

    def cloud_path(name: str) -> str:
        cam = next((c for c in get_config().cameras if c.name == name), None)
        return cam.rtsp_sub_path if cam else "/stream2"

    thumbs: dict[int, bytes] = {}

    def check_stream(name: str, creds: CameraCredentials) -> dict[str, Any]:
        """AC-F8-7: what the box sees, sent to the cloud with a source label and no credentials."""
        saved = creds.model_dump()
        info = stream_check(recorder.url_for(saved, cloud_path(name)))
        report = {"source": recorder.source_label(saved, cloud_path(name)), **info}
        on_stream(name, report)
        return report | {"verdict": recorder.verdict(info)}

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

    @app.put("/api/cameras/{name}")
    def save_camera(name: str, body: CameraCredentials, _: Guarded) -> dict[str, Any]:
        """AC-F8-5/6: one recorder channel per slot; the same channel cannot be both door and counter."""
        if name not in camera_names():
            raise HTTPException(404, "unknown camera")
        for other, saved in secrets_store.load()["cameras"].items():
            if (
                other != name
                and saved.get("host")
                and body.same_stream(CameraCredentials.model_validate(saved))
            ):
                raise HTTPException(409, f"this channel is already used by {other}")
        secrets_store.set_camera(name, body.model_dump())
        on_change()
        return check_stream(name, body)

    @app.post("/api/cameras/{name}/test")
    def test_camera(name: str, _: Guarded) -> dict[str, Any]:
        s = secrets_store.load()["cameras"].get(name)
        if name not in camera_names() or not s:
            raise HTTPException(404, "unknown camera or no credentials")
        return check_stream(name, CameraCredentials.model_validate(s))

    @app.post("/api/recorder/scan")
    def scan(body: RecorderLogin, _: Guarded) -> list[dict[str, Any]]:
        """AC-F8-6: one thumbnail per channel that answers, so the installer can pick door and counter."""
        if body.brand == "other":
            raise HTTPException(422, "pick the recorder brand to scan its channels")
        thumbs.clear()
        misses = 0
        for ch in range(1, recorder.MAX_CHANNELS + 1):
            jpg = grab(recorder.url_for(body.model_dump() | {"channel": ch}, ""))
            if jpg:
                thumbs[ch], misses = jpg, 0
            else:
                misses += 1
                if misses >= recorder.SCAN_STOP_AFTER_MISSES:
                    break
        return [{"channel": ch, "thumbnail": f"/api/recorder/channels/{ch}.jpg"} for ch in sorted(thumbs)]

    @app.get("/api/recorder/channels/{channel}.jpg")
    def thumbnail(channel: int, _: Guarded) -> Response:
        if channel not in thumbs:
            raise HTTPException(404, "scan the recorder first")
        return Response(thumbs[channel], media_type="image/jpeg")

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
        brands = "".join(f'<option value="{b}">{e(t["setup.brand." + b])}</option>' for b in recorder.BRANDS)
        login = f"""<select name="brand">{brands}</select>
<input name="host" placeholder="{e(t["setup.host"])}" required>
<input name="port" type="number" value="554" placeholder="{e(t["setup.port"])}">
<input name="username" placeholder="{e(t["setup.username"])}">
<input name="password" type="password" placeholder="{e(t["setup.password"])}">"""
        cams = "".join(
            f"""<section><h3>{e(t.get("setup.slot." + c["name"], c["name"]))} — {
                e(t["setup.camera.ready"] if c["ready"] else t["setup.camera.missing"])
            }</h3>
<form data-cam="{e(c["name"])}">{login}
<input name="channel" type="number" min="1" max="64" value="1" placeholder="{e(t["setup.channel"])}">
<input name="path" placeholder="{e(t["setup.path"])}">
<button>{e(t["setup.save"])}</button> <button type="button" data-test>{e(t["setup.test"])}</button></form>
<p><a href="/api/cameras/{e(c["name"])}/snapshot.jpg" target="_blank">{
                e(t["setup.snapshot"])
            }</a></p></section>"""
            for c in st["cameras"]
        )
        cloud = t["setup.cloud.ok"] if st["registered"] else t["setup.cloud.pending"]
        keys = ("setup.saved", "setup.discover.none", "setup.scan.none", "setup.taken")
        msgs = json.dumps(
            {k: v for k, v in t.items() if k.startswith(("setup.verdict.", "setup.slot."))}
            | {k: t[k] for k in keys}
        )
        return f"""<!doctype html><html lang="{e(lang)}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(t["setup.title"])}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:40rem;margin:1rem auto;padding:0 1rem}}
input,select{{display:block;margin:.3rem 0;padding:.5rem;width:100%}}button{{padding:.5rem 1rem;min-height:44px}}
#chans{{display:grid;grid-template-columns:repeat(auto-fill,minmax(9rem,1fr));gap:.5rem}}
#chans figure{{margin:0}}#chans img{{width:100%}}</style></head><body>
<h1>{e(t["setup.title"])}</h1>
<p>{e(t["setup.kit"])}: <b>{e(st["serial"])}</b> · v{e(st["agent_version"])}</p>
<p>{e(t["setup.network"])}: {e(st["network"] or t["setup.network.none"])} · {e(t["setup.cloud"])}: {e(cloud)}</p>
<h2>{e(t["setup.recorder"])}</h2><p><small>{e(t["setup.recorder.help"])}</small></p>
<button id="disc">{e(t["setup.discover"])}</button><pre id="found"></pre>
<form id="scan">{login}<button>{e(t["setup.scan"])}</button></form><div id="chans"></div>
<h2>{e(t["setup.cameras"])}</h2>{cams}
<p><small>{e(t["setup.zones"])}</small></p>
<script>const T={msgs};
const say=d=>alert(d.verdict?(T['setup.verdict.'+d.verdict]||d.verdict):(d.detail||T['setup.saved']));
document.getElementById('disc').onclick=async()=>{{const r=await fetch('/api/discover');const d=await r.json();
document.getElementById('found').textContent=d.length?d.map(x=>x.host+' '+x.xaddrs).join('\\n'):T['setup.discover.none']}};
const body=f=>{{const b=Object.fromEntries(new FormData(f));b.port=Number(b.port||554);
if(b.channel)b.channel=Number(b.channel);if(!b.path)delete b.path;return b}};
const save=async(cam,b)=>{{const r=await fetch('/api/cameras/'+cam,{{method:'PUT',
headers:{{'Content-Type':'application/json'}},body:JSON.stringify(b)}});
say(r.status===409?{{detail:T['setup.taken']}}:await r.json())}};
const sf=document.getElementById('scan');
sf.onsubmit=async ev=>{{ev.preventDefault();const b=body(sf);const r=await fetch('/api/recorder/scan',{{method:'POST',
headers:{{'Content-Type':'application/json'}},body:JSON.stringify(b)}});const d=r.ok?await r.json():[];
const box=document.getElementById('chans');box.textContent=d.length?'':T['setup.scan.none'];
for(const c of d){{const f=document.createElement('figure');const i=document.createElement('img');i.src=c.thumbnail;
const cap=document.createElement('figcaption');cap.textContent='#'+c.channel;f.append(i,cap);
for(const slot of ['door','counter']){{const bt=document.createElement('button');bt.type='button';
bt.textContent=T['setup.slot.'+slot];bt.onclick=()=>save(slot,{{...b,channel:c.channel}});f.append(bt)}}
box.append(f)}}}};
for(const f of document.querySelectorAll('form[data-cam]')){{const cam=f.dataset.cam;
f.onsubmit=async ev=>{{ev.preventDefault();await save(cam,body(f))}};
f.querySelector('[data-test]').onclick=async()=>{{const r=await fetch('/api/cameras/'+cam+'/test',{{method:'POST'}});
say(r.ok?await r.json():{{verdict:'unreachable'}})}}}}
</script></body></html>"""

    return app
