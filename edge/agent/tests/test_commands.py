"""Cloud commands (docs/05): clip (AC-F5-2, AC-F5-4), snapshot, count check (AC-F8-3), update (AC-F10-3)."""

import shutil
import subprocess
from pathlib import Path

import pytest

from fake_frigate.publisher import STATE
from seetlu_agent.commands import CommandRunner, clip_argv, key_from_upload_url, run_cmd
from seetlu_agent.edge_config import EdgeConfig
from seetlu_agent.engine import Engine
from seetlu_agent.outbox import Outbox
from tests.fakes import FakeCloud, copy_runner, fake_frigate

UPLOAD = "http://api.test/bucket/shops/s1/clips/c1.mp4?X-Amz-Signature=abc"


def runner(tmp_path: Path, calls: list[list[str]]) -> tuple[CommandRunner, FakeCloud, Engine]:
    cloud = FakeCloud(config={"config_version": 1})
    engine = Engine(EdgeConfig(), "K")
    engine.last_ts = 1_800_000_000.0
    r = CommandRunner(engine, Outbox(":memory:"), fake_frigate(), uploads=cloud.client(),
                      run=copy_runner(calls), compose_file="/c.yml", host_dir=tmp_path / "host")  # fmt: skip
    return r, cloud, engine


def test_clip_is_fetched_transcoded_and_uploaded_AC_F5_2(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    r, cloud, _ = runner(tmp_path, calls)
    cmd = {"id": "c1", "type": "clip", "upload_url": UPLOAD,
           "params": {"camera": "counter", "start": "2027-01-15T08:00:00Z", "end": "2027-01-15T08:01:00Z"}}  # fmt: skip
    status, result = r.execute(cmd) or ("", {})
    assert status == "done"
    assert result["object_key"] == "shops/s1/clips/c1.mp4"
    assert result["duration_s"] == 20.0  # capped at 20 s
    assert result["size_bytes"] == len(cloud.uploads["/bucket/shops/s1/clips/c1.mp4"]) > 0
    argv = calls[0]
    for flag in ("libx264", "veryfast", "28", "-an", "scale=-2:480"):
        assert flag in argv
    assert argv[argv.index("-t") + 1] == "20.000"
    assert r.execute(cmd) is None  # idempotent: already executed


def test_clip_older_than_edge_buffer_is_unavailable_AC_F5_4(tmp_path: Path) -> None:
    r, _, _ = runner(tmp_path, [])
    STATE.sim_now = 1_800_000_000.0
    cmd = {"id": "c2", "type": "clip", "upload_url": UPLOAD,
           "params": {"camera": "counter", "start": 1_800_000_000 - 8 * 86400, "end": 1_800_000_000 - 8 * 86400 + 10}}  # fmt: skip
    assert r.execute(cmd) == ("unavailable", {"reason": "not in the edge buffer"})


def test_snapshot_resized_and_uploaded(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    r, cloud, _ = runner(tmp_path, calls)
    url = "http://api.test/bucket/shops/s1/snapshots/c3.jpg?sig=1"
    status, result = r.execute({"id": "c3", "type": "snapshot", "params": {}, "upload_url": url}) or ("", {})
    assert status == "done" and result["object_key"] == "shops/s1/snapshots/c3.jpg"
    assert "scale=960:-2" in calls[0] and "/bucket/shops/s1/snapshots/c3.jpg" in cloud.uploads


def test_upload_without_url_fails_cleanly(tmp_path: Path) -> None:
    r, _, _ = runner(tmp_path, [])
    status, result = r.execute({"id": "c4", "type": "snapshot", "params": {}}) or ("", {})
    assert status == "failed" and result["error"] == "ValueError"


def test_count_check_counts_door_entries_AC_F8_3(tmp_path: Path) -> None:
    r, _, engine = runner(tmp_path, [])
    t0 = engine.last_ts or 0.0
    assert r.execute({"id": "s", "type": "count_check_start", "params": {}}) == ("done", {"started_at": t0})
    for i in range(3):
        tid = f"t{i}"
        for kind, ts, zones in (("new", 1, ["door_out"]), ("update", 2, ["door_in"]), ("end", 3, [])):
            after = {"id": tid, "camera": "door", "label": "person", "score": 0.8, "frame_time": t0 + 10 * i + ts,
                     "current_zones": zones}  # fmt: skip
            engine._on_event({"type": kind, "after": after}, t0 + 10 * i + ts)
    assert r.execute({"id": "e", "type": "count_check_stop", "params": {}}) == ("done", {"agent_count": 3})


def test_update_agent_pulls_and_recreates_the_container_AC_F10_3(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    r, _, _ = runner(tmp_path, calls)
    assert r.execute({"id": "u", "type": "update_agent", "params": {"version": "0.2.0"}}) == (
        "done", {"requested_version": "0.2.0"})  # fmt: skip
    assert calls[0][-3:] == ["/c.yml", "pull", "seetlu-agent"]
    assert calls[1][-4:] == ["up", "-d", "--no-deps", "seetlu-agent"]


def test_reboot_asks_the_host_helper(tmp_path: Path) -> None:
    r, _, _ = runner(tmp_path, [])
    assert r.execute({"id": "r", "type": "reboot", "params": {}}) == ("done", {"requested": True})
    assert (tmp_path / "host" / "reboot-requested").exists()


def test_upload_key_parsing() -> None:
    assert (
        key_from_upload_url("http://minio:9000/seetlu-clips/shops/a/clips/b.mp4?x=1") == "shops/a/clips/b.mp4"
    )


def _ffmpeg_works() -> bool:
    exe = shutil.which("ffmpeg")
    if not exe:
        return False
    return subprocess.run([exe, "-version"], capture_output=True, check=False).returncode == 0  # noqa: S603


@pytest.mark.skipif(not _ffmpeg_works(), reason="needs a working ffmpeg (present in the agent image)")
def test_real_ffmpeg_transcode(tmp_path: Path) -> None:
    src = Path(__file__).resolve().parents[2] / "fake-frigate" / "fake_frigate" / "media" / "sample.mp4"
    dst = tmp_path / "out.mp4"
    run_cmd(clip_argv(src, dst, 5))
    assert dst.stat().st_size > 0
