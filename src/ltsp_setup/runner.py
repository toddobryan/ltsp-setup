"""One place where every command, file write, and deletion happens.

Nothing else in this package is allowed to call :mod:`subprocess` or write to
disk directly.  That means ``--debug`` (the default) can show you exactly what
a real run would do without touching the machine, and every action lands in
the log in the same format.
"""

from __future__ import annotations

import grp
import logging
import os
import pwd
import shlex
import shutil
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from rich.console import Console
from rich.syntax import Syntax

logger = logging.getLogger("ltsp-setup")

console = Console(soft_wrap=True)


class StepFailed(RuntimeError):
    """A command that had to succeed did not."""


class Runner:
    """Executes actions, or describes them when ``dry_run`` is set.

    Args:
        dry_run: When True, print what would happen and change nothing.
    """

    def __init__(self, dry_run: bool = True) -> None:
        self.dry_run = dry_run

    # ---------------------------------------------------------------- output

    def announce(self, message: str) -> None:
        """Log a message and show it to whoever is watching."""
        logger.info(message)
        console.print(f"[bold cyan]::[/bold cyan] {message}")

    def _show(self, verb: str, detail: str) -> None:
        prefix = "[yellow]would[/yellow]" if self.dry_run else "[green]doing[/green]"
        console.print(f"  {prefix} [bold]{verb}[/bold] {detail}")

    # -------------------------------------------------------------- commands

    def run(
        self,
        argv: Sequence[str],
        *,
        check: bool = True,
        capture: bool = False,
        env: Mapping[str, str] | None = None,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run a command given as an argument list.

        Args:
            argv: The command and its arguments.  Never a shell string, so
                there is nothing to quote and nothing to inject.
            check: Raise :class:`StepFailed` on a non-zero exit.
            capture: Capture stdout/stderr instead of letting them through.
            env: Extra environment variables layered over the current ones.
            input_text: Text to feed the process on stdin.

        Returns:
            The completed process.  In a dry run this is a fake result with
            return code 0 and empty output.
        """
        argv = [str(a) for a in argv]
        pretty = shlex.join(argv)
        self._show("run", f"[white]{pretty}[/white]")
        logger.info("run: %s", pretty)

        if self.dry_run:
            return subprocess.CompletedProcess(argv, 0, "", "")

        full_env = {**os.environ, **(env or {})}
        result = subprocess.run(
            argv,
            text=True,
            env=full_env,
            input=input_text,
            capture_output=capture,
            check=False,
        )
        if check and result.returncode != 0:
            detail = (result.stderr or "").strip()
            raise StepFailed(
                f"Command failed with exit code {result.returncode}: {pretty}"
                + (f"\n{detail}" if detail else "")
            )
        return result

    def run_shell(self, script: str, *, check: bool = True) -> None:
        """Run a shell snippet, for the rare case a pipeline is genuinely needed.

        Prefer :meth:`run`.  This exists for things like piping a downloaded
        key through ``gpg --dearmor``.
        """
        self._show("shell", f"[white]{script}[/white]")
        logger.info("shell: %s", script)
        if self.dry_run:
            return
        result = subprocess.run(
            ["bash", "-o", "pipefail", "-c", script], text=True, check=False
        )
        if check and result.returncode != 0:
            raise StepFailed(
                f"Shell snippet failed with exit code {result.returncode}: {script}"
            )

    def which(self, program: str) -> bool:
        """True if ``program`` is on PATH.  Checked even during a dry run."""
        from shutil import which as _which

        return _which(program) is not None

    # ----------------------------------------------------------------- files

    def write(
        self, path: Path, content: str, *, mode: int = 0o644, show: bool = True
    ) -> None:
        """Write ``content`` to ``path``, creating parent directories."""
        self._show("write", f"{path} [dim](mode {mode:o})[/dim]")
        if show:
            syntax = Syntax(
                content.rstrip("\n"),
                _lexer_for(path),
                theme="ansi_dark",
                line_numbers=False,
                word_wrap=True,
            )
            console.print(syntax)
        logger.info("write %s:\n%s", path, content)
        if self.dry_run:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        path.chmod(mode)

    def read_text(self, path: Path) -> str:
        """Read a file's current contents.

        Always runs for real, even in a dry run -- this is inspection, not a
        change, the same reasoning as ``Libvirt.check_host_tools()`` running
        for real during a dry run (see ``lab/virt.py``): better to fail
        loudly here than produce a preview built on a guess.
        """
        return path.read_text()

    def exists(self, path: Path) -> bool:
        """True if ``path`` exists.

        Always checked for real, even in a dry run -- inspection, not a
        change, the same reasoning as :meth:`read_text`.
        """
        return path.exists()

    def count_files(self, path: Path) -> int:
        """How many regular files live under ``path``, recursively.

        For sanity-checking a deletion before it happens -- e.g. "this
        account I'm about to wipe holds 0 files" versus "holds 4,000" is the
        difference between an abandoned account and one a student is still
        using. Always checked for real, even in a dry run -- inspection,
        not a change, the same reasoning as :meth:`read_text`. Zero if
        ``path`` doesn't exist.
        """
        if not path.exists():
            return 0
        return sum(1 for p in path.rglob("*") if p.is_file())

    def list_dirs(self, path: Path) -> list[Path]:
        """Every immediate subdirectory of ``path``.

        Always checked for real, even in a dry run -- inspection, not a
        change, the same reasoning as :meth:`read_text`. Empty if ``path``
        doesn't exist.
        """
        if not path.exists():
            return []
        return sorted(p for p in path.iterdir() if p.is_dir())

    def passwd_entries(self) -> list[tuple[str, int]]:
        """Every local account as ``(username, uid)``.

        Always checked for real, even in a dry run -- inspection, not a
        change, the same reasoning as :meth:`read_text`.
        """
        return [(entry.pw_name, entry.pw_uid) for entry in pwd.getpwall()]

    def append_line(self, path: Path, line: str) -> None:
        """Append ``line`` to ``path`` unless it is already there."""
        self._show("append", f"{line!r} -> {path}")
        if self.dry_run:
            return
        existing = path.read_text() if path.exists() else ""
        if line in existing.splitlines():
            logger.info("%s already contains %r; nothing to do", path, line)
            return
        with open(path, "a") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(line + "\n")

    def mkdir(self, path: Path, *, mode: int = 0o755) -> None:
        """Create a directory and any missing parents."""
        self._show("mkdir", str(path))
        if self.dry_run:
            return
        path.mkdir(parents=True, exist_ok=True, mode=mode)

    def remove(self, paths: Iterable[Path]) -> None:
        """Delete files.  Directories and missing paths are skipped."""
        for path in paths:
            if not path.exists() and not path.is_symlink():
                continue
            if path.is_dir() and not path.is_symlink():
                logger.warning("refusing to remove directory %s", path)
                continue
            self._show("remove", str(path))
            if not self.dry_run:
                path.unlink()

    def remove_tree(self, path: Path) -> None:
        """Recursively delete a directory.  A no-op if it doesn't exist."""
        if not path.exists() and not path.is_symlink():
            return
        self._show("remove", f"{path} (recursively)")
        logger.info("remove tree: %s", path)
        if not self.dry_run:
            shutil.rmtree(path)

    def chown(self, path: Path, user: str, group: str | None = None) -> None:
        """Change ownership of a path."""
        group = group or user
        self._show("chown", f"{user}:{group} {path}")
        if self.dry_run:
            return
        uid = pwd.getpwnam(user).pw_uid
        gid = grp.getgrnam(group).gr_gid
        os.chown(path, uid, gid)


def _lexer_for(path: Path) -> str:
    """Guess a syntax-highlighting lexer from a file name."""
    name = path.name
    suffix = path.suffix
    if suffix in (".yaml", ".yml"):
        return "yaml"
    if suffix in (".sh", ".bash"):
        return "bash"
    if suffix == ".json":
        return "json"
    if suffix in (".toml",):
        return "toml"
    if suffix in (".service", ".conf", ".sources", ".list") or name == "override.conf":
        return "ini"
    return "text"
