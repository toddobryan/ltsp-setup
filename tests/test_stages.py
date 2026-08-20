"""Plan bookkeeping and the resume logic."""

from __future__ import annotations

import pytest

from ltsp_setup.config import Settings
from ltsp_setup.runner import Runner
from ltsp_setup.stages import Context, Plan, Stage, StageFunc, State


def noop(ctx: Context) -> None:
    return None


def test_duplicate_stage_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        Plan("server", [Stage("a", "", noop), Stage("a", "", noop)])


def test_remaining_skips_completed_stages() -> None:
    plan = Plan("server", [Stage("a", "", noop), Stage("b", "", noop)])
    state = State(role="server", completed=["a"])
    assert [s.name for s in plan.remaining(state)] == ["b"]


def test_stage_lookup_reports_valid_names() -> None:
    plan = Plan("server", [Stage("a", "", noop)])
    with pytest.raises(KeyError, match="a"):
        plan.stage("nope")


def test_plan_runs_every_stage_when_reboots_are_disabled() -> None:
    calls: list[str] = []

    def record(name: str) -> StageFunc:
        def step(ctx: Context) -> None:
            calls.append(name)

        return step

    plan = Plan(
        "server",
        [
            Stage("one", "", record("one"), reboot_after=True),
            Stage("two", "", record("two")),
        ],
    )
    plan.run(Context(Settings(), Runner(dry_run=True)), reboot=False)
    assert calls == ["one", "two"]


def test_plan_stops_at_the_first_reboot_when_reboots_are_enabled() -> None:
    calls: list[str] = []

    def record(name: str) -> StageFunc:
        def step(ctx: Context) -> None:
            calls.append(name)

        return step

    plan = Plan(
        "server",
        [
            Stage("one", "", record("one"), reboot_after=True),
            Stage("two", "", record("two")),
        ],
    )
    plan.run(Context(Settings(), Runner(dry_run=True)), reboot=True)
    assert calls == ["one"]
