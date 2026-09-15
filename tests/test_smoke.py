"""The netboot smoke test: does a freshly published image actually boot?

Everything here is parsing and polling logic, which is the part that can be
tested without a lab. The part that can't -- whether a real thin client comes
up -- is exactly what the VM is for.
"""

from __future__ import annotations

import dataclasses
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

import pytest

from ltsp_setup.config import Settings
from ltsp_setup.runner import Runner, StepFailed
from ltsp_setup.stages import Context
from ltsp_setup.steps import smoke

# Two leases for one MAC is the normal case, not a corrupt file: iPXE and the
# booted kernel send different DHCP client-ids, so dnsmasq issues each its own
# address. Both have to be watched, since which one the running system ends up
# on isn't knowable from the server.
LEASES = """\
1789509708 9c:7b:ef:b1:59:28 192.168.67.83 200-342875-21 01:9c:7b:ef:b1:59:28
1789518860 b0:0c:d1:5d:e6:03 192.168.67.62 * ff:d1:5d:e6:03:00:03:00:01:b0:0c
1789518825 b0:0c:d1:5d:e6:03 192.168.67.61 * 01:b0:0c:d1:5d:e6:03
"""


def _ctx(tmp_path: Path, leases: str = LEASES, *, dry_run: bool = False) -> Context:
    lease_file = tmp_path / "dnsmasq.leases"
    lease_file.write_text(leases)
    settings = dataclasses.replace(
        Settings(),
        smoke_test=dataclasses.replace(Settings().smoke_test, lease_file=lease_file),
    )
    return Context(settings, Runner(dry_run=dry_run))


class TestLeasesFor:
    def test_finds_every_address_for_one_mac(self, tmp_path: Path) -> None:
        leases = smoke.leases_for(_ctx(tmp_path), "b0:0c:d1:5d:e6:03")
        assert {lease.address for lease in leases} == {
            "192.168.67.62",
            "192.168.67.61",
        }
        assert max(lease.expires_at for lease in leases) == 1789518860

    def test_ignores_other_macs(self, tmp_path: Path) -> None:
        leases = smoke.leases_for(_ctx(tmp_path), "9c:7b:ef:b1:59:28")
        assert [lease.address for lease in leases] == ["192.168.67.83"]

    def test_matches_case_insensitively(self, tmp_path: Path) -> None:
        """virsh prints MACs lowercase and so does dnsmasq, but neither
        promises to, and a case mismatch here would look like a client that
        never asked for an address."""
        assert smoke.leases_for(_ctx(tmp_path), "B0:0C:D1:5D:E6:03")

    def test_skips_ipv6_leases(self, tmp_path: Path) -> None:
        leases = "1789518860 b0:0c:d1:5d:e6:03 fe80::1 * 01:b0:0c\n"
        assert smoke.leases_for(_ctx(tmp_path, leases), "b0:0c:d1:5d:e6:03") == []

    def test_skips_unparseable_rows(self, tmp_path: Path) -> None:
        leases = "duid 00:01:00:01\n1789518860 b0:0c:d1:5d:e6:03 192.168.67.62 * x\n"
        found = smoke.leases_for(_ctx(tmp_path, leases), "b0:0c:d1:5d:e6:03")
        assert [lease.address for lease in found] == ["192.168.67.62"]

    def test_empty_when_there_is_no_lease_file(self, tmp_path: Path) -> None:
        ctx = _ctx(tmp_path)
        ctx.settings.smoke_test.lease_file.unlink()
        assert smoke.leases_for(ctx, "b0:0c:d1:5d:e6:03") == []


SS_OUTPUT = """\
0      0       192.168.67.1:789 192.168.67.107:37598
0      0       192.168.67.1:789 192.168.67.210:56554
0      0       192.168.67.1:789 192.168.67.107:50130
"""


def _with_ss(ctx: Context, monkeypatch: pytest.MonkeyPatch, output: str) -> None:
    def fake_run(
        argv: Sequence[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, output, "")

    monkeypatch.setattr(ctx.runner, "run", fake_run)


class TestAgentPeers:
    def test_returns_address_and_port_for_matching_clients(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = _ctx(tmp_path)
        _with_ss(ctx, monkeypatch, SS_OUTPUT)
        assert smoke.agent_peers(ctx, {"192.168.67.107"}) == {
            "192.168.67.107:37598",
            "192.168.67.107:50130",
        }

    def test_ignores_every_other_client_in_the_lab(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other thin clients are connected to epoptes all day. Only the
        test client's own address is evidence about the new image."""
        ctx = _ctx(tmp_path)
        _with_ss(ctx, monkeypatch, SS_OUTPUT)
        assert smoke.agent_peers(ctx, {"192.168.67.9"}) == set()

    def test_does_not_shell_out_at_all_for_no_addresses(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = _ctx(tmp_path)
        monkeypatch.setattr(ctx.runner, "run", _must_not_run)
        assert smoke.agent_peers(ctx, set()) == set()

    def test_asks_ss_only_about_the_epoptes_port(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = _ctx(tmp_path)
        calls: list[list[str]] = []

        def record(
            argv: Sequence[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            calls.append([str(a) for a in argv])
            return subprocess.CompletedProcess([], 0, "", "")

        monkeypatch.setattr(ctx.runner, "run", record)
        smoke.agent_peers(ctx, {"192.168.67.107"})

        assert calls == [
            ["ss", "-H", "-tn", "state", "established", "sport", "=", ":789"]
        ]


def _must_not_run(*args: object, **kwargs: object) -> None:
    raise AssertionError("nothing should have been executed")


class TestWaitForAgent:
    """A connection left over from a previous run is not evidence about this
    one -- the kernel keeps showing a powered-off client's socket as
    ESTABLISHED for a while, and trusting it would pass a bad image.
    """

    def test_a_stale_connection_alone_does_not_pass(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = _ctx(tmp_path)
        _with_ss(ctx, monkeypatch, SS_OUTPUT)
        monkeypatch.setattr(time, "sleep", lambda _s: None)

        with pytest.raises(StepFailed, match="never connected to epoptes"):
            smoke._wait_for_agent(
                ctx,
                {"192.168.67.107"},
                {"192.168.67.107:37598", "192.168.67.107:50130"},
                time.monotonic() + 0.01,
            )

    def test_a_new_connection_passes_and_reports_the_address(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = _ctx(tmp_path)
        _with_ss(ctx, monkeypatch, SS_OUTPUT)
        address = smoke._wait_for_agent(
            ctx,
            {"192.168.67.107"},
            {"192.168.67.107:37598"},
            time.monotonic() + 30,
        )
        assert address == "192.168.67.107"


class TestWaitForLease:
    def test_a_leftover_lease_alone_does_not_pass(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """dnsmasq keeps leases for twelve hours, so the test client almost
        always already has one. Only a *newer* expiry means it just booted.
        """
        ctx = _ctx(tmp_path)
        monkeypatch.setattr(time, "sleep", lambda _s: None)

        with pytest.raises(StepFailed, match="never asked for a DHCP lease"):
            smoke._wait_for_lease(
                ctx,
                "b0:0c:d1:5d:e6:03",
                1789518860,
                time.monotonic() + 0.01,
            )

    def test_a_renewed_lease_passes_with_every_address(self, tmp_path: Path) -> None:
        ctx = _ctx(tmp_path)
        addresses = smoke._wait_for_lease(
            ctx, "b0:0c:d1:5d:e6:03", 1789518000, time.monotonic() + 30
        )
        assert addresses == {"192.168.67.62", "192.168.67.61"}


def test_dry_run_boots_nothing_and_polls_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx(tmp_path, dry_run=True)
    monkeypatch.setattr(ctx.runner, "run", _must_not_run)
    assert smoke.smoke_test_client(ctx) == smoke.DRY_RUN_ADDRESS
