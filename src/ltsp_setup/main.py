"""The ltsp-setup command line."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from ltsp_setup import config as config_module
from ltsp_setup import plans, stages
from ltsp_setup.lab.virt import Virt
from ltsp_setup.runner import Runner, StepFailed, console
from ltsp_setup.stages import Context
from ltsp_setup.steps import client, image, students

LOG_FILE = Path("/var/log/ltsp-setup.log")

app = typer.Typer(
    help="Set up an LTSP server and clients on a fresh Linux Mint install.",
    no_args_is_help=True,
)
server_app = typer.Typer(
    help="Set up this machine as the LTSP server.", no_args_is_help=True
)
client_app = typer.Typer(
    help="Set up this machine as the client template.", no_args_is_help=True
)
lab_app = typer.Typer(
    help="Manage the libvirt test VMs on your workstation.", no_args_is_help=True
)
image_app = typer.Typer(
    help="Manage the client-template VM and build the netboot image.",
    no_args_is_help=True,
)
student_app = typer.Typer(
    help="Manage student accounts and their desktop-setting defaults.",
    no_args_is_help=True,
)
app.add_typer(server_app, name="server")
app.add_typer(client_app, name="client")
app.add_typer(lab_app, name="lab")
app.add_typer(image_app, name="image")
app.add_typer(student_app, name="student")

DebugOption = Annotated[
    bool,
    typer.Option(
        "--debug/--no-debug",
        help="Show what would happen without doing it. On by default, "
        "so a real run has to say --no-debug.",
    ),
]
ConfigOption = Annotated[
    Optional[Path],
    typer.Option("--config", help="TOML file of setting overrides."),
]


def _setup_logging() -> None:
    """Log to /var/log if we can, and to stderr otherwise."""
    handlers: list[logging.Handler] = []
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(LOG_FILE))
    except OSError:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )


def _context(debug: bool, config_file: Path | None) -> Context:
    """Load settings and build the context every command needs."""
    _setup_logging()
    settings = config_module.load(config_file)
    return Context(settings=settings, runner=Runner(dry_run=debug))


def _require_root(debug: bool) -> None:
    """Refuse to make real changes unless we are root."""
    if not debug and os.geteuid() != 0:
        raise typer.BadParameter(
            "A real run changes system files, so it has to be run as root. "
            "Try: sudo ltsp-setup ... --no-debug"
        )


RebootOption = Annotated[
    bool,
    typer.Option(
        "--reboot/--no-reboot",
        help="--no-reboot runs every stage back to back instead of stopping "
        "at the first one that wants a reboot. Handy for reviewing a whole "
        "plan with --debug; not what you want on a real machine.",
    ),
]


def _run_plan(
    role: str,
    debug: bool,
    config_file: Path | None,
    *,
    install_unit: bool,
    reboot: bool = True,
) -> None:
    """Shared body of the server/client start and resume commands."""
    _require_root(debug)
    ctx = _context(debug, config_file)
    plan = plans.PLANS[role]
    if install_unit:
        stages.install_boot_unit(ctx.runner, role, config_file)
    plan.run(ctx, reboot=reboot)


# ---------------------------------------------------------------- server


@server_app.command("start")
def server_start(
    debug: DebugOption = True,
    config: ConfigOption = None,
    reboot: RebootOption = True,
) -> None:
    """Begin the server setup, installing the unit that resumes it after reboots."""
    _run_plan("server", debug, config, install_unit=True, reboot=reboot)


@server_app.command("resume")
def server_resume(debug: DebugOption = True, config: ConfigOption = None) -> None:
    """Carry on from wherever the last reboot left off. Run at boot by systemd."""
    _run_plan("server", debug, config, install_unit=False)


@server_app.command("stage")
def server_stage(
    name: str, debug: DebugOption = True, config: ConfigOption = None
) -> None:
    """Run one server stage on its own, without touching recorded progress."""
    _require_root(debug)
    ctx = _context(debug, config)
    plans.SERVER.stage(name).func(ctx)


# ---------------------------------------------------------------- client


@client_app.command("start")
def client_start(
    debug: DebugOption = True,
    config: ConfigOption = None,
    reboot: RebootOption = True,
) -> None:
    """Begin the client-template setup."""
    _run_plan("client", debug, config, install_unit=True, reboot=reboot)


@client_app.command("resume")
def client_resume(debug: DebugOption = True, config: ConfigOption = None) -> None:
    """Carry on from wherever the last reboot left off. Run at boot by systemd."""
    _run_plan("client", debug, config, install_unit=False)


@client_app.command("stage")
def client_stage(
    name: str, debug: DebugOption = True, config: ConfigOption = None
) -> None:
    """Run one client stage on its own, without touching recorded progress."""
    _require_root(debug)
    ctx = _context(debug, config)
    plans.CLIENT.stage(name).func(ctx)


@client_app.command("cleanup")
def client_cleanup(debug: DebugOption = True, config: ConfigOption = None) -> None:
    """Remove this project's own checkout and venv from the template.

    Not part of the plan -- run this by hand as the last step before
    shutting the template down, after using `client stage ...` to configure
    it. The template's whole disk becomes the client image, so anything
    left here ships to every real thin client.
    """
    _require_root(debug)
    client.cleanup_setup_tooling(_context(debug, config))


# ------------------------------------------------------------------- lab


def _virt(debug: bool, config_file: Path | None) -> Virt:
    ctx = _context(debug, config_file)
    return Virt(settings=ctx.settings, runner=ctx.runner)


@lab_app.command("build-golden")
def lab_build_golden(debug: DebugOption = True, config: ConfigOption = None) -> None:
    """Start the one-time interactive Mint install that becomes the golden image."""
    _virt(debug, config).build_golden()


@lab_app.command("create-server")
def lab_create_server(debug: DebugOption = True, config: ConfigOption = None) -> None:
    """Create (or recreate) the server VM as a clone of the golden image."""
    _virt(debug, config).create_server()


@lab_app.command("create-client")
def lab_create_client(debug: DebugOption = True, config: ConfigOption = None) -> None:
    """Create (or recreate) the client VM as a clone of the golden image."""
    _virt(debug, config).create_client()


@lab_app.command("create-client-template")
def lab_create_client_template(
    debug: DebugOption = True, config: ConfigOption = None
) -> None:
    """Create the client-template VM as a clone of the golden image.

    Lab-only convenience: production builds this with a fresh interactive
    install directly on the server. This overlay, on the workstation, is
    for testing steps/image.py's convert/build pieces without needing a
    full second Mint install inside the disk-constrained server VM.
    """
    _virt(debug, config).create_client_template()


@lab_app.command("reset")
def lab_reset(
    name: str, debug: DebugOption = True, config: ConfigOption = None
) -> None:
    """Throw one lab VM away and rebuild it clean from the golden image."""
    _virt(debug, config).reset(name)


@lab_app.command("netboot")
def lab_netboot(
    name: str,
    on: Annotated[
        bool, typer.Option("--on/--off", help="Boot from network first?")
    ] = True,
    debug: DebugOption = True,
    config: ConfigOption = None,
) -> None:
    """Flip a lab VM between netbooting and booting from its own disk."""
    _virt(debug, config).set_netboot(name, on)


@lab_app.command("network")
def lab_network(debug: DebugOption = True, config: ConfigOption = None) -> None:
    """Define and start the isolated LTSP network."""
    _virt(debug, config).ensure_networks()


@lab_app.command("status")
def lab_status(config: ConfigOption = None) -> None:
    """Show the lab VMs and networks."""
    console.print(_virt(False, config).status())


# ------------------------------------------------------------------ image


@image_app.command("create-template")
def image_create_template(
    debug: DebugOption = True, config: ConfigOption = None
) -> None:
    """Start the one-time interactive Mint install for the client template."""
    _require_root(debug)
    image.create_client_template(_context(debug, config))


@image_app.command("build")
def image_build(debug: DebugOption = True, config: ConfigOption = None) -> None:
    """Shut the client template down and rebuild the netboot image.

    Publishes the build but does not make it live -- run `image set-default`
    once it's been tested.
    """
    _require_root(debug)
    name = image.build_image(_context(debug, config))
    console.print(f"[bold green]Built:[/bold green] {name}")
    console.print(
        f"Not live yet. Test it, then run:  "
        f"sudo ltsp-setup image set-default {name} --no-debug"
    )


@image_app.command("set-default")
def image_set_default(
    name: str, debug: DebugOption = True, config: ConfigOption = None
) -> None:
    """Point DEFAULT_IMAGE at a published build and regenerate the boot menu.

    Also how to revert: pass the name of a previous, still-on-disk build
    (see `image list`) to fall back to it immediately, no rebuild needed.
    """
    _require_root(debug)
    image.set_default_image(_context(debug, config), name)


@image_app.command("list")
def image_list(config: ConfigOption = None) -> None:
    """Show every published build and which one is currently live."""
    ctx = _context(False, config)
    current = image.current_default_image(ctx)
    names = image.list_published_images(ctx)
    if not names:
        console.print(f"No images published yet under {image.PUBLISHED_IMAGE_DIR}.")
        return
    for name in names:
        marker = "[bold green]* live[/bold green]" if name == current else ""
        console.print(f"  {name}  {marker}")
    if current is not None and current not in names:
        console.print(
            f"[yellow]warning:[/yellow] DEFAULT_IMAGE is {current!r}, which "
            f"isn't among the published images above."
        )


@image_app.command("status")
def image_status(config: ConfigOption = None) -> None:
    """Show the client-template VM's current state."""
    console.print(image.status(_context(False, config)))


@image_app.command("import-raw")
def image_import_raw(
    source: str, debug: DebugOption = True, config: ConfigOption = None
) -> None:
    """Move an already-converted raw image into place and build the squashfs.

    Lab-only convenience for when the template lives elsewhere (e.g. a
    workstation overlay on the golden image) and its raw disk was copied
    here by hand -- see steps/image.py::convert_to_raw.
    """
    _require_root(debug)
    ctx = _context(debug, config)
    image.import_raw_image(ctx, Path(source))
    image.run_ltsp_image(ctx)


# -------------------------------------------------------------- student


@student_app.command("reset-defaults")
def student_reset_defaults(
    username: str, debug: DebugOption = True, config: ConfigOption = None
) -> None:
    """Delete a student's overrides for the panel/keyboard-layout settings.

    Destructive but narrow: only the files this project manages, not the
    rest of the account. Settings reseed from the system defaults baked
    into the client image on the student's next login.
    """
    _require_root(debug)
    students.reset_defaults(_context(debug, config), username)


def _report_applied(username: str, result: students.AppliedResult) -> None:
    for rel in result.applied:
        console.print(f"  [green]applied[/green] {username}: {rel}")
    for rel, reason in result.skipped:
        console.print(f"  [yellow]skipped[/yellow] {username}: {rel} ({reason})")


@student_app.command("apply-defaults")
def student_apply_defaults(
    username: str, debug: DebugOption = True, config: ConfigOption = None
) -> None:
    """Write current defaults into one account, patching only the
    properties that are missing or unchanged since we last shipped them.

    Compares each managed setting against a snapshot of the template as it
    stood the last time this ran: unchanged since then -> updated to the
    current default; changed, or no record at all -> left alone. Patches
    at the individual-property level, not whole-file, so a student
    changing one setting doesn't block an unrelated fix elsewhere in the
    same file.
    """
    _require_root(debug)
    result = students.apply_defaults(_context(debug, config), username)
    _report_applied(username, result)


@student_app.command("apply-defaults-all")
def student_apply_defaults_all(
    debug: DebugOption = True, config: ConfigOption = None
) -> None:
    """Run apply-defaults across every real student account."""
    _require_root(debug)
    ctx = _context(debug, config)
    for username, result in students.apply_defaults_all(ctx).items():
        _report_applied(username, result)


@student_app.command("remove-stale")
def student_remove_stale(
    debug: DebugOption = True, config: ConfigOption = None
) -> None:
    """Delete every real student account and its entire home directory.

    Destructive and NOT narrow -- this removes real content, not just
    settings. Every account is announced with its file count before it's
    touched, in both a dry run and a real one, so check that output
    carefully before re-running with --no-debug.
    """
    _require_root(debug)
    names = students.remove_all(_context(debug, config))
    if not names:
        console.print("No student accounts to remove.")
        return
    console.print(f"[bold]{len(names)} account(s):[/bold] {', '.join(names)}")


@student_app.command("clear-lock")
def student_clear_lock(
    username: str, debug: DebugOption = True, config: ConfigOption = None
) -> None:
    """Forcibly release a student's concurrent-login lock.

    Clients that log out cleanly release their own lock; a client that
    crashes or loses power leaves one that only clears itself after the
    heartbeat goes stale (~3 minutes, see data/ltsp-session-lock-check.sh).
    Use this instead of waiting.
    """
    _require_root(debug)
    existed = students.clear_session_lock(_context(debug, config), username)
    if existed:
        console.print(f"[green]Cleared[/green] the session lock for {username}.")
    else:
        console.print(f"{username} had no session lock to clear.")


# ---------------------------------------------------------------- config


@app.command("config")
def show_config(config: ConfigOption = None) -> None:
    """Print the settings in force, after any TOML overrides."""
    import dataclasses
    import json

    settings = config_module.load(config)
    found = config or config_module.find_config_file()
    console.print(f"[dim]config file: {found or 'none, using defaults'}[/dim]")
    console.print_json(json.dumps(dataclasses.asdict(settings), indent=2, default=str))


@app.command("plan")
def show_plan(role: str = "server") -> None:
    """List the stages for a role, in order."""
    plan = plans.PLANS.get(role)
    if plan is None:
        raise typer.BadParameter(f"role must be one of: {', '.join(plans.PLANS)}")
    for index, stage in enumerate(plan.stages, start=1):
        flag = "  [yellow](reboots)[/yellow]" if stage.reboot_after else ""
        console.print(f"{index}. [bold]{stage.name}[/bold] — {stage.description}{flag}")


def main() -> None:
    """Entry point that turns our own errors into tidy messages."""
    try:
        app()
    except StepFailed as failure:
        console.print(f"[bold red]error:[/bold red] {failure}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
