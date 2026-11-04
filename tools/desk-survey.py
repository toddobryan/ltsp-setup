#!/usr/bin/env python3
"""Record one lab computer: its number, MAC, hardware, and which monitor is left.

Run from a terminal in a desktop session at the desk. It writes
machines/<mac>--<user>.json next to this script, on the shared NFS /home. Each
person gets their own file because the sticky directory stops anyone replacing
another person's record. --csv keeps the newest record for each machine.

    python3 desk-survey.py          survey this desk
    python3 desk-survey.py --csv    print every saved record as CSV

Uses only the standard library, xrandr and ip. LAB_SYS replaces /sys for testing.
"""
import csv
import getpass
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

SYS = Path(os.environ.get("LAB_SYS", "/sys"))
OUT_DIR = Path(__file__).resolve().parent / "machines"
SERVER_IP = "192.168.67.1"
DIM = "0.35"
COMPUTERS = range(1, 31)
LAST_DUAL_MONITOR = 24  # computers after this one have a single monitor


def read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def edid_text(edid, tag):
    """Return a text descriptor from a base EDID block (name or serial)."""
    for start in range(54, 126, 18):
        block = edid[start : start + 18]
        if len(block) == 18 and block[:3] == b"\0\0\0" and block[3] == tag:
            return block[5:].split(b"\n")[0].decode("ascii", "replace").strip()
    return ""


def monitors():
    """Return a dict for each connected monitor, from sysfs."""
    found = []
    for path in sorted((SYS / "class/drm").glob("card*-*")):
        if read(path / "status") != "connected":
            continue
        try:
            edid = (path / "edid").read_bytes()
        except OSError:
            edid = b""
        found.append(
            {
                "connector": re.sub(r"^card\d+-", "", path.name),
                "edid_sha1": hashlib.sha1(edid).hexdigest() if edid else "",
                "model": edid_text(edid, 0xFC),
                "serial": edid_text(edid, 0xFF),
            }
        )
    return found


def ports():
    """Return every video connector the graphics hardware reports."""
    return sorted(
        re.sub(r"^card\d+-", "", path.name)
        for path in (SYS / "class/drm").glob("card*-*")
        if (path / "status").exists()
    )


def network():
    """Return (interface, ip, mac) for the route to the LTSP server."""
    text = subprocess.run(
        ["ip", "-o", "route", "get", SERVER_IP],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    iface = re.search(r"\bdev (\S+)", text).group(1)
    ip = re.search(r"\bsrc (\S+)", text).group(1)
    return iface, ip, read(SYS / "class/net" / iface / "address").lower()


def xrandr_name(connector):
    """Map a sysfs connector name to the name xrandr uses."""
    text = subprocess.run(
        ["xrandr", "--query"], capture_output=True, text=True, check=True
    ).stdout
    names = re.findall(r"^(\S+) (?:dis)?connected", text, re.M)
    for name in (connector, connector.replace("-A-", "-")):
        if name in names:
            return name
    raise SystemExit(f"xrandr has no output for {connector}; it lists {names}")


def brightness(output, value):
    subprocess.run(["xrandr", "--output", output, "--brightness", value], check=True)


def ask_left(pair):
    """Dim the first monitor and ask which side it is on. Returns the left one."""
    first, second = pair
    output = xrandr_name(first["connector"])
    other = xrandr_name(second["connector"])
    try:
        brightness(output, DIM)
        time.sleep(0.5)
        print(f"\nOne monitor should now be dim ({output}).")
        while True:
            reply = input("Dim monitor is on the [l]eft, [r]ight, or [n]ot sure? ")
            reply = reply.strip().lower()[:1]
            if reply == "l":
                return first, second
            if reply == "r":
                return second, first
            if reply == "n":
                return None
    finally:
        brightness(output, "1")
        brightness(other, "1")


def confirm(question):
    return input(f"{question} [y/n] ").strip().lower().startswith("y")


def ask_computer(mac):
    """Ask for the number on this desk, refusing typos and unconfirmed repeats."""
    while True:
        reply = input(f"Computer number ({COMPUTERS[0]}-{COMPUTERS[-1]}): ").strip()
        if not reply.isdecimal() or int(reply) not in COMPUTERS:
            print("That isn't a computer number.")
            continue
        number = int(reply)
        taken = [r["mac"] for r in records() if r.get("computer") == number]
        taken = [other for other in taken if other != mac]
        if not taken or confirm(f"Computer {number} is already {taken[0]}. Use it?"):
            return number


def records():
    found = []
    for path in sorted(OUT_DIR.glob("*.json")):
        try:
            found.append(json.loads(path.read_text()))
        except (OSError, ValueError):
            print(f"Skipping unreadable {path.name}", file=sys.stderr)
    return found


def survey():
    found = monitors()
    iface, ip, mac = network()
    if not mac:
        raise SystemExit(f"No MAC address found for {iface}")
    user = getpass.getuser()
    path = OUT_DIR / f"{mac.replace(':', '-')}--{user}.json"
    print(f"{socket.gethostname()}  {mac}  {ip}")
    for mon in found:
        print(f"  {mon['connector']}: {mon['model']} {mon['edid_sha1'][:6]}")
    if path.exists():
        print("You already surveyed this machine; saving will replace that.")

    computer = ask_computer(mac)
    expected = 2 if computer <= LAST_DUAL_MONITOR else 1
    if len(found) != expected:
        print(f"Computer {computer} should have {expected} monitor(s), found {len(found)}.")
        if not confirm("Save anyway?"):
            print("Nothing was saved.")
            return

    left = right = None
    if len(found) == 2:
        order = ask_left(found)
        if order is None:
            print("Left and right were not recorded.")
        else:
            left, right = order

    record = {
        "computer": computer,
        "user": user,
        "hostname": socket.gethostname(),
        "mac": mac,
        "ip": ip,
        "interface": iface,
        "vendor": read(SYS / "class/dmi/id/sys_vendor"),
        "product": read(SYS / "class/dmi/id/product_name"),
        "ports": ports(),
        "monitors": found,
        "left_edid": left["edid_sha1"] if left else "",
        "right_edid": right["edid_sha1"] if right else "",
        "left_connector": left["connector"] if left else "",
        "right_connector": right["connector"] if right else "",
        "recorded": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    OUT_DIR.mkdir(exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(record, indent=2) + "\n")
    temp.chmod(0o644)
    temp.replace(path)
    print("Saved. Thank you! You can close this window.")


def export_csv():
    fields = [
        "computer", "hostname", "mac", "ip", "vendor", "product",
        "left_connector", "left_edid", "right_connector", "right_edid",
        "monitor_count", "ports", "recorded",
    ]  # fmt: skip
    by_mac = {}
    for record in sorted(records(), key=lambda r: r["recorded"]):
        by_mac.setdefault(record["mac"], []).append(record)
    rows = []
    for mac, group in by_mac.items():
        # Prefer the newest record that actually says which monitor is left.
        known = [r for r in group if r["left_edid"]]
        rows.append(dict((known or group)[-1], monitor_count=len(group[-1]["monitors"])))
        rows[-1]["ports"] = " ".join(group[-1].get("ports", []))
        answers = {(r.get("computer"), r["left_edid"]) for r in known}
        if len(answers) > 1:
            print(f"Records disagree for {mac}: {sorted(answers)}", file=sys.stderr)
    rows.sort(key=lambda r: r.get("computer", 0))
    numbers = [r.get("computer") for r in rows]
    for number in sorted({n for n in numbers if numbers.count(n) > 1}):
        print(f"Computer {number} is on more than one machine", file=sys.stderr)
    writer = csv.DictWriter(sys.stdout, fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    missing = sorted(set(COMPUTERS) - {r.get("computer") for r in rows})
    if missing:
        print(f"Not surveyed yet: {missing}", file=sys.stderr)


if __name__ == "__main__":
    try:
        export_csv() if "--csv" in sys.argv[1:] else survey()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled; nothing was saved.")
        sys.exit(1)
