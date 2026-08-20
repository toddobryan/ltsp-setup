"""Running a multi-reboot setup without losing your place.

Installing a desktop, a new kernel, and LTSP takes more than one reboot.  The
original shell version survived reboots by turning on autologin for the admin
user, adding a passwordless-sudo exception, and running the script from a
``@reboot`` cron job.  That works, but it leaves three security-relevant
changes lying around that have to be cleaned up afterwards, and it gives you
nowhere good to look when something fails.

This module does the same job with one systemd oneshot unit that runs as root
at boot, records progress in a JSON file, and disables itself when there is
nothing left to do.  Progress survives reboots, each stage is safe to re-run,
and ``journalctl -u ltsp-setup`` is the log.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ltsp_setup import templates
from ltsp_setup.config import Settings
from ltsp_setup.runner import Runner

logger = logging.getLogger("ltsp-setup")

STATE_DIR = Path("/var/lib/ltsp-setup")
STATE_FILE = STATE_DIR / "state.json"
UNIT_NAME = "ltsp-setup.service"
UNIT_PATH = Path("/etc/systemd/system") / UNIT_NAME


@dataclass(frozen=True)
class Context:
    """What every stage function is handed."""

    settings: Settings
    runner: Runner


StageFunc = Callable[[Context], None]


@dataclass(frozen=True)
class Stage:
    """One resumable step of a setup.

    Attributes:
        name: Stable identifier recorded in the state file.  Renaming one
            makes already-set-up machines re-run it, so don't.
        description: Shown to whoever is watching.
        func: The work.
        reboot_after: Whether to reboot once it succeeds.
    """

    name: str
    description: str
    func: StageFunc
    reboot_after: bool = False


@dataclass
class State:
    """Where a machine is in its setup."""

    role: str
    completed: list[str]

    @classmethod
    def load(cls, role: str) -> State:
        """Read the state file, or start fresh if there isn't one."""
        if not STATE_FILE.is_file():
            return cls(role=role, completed=[])
        raw = json.loads(STATE_FILE.read_text())
        recorded = str(raw.get("role", role))
        if recorded != role:
            raise RuntimeError(
                f"{STATE_FILE} says this machine is being set up as a "
                f"{recorded!r}, but you asked for {role!r}. Delete the file "
                f"if you really mean to start over."
            )
        return cls(role=recorded, completed=list(raw.get("completed", [])))

    def save(self, runner: Runner) -> None:
        """Persist the state file."""
        payload = json.dumps({"role": self.role, "completed": self.completed}, indent=2)
        runner.write(STATE_FILE, payload + "\n", mode=0o644, show=False)


class Plan:
    """An ordered list of stages for one role."""

    def __init__(self, role: str, stages: Sequence[Stage]) -> None:
        self.role = role
        self.stages = list(stages)
        names = [s.name for s in self.stages]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            raise ValueError(f"Duplicate stage names in {role} plan: {duplicates}")

    def stage(self, name: str) -> Stage:
        """Look up one stage by name."""
        for stage in self.stages:
            if stage.name == name:
                return stage
        known = ", ".join(s.name for s in self.stages)
        raise KeyError(f"No stage named {name!r} in the {self.role} plan. Try: {known}")

    def remaining(self, state: State) -> list[Stage]:
        """The stages that have not completed yet, in order."""
        return [s for s in self.stages if s.name not in state.completed]

    # ------------------------------------------------------------------ run

    def run(self, ctx: Context, *, reboot: bool = True) -> None:
        """Work through the remaining stages, rebooting where a stage asks.

        Args:
            ctx: Settings and runner.
            reboot: Set False to run every stage back-to-back without
                rebooting.  Useful for reviewing a whole plan in a dry run;
                not useful on a real machine, where the kernel and LTSP
                packages genuinely need the reboots.
        """
        state = (
            State.load(self.role) if not ctx.runner.dry_run else State(self.role, [])
        )
        todo = self.remaining(state)
        if not todo:
            ctx.runner.announce("Every stage is already complete; finishing up.")
            self.finish(ctx)
            return

        for stage in todo:
            ctx.runner.announce(f"[{self.role}] {stage.name} — {stage.description}")
            stage.func(ctx)
            state.completed.append(stage.name)
            state.save(ctx.runner)

            if stage.reboot_after and reboot:
                if self.remaining(state):
                    ctx.runner.announce(
                        "Rebooting; setup resumes automatically at boot."
                    )
                    ctx.runner.run(["systemctl", "reboot"])
                    return
                break

        self.finish(ctx)

    def finish(self, ctx: Context) -> None:
        """Turn off the boot-time unit now that the plan is done."""
        ctx.runner.announce("Setup complete. Disabling the boot-time unit.")
        disable_boot_unit(ctx.runner)


# ------------------------------------------------------------- systemd glue


def install_boot_unit(runner: Runner, role: str, config_file: Path | None) -> None:
    """Install and enable the unit that resumes setup after each reboot."""
    executable = _entry_point()
    command = f"{executable} {role} resume --no-debug"
    if config_file is not None:
        command += f" --config {config_file}"
    unit = templates.render(
        "ltsp-setup.service",
        {"DESCRIPTION": f"LTSP {role} setup (resumes across reboots)", "EXEC": command},
    )
    runner.write(UNIT_PATH, unit, mode=0o644)
    runner.run(["systemctl", "daemon-reload"])
    runner.run(["systemctl", "enable", UNIT_NAME])


def disable_boot_unit(runner: Runner) -> None:
    """Disable and remove the boot-time unit.  Safe to call twice."""
    runner.run(["systemctl", "disable", UNIT_NAME], check=False)
    runner.remove([UNIT_PATH])
    runner.run(["systemctl", "daemon-reload"], check=False)


def _entry_point() -> str:
    """Absolute path to the installed ``ltsp-setup`` command."""
    from shutil import which

    found = which("ltsp-setup")
    return found or "/usr/local/bin/ltsp-setup"
