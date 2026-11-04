"""The monitor layout script, run for real against a fake sysfs and xrandr."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

import pytest

from ltsp_setup import templates
from ltsp_setup.config import Settings
from ltsp_setup.plans import CLIENT, SERVER
from ltsp_setup.runner import Runner
from ltsp_setup.stages import Context
from ltsp_setup.steps import client

LEFT = "a" * 40
RIGHT = "b" * 40


def _hash_of(edid: bytes, tmp_path: Path) -> str:
    path = tmp_path / "edid-to-hash"
    path.write_bytes(edid)
    out = subprocess.run(["sha1sum", str(path)], capture_output=True, text=True)
    return out.stdout.split()[0]


def _layout(
    tmp_path: Path,
    connected: dict[str, bytes],
    table: list[tuple[str, str]],
) -> list[str]:
    """Run the script and return the arguments it gave xrandr, if any."""
    script = tmp_path / "layout.sh"
    script.write_text(templates.read("ltsp-monitor-layout.sh"))
    drm = tmp_path / "sys/class/drm"
    for connector in ("DP-1", "DP-2", "DP-3", "HDMI-A-1"):
        port = drm / f"card0-{connector}"
        port.mkdir(parents=True)
        edid = connected.get(connector)
        status = "disconnected" if edid is None else "connected"
        (port / "status").write_text(f"{status}\n")
        (port / "edid").write_bytes(edid or b"")
    (drm / "version").write_text("not a connector\n")

    tsv = tmp_path / "table.tsv"
    tsv.write_text(
        "".join(f"{i}\t{l}\t{r}\n" for i, (l, r) in enumerate(table, start=1))
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "xrandr.log"
    stub = bin_dir / "xrandr"
    stub.write_text(f'#!/bin/sh\necho "$*" >> {calls}\n')
    stub.chmod(0o755)

    result = subprocess.run(
        ["sh", str(script)],
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "LTSP_MONITOR_SYS": str(tmp_path / "sys"),
            "LTSP_MONITOR_TABLE": str(tsv),
        },
    )
    assert result.returncode == 0
    return calls.read_text().splitlines() if calls.exists() else []


def _arrangement(left: str, right: str) -> list[str]:
    return [
        f"--output {left} --auto --primary --pos 0x0 "
        f"--output {right} --auto --right-of {left}"
    ]


def test_table_order_beats_connector_order(tmp_path: Path) -> None:
    left = _hash_of(b"left", tmp_path)
    right = _hash_of(b"right", tmp_path)
    calls = _layout(tmp_path, {"DP-1": b"right", "DP-2": b"left"}, [(left, right)])
    assert calls == _arrangement("DP-2", "DP-1")


def test_left_on_the_first_connector(tmp_path: Path) -> None:
    left = _hash_of(b"left", tmp_path)
    right = _hash_of(b"right", tmp_path)
    calls = _layout(tmp_path, {"DP-1": b"left", "DP-3": b"right"}, [(left, right)])
    assert calls == _arrangement("DP-1", "DP-3")


def test_replaced_left_monitor_is_placed_by_its_partner(tmp_path: Path) -> None:
    right = _hash_of(b"right", tmp_path)
    calls = _layout(tmp_path, {"DP-1": b"right", "DP-2": b"new"}, [(LEFT, right)])
    assert calls == _arrangement("DP-2", "DP-1")


def test_replaced_right_monitor_is_placed_by_its_partner(tmp_path: Path) -> None:
    left = _hash_of(b"left", tmp_path)
    calls = _layout(tmp_path, {"DP-1": b"new", "DP-2": b"left"}, [(left, RIGHT)])
    assert calls == _arrangement("DP-2", "DP-1")


def test_unknown_monitors_go_side_by_side_in_connector_order(tmp_path: Path) -> None:
    calls = _layout(tmp_path, {"DP-1": b"x", "DP-2": b"y"}, [(LEFT, RIGHT)])
    assert calls == _arrangement("DP-1", "DP-2")


def test_hdmi_uses_the_xrandr_name(tmp_path: Path) -> None:
    calls = _layout(tmp_path, {"DP-1": b"x", "HDMI-A-1": b"y"}, [])
    assert calls == _arrangement("DP-1", "HDMI-1")


def test_one_monitor_is_left_alone(tmp_path: Path) -> None:
    assert _layout(tmp_path, {"DP-3": b"x"}, [(LEFT, RIGHT)]) == []


def test_no_monitors_still_exits_cleanly(tmp_path: Path) -> None:
    assert _layout(tmp_path, {}, []) == []


def test_clear_script_removes_only_the_display_settings(tmp_path: Path) -> None:
    script = tmp_path / "clear.sh"
    script.write_text(templates.read("ltsp-clear-display-settings.sh"))
    channel = tmp_path / ".config/xfce4/xfconf/xfce-perchannel-xml"
    channel.mkdir(parents=True)
    (channel / "displays.xml").write_text("<channel/>")
    (channel / "xfce4-panel.xml").write_text("<channel/>")

    result = subprocess.run(
        ["sh", str(script)], env={**os.environ, "HOME": str(tmp_path)}
    )

    assert result.returncode == 0
    assert [p.name for p in channel.iterdir()] == ["xfce4-panel.xml"]


def test_clear_script_succeeds_with_nothing_to_remove(tmp_path: Path) -> None:
    script = tmp_path / "clear.sh"
    script.write_text(templates.read("ltsp-clear-display-settings.sh"))
    result = subprocess.run(
        ["sh", str(script)], env={**os.environ, "HOME": str(tmp_path)}
    )
    assert result.returncode == 0


def test_table_has_a_left_and_right_for_every_dual_monitor_desk() -> None:
    rows = [
        line.split("\t") for line in templates.read("lab-monitors.tsv").splitlines()
    ]
    assert [int(row[0]) for row in rows] == list(range(1, 25))
    hashes = [value for row in rows for value in row[1:]]
    assert all(len(value) == 40 for value in hashes)
    assert len(set(hashes)) == len(hashes)


def test_configure_monitors_installs_everything(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    client.configure_monitors(Context(Settings(), Runner(dry_run=True)))
    written = {
        r.message.split(":")[0].removeprefix("write ")
        for r in caplog.records
        if r.message.startswith("write ")
    }
    assert written == {
        "/usr/local/sbin/ltsp-monitor-layout.sh",
        "/usr/local/sbin/ltsp-clear-display-settings.sh",
        "/etc/ltsp-monitor-layout.tsv",
        "/etc/lightdm/lightdm.conf.d/60-ltsp-monitor-layout.conf",
        "/etc/xdg/autostart/ltsp-monitor-layout.desktop",
    }


def test_monitors_stage_is_client_only() -> None:
    assert "monitors" in [stage.name for stage in CLIENT.stages]
    assert "monitors" not in [stage.name for stage in SERVER.stages]
