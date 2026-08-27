# LTSP Setup

Scripts to set up an LTSP server and its client image on fresh installs of
Linux Mint 22.3 (Zena), plus a libvirt lab for testing the whole thing in two
VMs before touching real hardware.

## What it does

Everything runs through one command, `ltsp-setup`, which has three groups:

- `ltsp-setup lab ...` runs on your workstation and manages the test VMs.
- `ltsp-setup server ...` runs on the machine that becomes the LTSP server.
- `ltsp-setup client ...` runs on the machine that becomes the client template.

**Every command defaults to a dry run.** It prints the exact commands it would
run and the exact contents of every file it would write, and changes nothing.
Add `--no-debug` when you actually mean it.

```bash
ltsp-setup server start                 # shows you the whole plan
sudo ltsp-setup server start --no-debug # does it
```

## How a setup survives reboots

Installing a desktop, a kernel and LTSP takes several reboots, so the work is
split into stages:

```
$ ltsp-setup plan --role server
1. networking — hostname, /etc/hosts and a static address on the LTSP NIC
2. mirrors — point apt at our mirrors and upgrade everything  (reboots)
3. apps — Java, Racket, Chrome, VS Code and Rust
4. ltsp — LTSP server, dnsmasq, NFS and Epoptes  (reboots)
5. desktop — system-wide desktop defaults  (reboots)
```

`server start` installs a systemd oneshot unit, `ltsp-setup.service`, which
runs at boot and picks up where the last stage left off. Progress lives in
`/var/lib/ltsp-setup/state.json`. When the last stage finishes, the unit
disables and removes itself.

Watch it with `journalctl -fu ltsp-setup`. Re-run a single stage with
`sudo ltsp-setup server stage ltsp --no-debug`.

## Settings

Defaults are in `src/ltsp_setup/config.py`. Override any of them in a TOML
file, passed with `--config` or found automatically at `./ltsp-setup.toml` or
`/etc/ltsp-setup.toml`. See `examples/lab.toml` and `examples/school.toml`.

`ltsp-setup config` prints the settings actually in force.

### Interfaces are matched by MAC, not by name

Interface names come from PCI enumeration order, so they differ between the
test VM and the real server and can move when a card is reseated. Set
`mac_for_internet` and `mac_for_ltsp` and netplan will match on those and
rename the interface to whatever `nic_for_internet` / `nic_for_ltsp` say. The
lab assigns fixed MACs to the server VM for exactly this reason.

## The test lab

The Mint ISO is a live image driven by Ubiquity, which does not preseed
reliably, so the golden image is built by hand once and then cloned:

```bash
# One time: click through a normal Mint install.
ltsp-setup lab build-golden --no-debug
```

In the installer, the username must be `sysadmin` (or whatever `admin_user`
says). Everything else can be default. Afterwards, install `openssh-server`,
`git`, and `python3-venv` — none of the three are on the ISO, and all three
are needed before anything else (SSH access, cloning this repo, and `python3
-m venv .venv`, which otherwise fails silently with no `.venv/bin/` at all)
— then shut down and freeze the disk:

```bash
sudo apt update && sudo apt install -y openssh-server git python3-venv
```

```bash
sudo chmod 444 /var/lib/libvirt/images/mint-22.3-fresh.qcow2
virsh --connect qemu:///system undefine mint-22.3-fresh
```

The golden disk is the copy-on-write **backing file** for both VMs, so booting
it again would corrupt every clone. Undefining the domain prevents that.

**Worth doing before you freeze it, not after:** every clone (server,
client-template, client) currently repeats the same one-time dance —
authorize an SSH key for repeated automation access, add a scoped
`NOPASSWD` sudoers entry, `git clone` this repo, and build the dev venv —
because a fresh overlay inherits none of it from the golden image. Doing
all four once here, before freezing, saves redoing them per clone. The SSH
key and sudo entry are fine to bake in for a lab-only image that's never
used for the real production install (isolated network, your own
workstation) — the `git clone` will still need a `git pull &&
.venv/bin/pip install -e ".[dev]"` on each clone to catch up to whatever's
changed since the golden was frozen, but at least the clone and venv
machinery are already there.

Then, as often as you like:

```bash
ltsp-setup lab create-server --no-debug   # ~1 second
ltsp-setup lab create-client --no-debug
ltsp-setup lab reset ltsp-server --no-debug   # throw it away, start clean
ltsp-setup lab status
```

Two networks are involved. `default` is libvirt's NAT network and gives the
server its route to the internet. `ltsp` is an isolated switch with **no
libvirt DHCP of its own** — the LTSP server is the only thing answering DHCP
there, which is what makes PXE boot deterministic.

## Development

```bash
poetry install
poetry run pytest
poetry run mypy
poetry run black src tests
```
