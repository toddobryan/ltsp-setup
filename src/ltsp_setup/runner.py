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
import stat
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Literal

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

    def write_secret(self, path: Path, content: str, *, mode: int = 0o600) -> None:
        """Write ``content`` to ``path`` without ever logging or printing it.

        For real secrets (student passwords) -- ``write()``'s
        ``logger.info("write %s:\\n%s", path, content)`` call is
        unconditional regardless of its own ``show`` flag, so it isn't safe
        for content that shouldn't end up sitting in ``/var/log`` forever.
        Only the path is announced/logged here. Creates parent directories
        at ``0o700`` rather than ``write()``'s default, since a directory
        holding secret files shouldn't be group/world-readable either.
        """
        self._show("write", f"{path} [dim](mode {mode:o}, content withheld)[/dim]")
        logger.info("write %s: <content withheld>", path)
        if self.dry_run:
            return
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(content)
        path.chmod(mode)

    def copy(self, src: Path, dest: Path, *, mode: int = 0o644) -> None:
        """Copy a file, creating parent directories.

        Unlike :meth:`write`, the content never reaches the console or the
        log.  These are arbitrary teacher-supplied files -- a .odt, a PDF,
        an image -- and a dry run that dumped a few hundred kilobytes of
        zip container into the terminal would be worse than useless.  Only
        the paths are announced.
        """
        self._show("copy", f"{src} -> {dest} [dim](mode {mode:o})[/dim]")
        logger.info("copy %s -> %s", src, dest)
        if self.dry_run:
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        dest.chmod(mode)

    def copy_nofollow(
        self,
        src_root: Path,
        src_rel: Path,
        dest_root: Path,
        dest_rel: Path,
        *,
        mode: int = 0o644,
    ) -> None:
        """Copy a file when a student controls the folders at either end.

        :meth:`copy` follows symlinks, which is fine for a teacher's own
        handouts and dangerous for root working inside a student's home: a
        submission that is really a symlink to ``/etc/shadow`` would be
        copied somewhere the student can read it, a folder on the way to it
        could lead into a classmate's home, and a destination folder swapped
        for a symlink would have root writing anywhere on the disk. Checking
        first doesn't help, because the student can swap the path after the
        check. So the kernel refuses instead: each relative path is walked
        one folder at a time, no symlink is followed anywhere along it, and
        an existing destination is never written over.

        Args:
            src_root: Where the walk to the source starts. Not itself
                allowed to be a symlink.
            src_rel: The source, relative to ``src_root``.
            dest_root: Where the walk to the destination starts, likewise.
            dest_rel: The destination, relative to ``dest_root``. Missing
                folders on the way are created, mode 755.
            mode: The new file's mode.

        Raises:
            StepFailed: Anything but a plain file at the source, or any of
                the refusals above. A partly written file is removed.
        """
        src, dest = src_root / src_rel, dest_root / dest_rel
        self._show("copy", f"{src} -> {dest} [dim](mode {mode:o})[/dim]")
        logger.info("copy %s -> %s", src, dest)
        if self.dry_run:
            return
        create = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        try:
            src_dir = _open_dir_nofollow(src_root, src_rel.parent.parts)
            try:
                # O_NONBLOCK so that a FIFO reaches the check below rather
                # than hanging this open, and with it the whole class, forever.
                source_fd = os.open(
                    src_rel.name,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=src_dir,
                )
            finally:
                os.close(src_dir)
            with os.fdopen(source_fd, "rb") as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise StepFailed(f"{src} isn't a regular file")
                dest_dir = _open_dir_nofollow(
                    dest_root, dest_rel.parent.parts, create=True
                )
                try:
                    target_fd = os.open(dest_rel.name, create, mode, dir_fd=dest_dir)
                    try:
                        with os.fdopen(target_fd, "wb") as target:
                            shutil.copyfileobj(source, target)
                            os.fchmod(target.fileno(), mode)
                    except BaseException:
                        os.unlink(dest_rel.name, dir_fd=dest_dir)
                        raise
                finally:
                    os.close(dest_dir)
        except OSError as error:
            raise StepFailed(f"Couldn't copy {src} to {dest}: {error}") from error

    def same_content(self, left: Path, right: Path) -> bool:
        """True if both paths exist and hold identical bytes.

        Compared byte-wise rather than as text, since this runs against
        arbitrary handout files.  Always compared for real, even in a dry
        run -- inspection, not a change, the same reasoning as
        :meth:`read_text`.  False if either path is missing.
        """
        if not left.is_file() or not right.is_file():
            return False
        return left.read_bytes() == right.read_bytes()

    def read_text(self, path: Path) -> str:
        """Read a file's current contents.

        Always runs for real, even in a dry run -- this is inspection, not a
        change, the same reasoning as ``Libvirt.check_host_tools()`` running
        for real during a dry run (see ``lab/virt.py``): better to fail
        loudly here than produce a preview built on a guess.
        """
        return path.read_text()

    def read_command(self, argv: Sequence[str]) -> str:
        """Run a read-only command and return its stdout.

        Always runs for real, even in a dry run -- inspection, not a change,
        the same reasoning as :meth:`read_text`. :meth:`run` deliberately
        fakes an empty result during a dry run, which is right for commands
        that *do* something and wrong for ones that only report: a preview
        built on empty output isn't a cautious preview, it's a blank one.
        Use this only for commands with no side effects.

        Returns an empty string if the command isn't there or fails, so a
        caller can treat "nothing to report" and "nothing installed" alike.
        """
        argv = [str(a) for a in argv]
        logger.info("read: %s", shlex.join(argv))
        try:
            result = subprocess.run(argv, text=True, capture_output=True, check=False)
        except OSError:
            return ""
        return result.stdout or ""

    def exists(self, path: Path) -> bool:
        """True if ``path`` exists.

        Always checked for real, even in a dry run -- inspection, not a
        change, the same reasoning as :meth:`read_text`.
        """
        return path.exists()

    def kind_nofollow(
        self, root: Path, rel: Path
    ) -> Literal["file", "missing", "other"]:
        """What is at ``root / rel``, without following any symlink to it.

        ``"file"`` is a regular file reached entirely through real folders.
        ``"missing"`` is nothing at all. ``"other"`` is everything else: a
        folder, a FIFO, a symlink, or anything behind a symlink, which is
        what separates this from :meth:`exists`.

        Always checked for real, even in a dry run -- inspection, not a
        change, the same reasoning as :meth:`read_text`.
        """
        try:
            dir_fd = _open_dir_nofollow(root, rel.parent.parts)
            try:
                info = os.stat(rel.name, dir_fd=dir_fd, follow_symlinks=False)
            finally:
                os.close(dir_fd)
        except FileNotFoundError:
            return "missing"
        except OSError:
            return "other"
        return "file" if stat.S_ISREG(info.st_mode) else "other"

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

    def group_exists(self, name: str) -> bool:
        """True if a Unix group of this name already exists.

        Always checked for real, even in a dry run -- inspection, not a
        change, the same reasoning as :meth:`passwd_entries`.
        """
        try:
            grp.getgrnam(name)
            return True
        except KeyError:
            return False

    def group_members(self, name: str) -> list[str]:
        """Every account in a Unix group, by secondary *or* primary membership.

        ``grp.getgrnam().gr_mem`` lists only *secondary* members -- an
        account whose primary group is this one doesn't appear there at
        all.  On a server where accounts are created with a per-section
        primary group that is the difference between seeing a whole class
        and seeing nobody, so both sources are unioned here.

        Always read for real, even in a dry run -- inspection, not a
        change, the same reasoning as :meth:`passwd_entries`.  Empty if no
        such group exists.
        """
        try:
            group = grp.getgrnam(name)
        except KeyError:
            return []
        members = set(group.gr_mem)
        members.update(
            entry.pw_name for entry in pwd.getpwall() if entry.pw_gid == group.gr_gid
        )
        return sorted(members)

    def primary_group(self, username: str) -> str:
        """The name of ``username``'s primary group.

        Always read for real, even in a dry run -- inspection, not a
        change, the same reasoning as :meth:`passwd_entries`.
        """
        return grp.getgrgid(pwd.getpwnam(username).pw_gid).gr_name

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

    def ensure_block(self, path: Path, marker: str, block: str) -> None:
        """Append ``block`` to ``path`` once, identified by ``marker``.

        Unlike :meth:`append_line`, which matches a single exact line, this
        only checks whether ``marker`` appears anywhere in the file -- so a
        student who has since hand-edited *inside* the block (e.g.
        uncommenting a line) is never mistaken for "not applied yet" and
        doesn't get a second copy appended.
        """
        self._show("ensure block", f"{marker!r} -> {path}")
        if self.dry_run:
            return
        existing = path.read_text() if path.exists() else ""
        if marker in existing:
            return
        with open(path, "a") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(block)
            if not block.endswith("\n"):
                handle.write("\n")

    def mkdir(self, path: Path, *, mode: int = 0o755) -> None:
        """Create a directory and any missing parents."""
        self._show("mkdir", str(path))
        if self.dry_run:
            return
        path.mkdir(parents=True, exist_ok=True, mode=mode)

    def ensure_readonly_dir(self, path: Path, *, mode: int = 0o755) -> bool:
        """Make ``path`` a directory that only this process can write to.

        Creates it if nothing has the name. It takes this process's owner,
        which on a real run is root, so nothing needs chowning. Unlike
        :meth:`mkdir` this is safe in a folder a student controls: it never
        follows a symlink, and it doesn't accept one of their own folders as
        the real thing.

        Returns:
            True if the directory is there, or would be after a dry run.
            False, having changed nothing, if something this process doesn't
            own is already using the name.
        """
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            self._show("mkdir", f"{path} [dim](mode {mode:o})[/dim]")
            logger.info("mkdir %s", path)
            if not self.dry_run:
                os.mkdir(path, mode)
                # mkdir's mode is cut down by the umask. By descriptor, not by
                # name: chmod follows symlinks, and the name is the student's
                # to swap the moment the directory exists.
                dir_fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    os.fchmod(dir_fd, mode)
                finally:
                    os.close(dir_fd)
            return True
        return stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()

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


def _open_dir_nofollow(
    root: Path, parts: Sequence[str], *, create: bool = False
) -> int:
    """Open ``root/parts...`` one folder at a time, refusing any symlink.

    ``O_NOFOLLOW`` alone only protects the last part of a path, so a symlink
    earlier in it would be followed; opening each folder relative to the one
    before closes that gap. With ``create``, missing folders are made, mode
    755 whatever the umask.

    Returns:
        An open descriptor, for the caller to close.

    Raises:
        OSError: A folder is missing, or isn't a real folder.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(root, flags)
    for part in parts:
        try:
            made = False
            if create:
                try:
                    os.mkdir(part, 0o755, dir_fd=fd)
                    made = True
                except FileExistsError:
                    pass
            next_fd = os.open(part, flags, dir_fd=fd)
        finally:
            os.close(fd)
        fd = next_fd
        if made:
            os.fchmod(fd, 0o755)
    return fd


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
