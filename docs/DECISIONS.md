# Decisions and handoff notes

Written 2026-08-19, at the point where the package was finished but had never
been run against a real machine. If you are an assistant picking this up: read
"Where things actually stand" first, because the gap between "the code is
written" and "the code works" has not been closed yet.

---

## Where things actually stand

**Verified:** 45 unit tests pass, `mypy --strict` is clean, `black` is clean,
and every CLI command has been exercised in dry-run mode so the exact shell
commands and file contents have been eyeballed.

**The `server` and `client` plans, and the full client-image pipeline, have
now all run for real, end to end, successfully**, on 2026-08-19. The
`server` plan ran its six stages (`networking`, `mirrors`, `apps`, `ltsp`,
`virt`, `desktop`) against the lab's `ltsp-server` VM across two real
reboots; the `client` plan ran its four stages against a client-template
overlay on the workstation across one reboot; both fully driven by the
systemd resume unit with no manual intervention between reboots. Four real
bugs turned up along the way (see "Bugs found on the first real run" below)
and are fixed, plus a lab-only disk-sizing problem (see "Building and
testing the client image in the lab" below).

The image build itself was exercised through the lab's disk-space
workaround (see "Building and testing the client image in the lab" below)
rather than the server hosting the template VM directly — that specific
path (`steps/image.py::create_client_template` /
`shutdown_client_template` running on the server itself) is still
unverified. `run_ltsp_image`, `convert_to_raw`'s command shape, and the
real `ltsp image` invocation are now confirmed working, including
resolving the "does `ltsp image` need a separate `ltsp initrd` re-run"
open question — see "Decisions, and why" below.

**And a thin client has now actually netbooted against it, for real**
(2026-08-19, `ltsp-client` on the lab's isolated network). Confirmed from
the server's own dnsmasq/NFS logs, not just assumed: PXE DHCP handshake →
TFTP served `ltsp.ipxe`, then correctly resolved to *this specific image*
(`ltsp-client-template/vmlinuz` + `initrd.img`, not a generic fallback) →
kernel boots, requests its own DHCP lease → `showmount -a` shows
`/srv/ltsp` actively NFS-mounted from the client. The whole chain — PXE,
DHCP, TFTP, kernel/initrd, NFS root — works end to end. Getting here
needed one more real fix: `DEFAULT_IMAGE` in `/etc/ltsp/ltsp.conf`, not
written by any existing code, is what tells `ltsp ipxe` which image to
default the menu to; see "Decisions, and why" below.

Confirmed working: LTSP + dnsmasq + NFS installed and active, KVM/libvirt
installed with `sysadmin` in the `libvirt` group, Chrome/VS Code/Java/
Racket/Rust all present and on PATH on both server and client, dconf
datetime settings applied, `epoptes-client` on the template, a real
3.9GB squashfs + kernel/initrd built and dropped in `/srv/tftp/ltsp/`, and
now a full netboot against it.

The golden Mint 22.3 image was being built by hand when this was written;
it's since finished and is frozen (`chmod 444`, domain undefined) per the
"Golden image + copy-on-write clones" section below.

**The remaining unverified path from above is now verified too** (2026-08-20):
`steps/image.py::create_client_template`/`build_image` ran for real on the
actual production server (`200-231-server`), not the lab workaround —
`mint-22.3-xfce-client` was installed directly as a KVM VM on the server
itself, imaged locally, no cross-machine hand-carry needed. Along the way:

- Reused the lab's golden-image/COW-overlay machinery (`lab create-client-template`
  / `lab reset`) on the server itself, purely as a development convenience —
  freeze a minimal install once (`mint-22.3-xfce-fresh.qcow2`), then clone
  and re-run the `client` plan in seconds instead of reinstalling Mint by
  hand on every iteration. Not part of the documented production path above,
  which still does a fresh install directly; this is an option if that gets
  tedious.
- Added dated image names (`mint-22.3-xfce-client-2026-08-20`, matching this
  server's own pre-existing convention from before this tool existed) plus
  `image set-default`/`image list`, so a build is published without going
  live immediately, and reverting to any previous still-on-disk build is
  just `image set-default <name>` again — no rebuild. See
  `steps/image.py::dated_image_name`/`set_default_image`.
- **`server.configure_ltsp` must not be run against this real server.** Its
  full-file `ltsp.conf` template would silently destroy real, already-active
  settings (`NFS_HOME=1`, `FSTAB_HOME`, `LIGHTDM_CONF`) that predate this
  tool and aren't reflected in `data/ltsp.conf`. `set_default_image` patches
  only the `DEFAULT_IMAGE` line in place instead — see
  `steps/image.py::_with_default_image`.

  **The underlying gap is fixed now (2026-08-26)** — `data/ltsp.conf`
  gained a real `[clients]` section (`FSTAB_HOME`, `LIGHTDM_CONF`,
  `POST_INIT_CUPS`, `POST_INIT_NOCUPSD`) and `NFS_HOME=1`, found by diffing
  against this same real server's `ltsp.conf` (see "Bugs found on the
  first real run" below). The caution above still holds for a different
  reason, though: this template always writes the *static* configured
  image name, and this server's real `DEFAULT_IMAGE` is a *dated* build
  (`mint-22.3-xfce-client-2026-08-26-2`) — running `configure_ltsp` here
  would still clobber that. Only run it against a server whose
  `DEFAULT_IMAGE` is meant to track the static name (the lab's `ltsp-server`
  does); use `set_default_image` for anything already live on a dated name.
- Two real bugs found building the actual production image, both now fixed
  and covered by regression tests: `run_ltsp_image` once passed a dated
  name to `ltsp image` while the raw source was still written under the
  static undated name (`ltsp image <name>` needs the *same* name for both
  its source and its output — see `man ltsp-image`); and
  `list_published_images` used `Path.glob`, which silently swallows
  `PermissionError` on `/srv/ltsp/images` (root-owned `0700`) and reported
  "nothing published" instead of failing loudly.
- **Confirmed booting on real hardware**, not just a VM: two physical lab
  machines, one on each of the school's two routers, both PXE-booted
  `mint-22.3-xfce-client-2026-08-20` successfully — TFTP served the new
  image's `initrd.img`/`vmlinuz` by name, confirmed from dnsmasq's own log.

---

## Decisions, and why

### Building the client image: the server hosts the template VM itself

Todd's call (2026-08-19): the production server runs KVM and hosts the
client template as a local libvirt VM (`ClientTemplate` in `config.py`,
`steps/image.py`) — not a separate machine, and not `ltsp image /` on the
server itself. Server and client stay two genuinely different machines
(different packages, different configuration), but because the template's
disk is always local to the server, imaging never needs a cross-machine
disk transfer.

Checking `ltsp-image(8)` directly (it's undocumented in Todd's how-to
notes, which predate this feature) changed the mechanism from what was
guessed here originally:

- `ltsp image` takes a **raw VM disk image** directly as a source — it
  mounts/loop-mounts the file itself. No NBD attach, no manual mount, no
  chroot needed.
- qcow2 is never mentioned in LTSP's docs, only raw and VMDK. The template
  VM's own disk stays qcow2 (COW, snapshotting, consistent with the lab's
  disks); `steps/image.py::build_image` converts it to raw with
  `qemu-img convert` right before each image build, then deletes the raw
  copy again afterwards. Keeping it resident permanently would mean the
  server always budgets for a full second copy of the client disk; deleting
  it means that headroom is only needed transiently, during a rebuild.
- `-c/--cleanup` (`ltsp image`'s default) already builds a writeable overlay
  and strips accounts/sensitive data before `mksquashfs`.
- `ltsp image` calls `ltsp kernel` itself after building the squashfs —
  **confirmed** on the first real run (2026-08-19): the output shows
  `Running: ltsp kernel /srv/ltsp/images/ltsp-client-template.img` firing
  automatically and dropping `initrd.img`/`vmlinuz` in `/srv/tftp/ltsp/
  ltsp-client-template/`. So no, a separate `ltsp initrd` re-run per
  rebuild is not needed — `configure_ltsp`'s existing one-time call (which
  sets up the generic PXE/iPXE boot files, a different thing) is correctly
  left alone in `run_ltsp_image`.

`ltsp-setup image create-template` does the one-time interactive install
(same shape as `lab build-golden`); `ltsp-setup image build` shuts the
template down and rebuilds the netboot image, and is re-runnable on demand.
The server now also needs KVM/libvirt itself — see the new `virt` stage in
`plans.SERVER`.

### `DEFAULT_IMAGE` in ltsp.conf, and only ever serving one image

A built squashfs sitting in `/srv/ltsp/images/` doesn't make thin clients
boot it — nothing did until the first real netboot attempt (2026-08-19)
turned up two more real gaps, both now fixed:

1. **`configure_ltsp` never wrote `/etc/ltsp/ltsp.conf` at all.**
   `ltsp ipxe` reads `DEFAULT_IMAGE` from `[server]` there to decide what
   the generated boot menu defaults to; without it, the menu falls back to
   an arch-based guess (`x86_64`) that matches no actual image. New
   `data/ltsp.conf` template, written by `configure_ltsp` (with
   `client_template.image_name`) *before* `ltsp ipxe` runs, since the menu
   is generated from whatever's in the file at that moment.
2. **`run_ltsp_image` now passes `--backup 0`.** Todd's operational rule,
   confirmed the same day: serve only one image, ever. Students don't
   choose from the boot menu, so `ltsp image`'s default of keeping
   `<name>.img.old` around is just a way for some clients to end up
   booting a stale version by accident.

Verified for real against `ltsp-client` on the isolated lab network,
straight from the server's own dnsmasq log: PXE DHCP → TFTP serves
`ltsp.ipxe`, which now resolves `img` to `ltsp-client-template` (visible
as `set img ltsp-client-template` injected into the generated file) →
correct per-image `vmlinuz`/`initrd.img` served → client requests its own
DHCP lease → `showmount -a` shows `/srv/ltsp` mounted from the client.

### Building and testing the client image in the lab

The lab's `ltsp-server` VM has a 40GB disk (`Lab.golden_disk_gb`) — nowhere
near enough to also host a full second Mint install for the client
template inside it, the way production does. Todd's call (2026-08-19):
build the template on the *workstation* instead, as a copy-on-write
overlay on the same golden image the other lab VMs use (fast, and disk-
cheap — the alternative, a fresh full install, would have hit the same
problem one level up), then hand-carry the result to the server. This
knowingly doesn't exercise `create_client_template`/
`shutdown_client_template` running *on* the server, which is still
unverified — everything downstream of that does get exercised for real.

Added for this:
- `Virt.create_client_template()` / `lab create-client-template` —
  overlay on the golden image, attached to the `default` NAT network
  (unlike `create_client`, which is deliberately on the isolated `ltsp`
  network) so the `client` plan's `apt` work has internet access.
- `steps/image.py::build_image` split into `shutdown_client_template`,
  `convert_to_raw`, and `run_ltsp_image` so the lab workflow can run the
  first two on the workstation and the third on the server, instead of one
  monolithic function assuming everything is co-located.
- `steps/image.py::import_raw_image` / `ltsp-setup image import-raw` —
  server-side: moves an already-converted raw image (copied over by hand
  with `rsync --sparse`, since a plain `scp` would send the full 40GB
  instead of the ~17GB actually used) into place and runs
  `run_ltsp_image`.

The actual lab sequence that worked: `lab create-client-template` on the
workstation → authorize the SSH key and scoped sudo by hand (same one-time
dance as the server, since a fresh overlay doesn't inherit either — they
were added to the running server's disk after the golden image was
already frozen) → `client start --no-debug` → shut down and
`qemu-img convert -O raw` on the workstation (needs `sudo`, which this
session didn't have passwordless on the workstation, so that one step was
run by hand) → `rsync --sparse` the raw file to the server → `image
import-raw` on the server.

**Real disk-sizing catch along the way:** the server VM's own `apps` stage
(Chrome, VS Code, Rust, Java, Racket — confirmed intentional, sysadmin
wants these on the server too, not just the client) plus KVM/libvirt left
only 2.7GB free on its 40GB disk, nowhere near enough headroom for
`ltsp image`'s writeable overlay and squashfs output on top of the ~17GB
raw source. Fixed by live-growing the overlay to 60GB
(`virsh blockresize`, no shutdown needed) and growing the partition/
filesystem online (`growpart` + `resize2fs`, from `cloud-guest-utils`,
not installed by default). This is a lab-VM-sizing problem, not a
production one — real hardware won't be this tight — but it's worth
remembering `server_ram_mb`/the implicit 40GB `golden_disk_gb` ceiling
if the lab VMs keep growing.

### Consolidate into `ltsp-setup`; `lab` is retired

There were two overlapping half-finished ports. `ltsp-setup` had the cleaner
foundation (poetry, typer, `string.Template` data files), so it won.
`~/code/python/lab` still holds the student-account code, which has not been
ported. Do not delete that repo.

### Python, not bash

The bash version worked but was the older implementation. Todd's call: the
Python is easier to read and follow. The shell tree now lives in `_to_delete/`.

### systemd oneshot, not `@reboot` cron

The bash version survived reboots by turning on autologin for `sysadmin`,
adding a passwordless-sudo exception for the setup script, and running it from
a `@reboot` cron job. Three security-relevant changes that all had to be
cleaned up afterwards, and if cleanup did not run they silently persisted.

Now: one `ltsp-setup.service` oneshot unit, running as root at boot, that
disables and removes itself when the plan finishes. Progress is in
`/var/lib/ltsp-setup/state.json`. Logs go to the journal.

### Golden image + copy-on-write clones, not preseeding

The Mint ISO is a live image driven by Ubiquity. `lab/src/files/preseed.cfg`
was written as a debian-installer preseed, which Ubiquity cannot consume —
`virt-install --location` plus `--initrd-inject` does not work against this
ISO. Mint *can* be preseeded via `automatic-ubiquity`, but it is a well-known
time sink and breaks on point releases.

So: install Mint by hand once, freeze that qcow2, and make both VMs
copy-on-write overlays on top of it. Creating a VM takes about a second, so
re-testing from a genuinely pristine machine is cheap enough to do constantly.

The golden disk is the **backing file** for both overlays. Booting it again
corrupts every clone. It is `chmod 444` and its libvirt domain is undefined
specifically to make that mistake hard.

Revisiting unattended install later is fine. It was deferred, not rejected.

### Interfaces matched by MAC, not by name

Interface names come from PCI enumeration order. The old code had three
different guesses across three files (`enp0s3/enp0s8` from VirtualBox,
`enp1s0/enp10s0` from QEMU, `eno1/eno2` from the real server) and no way to
tell which applied.

Now `mac_for_internet` / `mac_for_ltsp` in the config produce netplan
`match: {macaddress: ...}` plus `set-name:`, so the interface gets renamed to
whatever `nic_for_internet` / `nic_for_ltsp` say regardless of slot order. The
lab assigns fixed MACs (`52:54:00:67:00:01` internet, `...:02` LTSP,
`...:10` client) for exactly this reason.

This means `examples/lab.toml` and `examples/school.toml` can differ only in
the MACs, and the same code path is exercised both places.

### Disks and ISO in `/var/lib/libvirt/images`

Under `qemu:///system`, QEMU runs as `libvirt-qemu` under an AppArmor profile
that grants access to libvirt's storage directory and denies it in home
directories. Todd hit this empirically with the ISO in `~/Downloads` before
the default was changed. Do not move these back under `~`.

### Dry run by default

Every command defaults to `--debug`, which prints the exact commands and the
full contents of every file it would write, and changes nothing. A real run
must say `--no-debug`. This inverts the usual default deliberately: these
scripts run as root on a machine that is tedious to rebuild.

`Runner` in `runner.py` is the only place that executes anything or touches
disk. Keep it that way — it is what makes the dry run trustworthy.

### Commands are argument lists, never shell strings

`Runner.run` takes a list and never uses `shell=True`. `run_shell` exists for
genuine pipelines (dearmoring a GPG key) and is used twice. This is partly
hygiene and partly because the old code had a bug that came directly from
mixing the two — see below.

### Concurrent-login lock: a directory on NFS home, not a PAM session count

Todd's concern (2026-08-26): two thin clients logged in as the same student
account both write to the same NFS-mounted home directory, which corrupts
things like browser profile locks (the Chrome singleton-lockfile problem
below is one instance of this general class of bug). `pam_limits`'
`maxlogins` looked like the obvious fix — it's already wired into
`/etc/pam.d/lightdm` (`session required pam_limits.so`) — but it only counts
sessions in the *local* utmp, and each thin client is its own independent
boot with its own utmp. It can't see a login on a different client at all.

Instead, `steps/common.py::configure_session_lock` patches
`/etc/pam.d/lightdm` (a package-owned conffile, hence patched in place with
`_insert_after` rather than templated wholesale — same reasoning as
`image.py`'s `DEFAULT_IMAGE` line-patching) to run
`data/ltsp-session-lock-check.sh` via `pam_exec` in the `auth` phase. It
takes an atomic `mkdir` lock (atomic even over NFS, unlike `flock`) in a
directory inside the student's own home, refuses a login from a different
hostname while that lock is fresh, and auto-recovers if the owning client
goes silent for more than `STALE_SECONDS` (180s) — e.g. it crashed or lost
power without logging out. An XFCE autostart entry
(`ltsp-session-heartbeat.desktop` → `ltsp-session-heartbeat.sh`) refreshes
the lock every 60s for the life of the session so a real, still-active
session is never mistaken for an abandoned one; `ltsp-session-lock-release.sh`
(PAM `close_session`) removes the lock on a clean logout. `ltsp-setup student
clear-lock <username>` removes one by hand, for when 180s is still too long
to wait.

**Tested against real hardware 2026-08-26** — Todd logged into the same
student account on two real thin clients: the second login was refused, and
logging out of the first let the second in immediately after. One gap found
in that test: `pam_exec`'s `auth requisite` failure showed LightDM's generic
"Invalid password" rather than the script's actual message, because
`pam_exec` sends a failing child's output to `/dev/null` by default. Fixed
by adding the `stdout` option (`auth requisite pam_exec.so quiet stdout
...`), which relays the script's stdout to the greeter via `pam_info()`, and
moving the refusal message from stderr to stdout to actually reach it.

Caught by the same real-hardware test this decision used to call for, and
one more thing worth remembering from it: the `desktop` stage had silently
run against a stale install on the template earlier in the session (see
`docs/desktop-polish-todo.md`) — a passing dry-run and a clean `pytest` run
here never would have caught either of these, only actually logging in on
two real clients did.

---

## Bugs found in the old code

Recording these so they do not get reintroduced.

1. **`check_call(["rm", "/etc/netplan/*"], debug)`** — a list passed with
   `shell=True`. On POSIX that runs `rm` with no arguments and binds the rest
   to `$0`/`$1`. It never deleted anything, and the glob would not have
   expanded anyway. Netplan cleanup is now done in Python with `pathlib`.

2. **`mirrors.py` said `mint_version = "zara"`** — that is Mint 22.2. 22.3 is
   `zena`. Would have pointed apt at the wrong Mint repo.

3. **`data/etc_netplan_ltsp.yaml` was malformed** — `wakeonlan` and
   `linklocal` were siblings of the interface names under `ethernets:` rather
   than children of each interface, and `linklocal` is misspelled (`link-local`).
   Netplan is now generated through PyYAML from a dict, so it cannot be
   syntactically malformed. There is a test asserting `activation-mode: 'off'`
   stays quoted, because YAML would otherwise read `off` as boolean false.

4. **`lab/src/files/preseed.cfg` is unusable** — see the golden image section.

---

## Bugs found on the first real run

Recording these too, same reason as above.

1. **`make_overlay()` used a raw `qemu-img create` instead of the libvirt
   storage pool.** `lab.pool_dir` (`/var/lib/libvirt/images`) is root-owned
   `0711`; only libvirtd, running as root, can create files there. `virt-install`
   itself is pool-aware and worked fine, but our own direct `qemu-img create`
   call, run as the unprivileged CLI user, failed with a plain permission
   error. Fixed by routing overlay creation through `virsh vol-create-as` /
   `vol-delete` against the pool (new `Lab.pool_name` config, default
   `"default"`), so libvirtd does the actual write.
2. **`build_golden()` had no check for an existing golden disk.** It would
   have run `virt-install` straight over an already-finished golden image.
   Caught only because the *finished* image is `chmod 444`, which blocked
   the accidental reinstall with a permission error rather than actually
   corrupting it — the protection documented in "Golden image + copy-on-write
   clones" worked exactly as intended, but the code shouldn't have relied on
   it as the only guard. Fixed: `build_golden()` now checks
   `golden_disk.is_file()` first and refuses with instructions.
3. **`install_prerequisites()` installed `software-properties-common`,
   which doesn't exist on Mint.** Mint's `mintsources` package replaces it
   (`apt-cache policy` shows no installation candidate at all) and is
   already present on a stock install; it already provides
   `add-apt-repository`, the only thing later steps needed from that
   package. Removed from the prerequisite list entirely.
4. **`install_prerequisites()` ran before the package index was refreshed
   against the new mirrors.** `_mirrors_and_upgrade` wrote the new sources
   file, then immediately ran `apt-get install` for the prerequisites, and
   only called `apt-get update` afterwards (inside `apt_upgrade`). Installing
   against the stale pre-switch index produced a real "unmet dependencies"
   failure (`git` needing `liberror-perl`). Fixed by calling
   `common.apt_update(ctx)` in `plans.py::_mirrors_and_upgrade` right after
   `set_mirrors`, before `install_prerequisites`.
5. **`stages.py::_entry_point()` fell back to a hardcoded
   `/usr/local/bin/ltsp-setup`** when `shutil.which("ltsp-setup")` failed to
   resolve it — which it reliably does under `sudo`, whose `secure_path`
   strips a project-local venv's `bin/` off `PATH` even when the invoking
   shell had it there. Every venv-based install (this project's own
   documented setup) hit this the first time the boot-time resume unit
   fired after a reboot: `203/EXEC`, nothing left to resume. Fixed to fall
   back to the console script next to `sys.executable` instead, which is
   unaffected by `PATH`. Caught running the real server plan end-to-end in
   the lab for the first time (2026-08-26).
6. **`image import-raw` built the squashfs under the wrong name.**
   `import_raw_image` moves the raw source into place under the *static*
   configured `client_template.image_name`, but the CLI command then called
   `run_ltsp_image(ctx)` with no argument, which defaults to
   `dated_image_name(ctx)` — despite `run_ltsp_image`'s own docstring saying
   the lab's cross-machine workflow "passes nothing so it falls back to the
   static configured name." `ltsp image` would look for a source file that
   was never written and fail with "Image does not exist." Fixed by passing
   the static name through explicitly. Caught trying to actually run the
   lab's cross-machine image-build workflow for the first time (2026-08-26).
7. **`data/ltsp.conf` only ever rendered a `[server]` section** —
   `[clients]` (`FSTAB_HOME`, `LIGHTDM_CONF`, `POST_INIT_CUPS`,
   `POST_INIT_NOCUPSD`) and `NFS_HOME=1` were missing entirely, even though
   the real production server has had all of them for a while (added by
   hand, never ported back — see the `configure_ltsp` caution above). Found
   because the lab's `pxe-test` client showed LightDM's full scrollable
   user-list greeter (a few hundred real names is unusable) instead of a
   plain username prompt. Fixed by adding both to the template
   (2026-08-26).
8. **`configure_ltsp` ran `ltsp nfs` *before* writing `ltsp.conf`.** `ltsp
   nfs` reads `NFS_HOME` from `ltsp.conf` to decide whether to uncomment
   the `/home` export in `/etc/exports.d/ltsp-nfs.exports` (`man
   ltsp-nfs`) — run first, it only ever sees the *previous* content, so
   adding `NFS_HOME=1` (bug 7, above) silently never took effect. Same
   class of bug `ltsp ipxe`'s ordering already guarded against
   (`DEFAULT_IMAGE` needs to exist first); this just missed the equivalent
   for `nfs`. Confirmed via `exportfs -v` on the lab server: `/home` never
   appeared until this moved after the write. Fixed by moving `ltsp nfs`
   to run after the config write (2026-08-26) — meaning **no lab or real
   run before this fix ever actually had a working NFS-mounted home
   directory**, only whatever a client's local ephemeral filesystem
   provided.

---

## Deferred, deliberately

- **Student account creation.** Still in `~/code/python/lab`:
  `accounts/create.py`, `accounts/student.py`, `accounts/groups.sh`,
  `accounts/data/rosters.csv`, `accounts/users.txt`. Not ported. Todd wants a
  working server and client first — done now, see "Where things actually
  stand" above.

  Real gotcha found testing a manually-created account (2026-08-19):
  `ltsp.img` (LTSP's generic initrd, separate from the per-image squashfs)
  embeds a snapshot of the server's `passwd`/`group`, per `man
  ltsp-initrd`. A new user is invisible to clients — "user doesn't exist"
  at login — until `ltsp initrd` re-runs and the client reboots. Cheap
  (seconds, no squashfs rebuild needed), but easy to forget by hand.
  Whatever this account-creation feature ends up being, it should trigger
  `ltsp initrd` itself rather than leaving that as a step someone has to
  remember — a newly created account should just work on next boot.
- **Student default configuration.** Partly built (2026-08-24) —
  `steps/students.py` plus `steps/xfconf.py`; see the new section below.
  Still missing: wiring `apply_defaults` into account creation itself once
  that's ported (it's written to be safely callable standalone against a
  freshly-created account, so no rework needed later), and dconf/per-app
  config beyond the two xfconf files managed today.
  `steps/common.py::configure_dconf` is where a dconf-based version of the
  same idea would go.
- **Trimming the image.** The 25 GB disk overflowed, which is part of why this
  rebuild happened; the default is now 40 GB. Chrome, VS Code, the JDK and a
  full Rust toolchain are the four big items. `ltsp image` squashfs-compresses,
  so the netboot image will be much smaller than the disk it came from.
- **Unattended Mint install.**
- **NFSv4 + Kerberos for `/home` instead of plain NFSv3.** Motivated by a
  real concern (2026-08-19): Chrome startup gets slow when many students
  launch it at once, and NFSv4 is meaningfully faster than SSHFS
  (kernel-space, compound RPCs, delegation caching) even with Kerberos
  encryption (`sec=krb5p`) turned on — unlike plain NFSv3, which is faster
  than SSHFS but has no real per-user auth (`no_root_squash` + UID-trust
  means one client can impersonate another's UID) and was rejected for that
  reason on its own. Deferred because it's purely additive on top of what
  exists — nothing to undo. LTSP's own switch is `NFS_HOME=1` + a
  `FSTAB_HOME` fstab line in `ltsp.conf` (`man ltsp-nfs` has the NFSv3
  example verbatim), then `ltsp initrd` + `ltsp nfs`.

  **Correction (2026-08-20):** this whole note was written assuming SSHFS
  is what's currently live and slow. Checking the real production
  `/etc/ltsp/ltsp.conf` on this server shows `NFS_HOME=1` and `FSTAB_HOME`
  already set — **this server is already on plain NFSv3, not SSHFS.**
  Either the Chrome slowness reported last school year happened under
  NFSv3 already (which would mean the SSHFS→NFSv4 speed story above isn't
  the actual explanation, and something else — concurrent NFSv3 load,
  Chrome's own profile/lock behavior, something else entirely — is worth
  checking first) or the server moved off SSHFS at some point without this
  doc being updated. Not resolved; see the timing-test item below before
  assuming NFSv4+Kerberos is the fix. The separate, genuinely nontrivial
  piece — standing up a Kerberos KDC and keytabs for the server and every
  client — still doesn't conflict with NFSv3 running in the meantime.
- **Timing tests: NFSv3 vs SSHFS for `/home`.** Added 2026-08-20, prompted
  by the correction just above: before spending the KDC/LDAP effort on
  NFSv4+Kerberos, get real numbers instead of assuming. Measure Chrome
  startup (and general `/home` latency, e.g. `dbench`/`fio` against a real
  mounted home dir) under concurrent load, comparing this server's current
  NFSv3 setup against SSHFS, on the same client hardware. If NFSv3 turns
  out to already be fast enough and the reported slowness has some other
  cause, that changes whether the NFSv4+Kerberos investment (below) is
  actually worth it.

  There's a second real bug this could fix, but only if scoped correctly:
  `pamltsp` (`ltsp/client/login/pamltsp` upstream) implements the PAM
  `auth`/`session` phases (SSH to the server) but never the `password`
  phase at all, so a student running `passwd` on the client silently
  rewrites the ephemeral client's own `/etc/shadow` — no effect on the
  server, gone on next reboot either way. Confirmed as a known, upstream
  `wontfix`.

  **A second real symptom of the same gap** (reported 2026-08-20, a
  recurring problem last school year): when a student's password is changed
  on the server, their GNOME login keyring — created under the old
  password — no longer auto-unlocks, because `pamltsp` never runs the PAM
  `password` phase that would keep it in sync. Every time the student then
  opens Chrome (or any app that touches the keyring) they get a
  keyring/login password mismatch prompt and have to click Cancel
  repeatedly to get past it. Same root cause as the `passwd` bug above,
  same fix (SSSD implementing the PAM `password` phase properly) — no
  separate design needed, just another reason the SSSD work is worth doing.

  Swapping the `/home` *mount protocol* (SSHFS → NFSv4) doesn't
  touch this — auth and home-mounting are separate mechanisms in LTSP. What
  fixes it is replacing `pamltsp` with SSSD for account/auth. **Correction
  to the note above (2026-08-19): this isn't "students use `kpasswd`
  instead."** Kerberos alone has no POSIX account data (UID/GID/home/
  shell), so a real deployment pairs it with LDAP as the directory —
  that's the standard combo, e.g. what FreeIPA bundles (389-ds LDAP + MIT
  Kerberos + SSSD glue, packaged for exactly this "centralize a Linux
  lab's accounts" case, rather than hand-wiring the three separately).
  Once SSSD is the auth stack, `pam_sss.so` implements the PAM `password`
  phase properly (the phase `pamltsp` is missing) and talks the Kerberos
  password-change protocol to the KDC *on the student's behalf* — the
  standard `passwd` command and Mint's graphical "Users" tool both work
  completely normally through ordinary PAM, exactly as before. Students
  never see or type `kpasswd`; that's purely SSSD's internal
  implementation. So the KDC+LDAP investment is worth it for both the
  NFSv4 speed reason and the password-change fix together, not because
  NFSv4 incidentally fixes the password bug on its own.

  **Idea floated the same day, explicitly "in an ideal world," not
  decided:** host the FreeIPA (LDAP+Kerberos) server on Todd's separate
  webapp server that lives outside district infrastructure, so students
  get one account for both the lab and the webapp. Real considerations to
  work through before this is more than an idea: (1) login availability
  at school would become dependent on reachability of an external host —
  a school internet outage would mean nobody can log into the lab, not
  just lose the webapp; (2) exposing LDAP/Kerberos ports across the open
  internet is a meaningfully bigger security surface than keeping auth
  infrastructure on an isolated internal LAN — a site-to-site VPN (e.g.
  WireGuard) between the school's LTSP server and the external host would
  be the sane way to do this, not opening 389/636/88/464 directly; (3) the
  webapp itself would need to actually authenticate against the same
  directory (LDAP bind, or an OIDC/SAML bridge in front of it) rather than
  its own separate user table, which is separate work depending on the
  webapp's stack; (4) whether student directory data living on a
  district-external host raises any compliance question worth checking
  into first, given it's specifically outside district infrastructure.
- **Overnight rebuild-and-reimage cron job.** `ltsp-setup image build`
  (`steps/image.py::build_image`) is the single re-runnable command this
  would call. The precondition here — the create/build split exercised on
  real hardware — is now satisfied (2026-08-27, several real rebuilds this
  week). Still deferred: the "boot the template, update its packages, shut
  it back down" half doesn't exist yet. See `docs/todo.md` for the two
  concrete open items this split into (an interactive edit-and-rebuild
  command, then the unattended cron version of it).
- **Chrome's stale singleton lockfile — fixed 2026-08-26, no longer
  deferred.** Real recurring problem last school year (reported
  2026-08-20): if a student's session ends uncleanly — powering off the
  thin client, or otherwise leaving Chrome "running" from the client's
  point of view — `~/.config/google-chrome/Singleton{Lock,Cookie,Socket}`
  survive in the student's (NFS-mounted) home directory. On the next login,
  `google-chrome` tries to hand off to that "existing" instance over the
  singleton socket, gets no response since the process is long gone, and
  just exits — no error, no window, nothing, so clicking the launcher looks
  like it did nothing at all. Todd wrote a `fix-chrome` script students
  could run by hand to delete the lockfiles; `steps/common.py::
  configure_chrome_singleton_cleanup` now does it automatically, at every
  session start, before Chrome ever runs. This originally looked safe on
  its own reasoning ("each thin-client login is a fresh session, so a login
  can never legitimately find a live Chrome process still holding that
  lock") — but that reasoning quietly depended on an assumption that turned
  out not to hold until the same day: nothing was actually stopping the
  same student account from being logged into *two* thin clients at once,
  in which case the second client's "stale" lock would really belong to the
  first client's still-live session. Fixed together with the concurrent-
  login lock (see "Concurrent-login lock" above) — this cleanup would be
  unsafe without it.

## Dropped from the app list

Todd's call on 2026-08-19, revisiting the old list: **IntelliJ IDEA Community**,
**PyCharm Community**, and the **Dvorak-Qwerty keymap** (the `tbocek/dvorak`
build, its dconf keyboard entries, and the ctrl/alt swap) are all out.

**Rust was added**, installed system-wide into `/usr/local/rustup` and
`/usr/local/cargo` with a `profile.d` snippet putting it on everyone's PATH.
Per-user rustup would mean every student downloading a several-hundred-megabyte
toolchain into an NFS-mounted home directory. `CARGO_HOME` is deliberately left
unset for users so `cargo install` still falls back to `~/.cargo`.

**Racket** comes from `ppa:plt/racket`. Checked on 2026-08-19: that PPA does
publish for noble and was at **9.1** (published 2026-03-03) while upstream was
at **9.3**. Todd wanted "latest" but also wanted the PPA; `apps.racket_source`
switches between `"ppa"` (apt-managed, upgrades with the system) and
`"upstream"` (resolves the newest release at install time from
racket-lang.org). Default is `"ppa"`.

**OpenJDK 17** was kept deliberately, not by inertia — Todd chose it over 21
and 25 when asked.

---

## Housekeeping still owed

- **`docs/how-to-server.md` and `docs/how-to-client.md` — deleted
  2026-08-26.** Todd's hand-written pre-port notes, moved out of
  `src/ltsp_setup/data/`; they were the most accurate description of what a
  real install needs and were the source of truth for the port — several
  things in the bash scripts were stale relative to them (Racket 8.15 vs
  8.18, the dead `ppa:mmk2410` IntelliJ PPA, the old `vscode.list` instead of
  deb822 `vscode.sources`). By the time of deletion they were themselves
  stale relative to the ported tool (Mint 22.2, IntelliJ/PyCharm and the
  Dvorak keymap both dropped 2026-08-19, no Rust/GIMP/Shotcut/
  SimpleScreenRecorder, a hardcoded Racket 8.18 download) and fully
  superseded by `steps/server.py`/`steps/client.py` plus `README.md`'s
  usage/bootstrap sections — keeping them "updated" would have meant
  hand-retyping what the code already does, with nothing to keep the two in
  sync. **Worth revisiting once the tool looks production-ready:** a plain-
  English "here's what happens and why" narrative walkthrough, written fresh
  from `steps/server.py`/`steps/client.py`, would still be worth having for
  onboarding or as a fallback if the tool itself breaks — just not worth
  maintaining a second, hand-written copy of the same steps while things are
  still actively changing.

---

## Things to be suspicious of on the first real run

- **`ltsp dnsmasq --proxy-dhcp=0`.** Correct for the isolated lab network,
  where the server owns the subnet and nothing else answers DHCP. On the real
  school network, if the school's own DHCP server is reachable on the LTSP
  segment, proxy DHCP is the right choice instead. This will need to differ
  between `lab.toml` and `school.toml` and currently cannot — it is hardcoded
  in `steps/server.py::configure_ltsp`.
- **`ltsp-binaries` from the PPA.** The old bash cloned
  `github.com/ltsp/binaries` by hand into `/srv/tftp/ltsp`. The PPA package is
  believed to supersede that, but it has not been confirmed.
- **The `networking` stage runs first, before mirrors.** It replaces
  NetworkManager-managed config with networkd. If the MACs are wrong the
  machine loses its network at step one. In a VM the console still works, so
  this is recoverable; on real hardware, be careful.
- **Whether `ltsp image`'s automatic `ltsp kernel` call makes the existing
  `ltsp initrd` re-run redundant per rebuild.** `steps/image.py::build_image`
  does not re-run `ltsp initrd` after each image build, on the reading that
  `ltsp image` already refreshes the kernel/initrd itself — but this is
  read from `ltsp-image(8)`, not observed. Check the actual netboot files
  under the images directory after a real `image build` to confirm.
- **`qemu-img convert -O raw` writing into `/srv/ltsp/` while a rebuild is
  in progress.** The server needs headroom for the qcow2 template disk plus
  a full raw copy simultaneously during that window (the raw copy is
  deleted again once `ltsp image` finishes) — make sure whatever partition
  holds `/srv/ltsp` and `/var/lib/libvirt/images` has room for both at once,
  not just steady-state usage.
- **e1000 for the client NIC.** Chosen over virtio because its PXE option ROM
  is the most thoroughly tested. If netboot misbehaves, this is a knob.
