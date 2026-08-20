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
- **Student default configuration** — `/etc/skel`, dconf system defaults, per-app
  config. `steps/common.py::configure_dconf` is where this goes; the dconf
  profile and local database are already set up properly rather than being
  poked in with one-off `gsettings` calls, specifically so this can slot in.
- **Trimming the image.** The 25 GB disk overflowed, which is part of why this
  rebuild happened; the default is now 40 GB. Chrome, VS Code, the JDK and a
  full Rust toolchain are the four big items. `ltsp image` squashfs-compresses,
  so the netboot image will be much smaller than the disk it came from.
- **Unattended Mint install.**
- **NFSv4 + Kerberos for `/home` instead of SSHFS.** Motivated by a real
  concern (2026-08-19): Chrome startup gets slow when many students launch
  it at once, and NFSv4 is meaningfully faster than the default SSHFS
  (kernel-space, compound RPCs, delegation caching) even with Kerberos
  encryption (`sec=krb5p`) turned on — unlike plain NFSv3, which is faster
  but has no real per-user auth (`no_root_squash` + UID-trust means one
  client can impersonate another's UID) and was rejected for that reason.
  Deferred because it's purely additive on top of what exists — nothing to
  undo. LTSP's own switch is `NFS_HOME=1` + a `FSTAB_HOME` fstab line in
  `ltsp.conf` (`man ltsp-nfs` has the NFSv3 example verbatim), then
  `ltsp initrd` + `ltsp nfs`. The separate, genuinely nontrivial piece is
  standing up a Kerberos KDC and keytabs for the server and every client,
  which doesn't conflict with SSHFS running in the meantime.

  There's a second real bug this could fix, but only if scoped correctly:
  `pamltsp` (`ltsp/client/login/pamltsp` upstream) implements the PAM
  `auth`/`session` phases (SSH to the server) but never the `password`
  phase at all, so a student running `passwd` on the client silently
  rewrites the ephemeral client's own `/etc/shadow` — no effect on the
  server, gone on next reboot either way. Confirmed as a known, upstream
  `wontfix`. Swapping the `/home` *mount protocol* (SSHFS → NFSv4) doesn't
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
  would call, but the "boot the template, update its packages, shut it back
  down" half doesn't exist yet — Todd wants that added later, once the
  create/build split above has actually been exercised on real hardware.

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

- `docs/how-to-server.md` and `docs/how-to-client.md` are Todd's hand-written
  notes, moved out of `src/ltsp_setup/data/`. They were the most accurate
  description of what a real install needs and were the source of truth for
  the port — several things in the bash scripts were stale relative to them
  (Racket 8.15 vs 8.18, the dead `ppa:mmk2410` IntelliJ PPA, the old
  `vscode.list` instead of deb822 `vscode.sources`).

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
