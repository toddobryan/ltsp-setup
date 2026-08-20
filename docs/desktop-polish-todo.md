# Desktop/user-settings polish list

Running list of tweaks to the student desktop experience, found while
testing the two real lab machines against `mint-22.3-xfce-client-2026-08-20`
and later builds. Unlike `docs/DECISIONS.md` (why things are the way they
are, what's verified), this is just a working checklist — add to it freely,
check items off as they're fixed and confirmed, delete items that turn out
not to matter.

Most of this kind of setting is applied by `steps/common.py::configure_dconf`
/ `configure_panel_defaults` / `configure_autostart`, run as part of the
`client` plan's `desktop` stage.

## Open

- [ ] **Chrome's stale singleton lockfile.** Recurring problem last school
      year: a student's session ending uncleanly leaves
      `~/.config/google-chrome/Singleton{Lock,Cookie,Socket}` behind: NFS
      home + fresh login means any leftover lock is always stale, so
      clearing it at session start should be safe. See `docs/DECISIONS.md`
      → "Deferred, deliberately" for the full writeup.
- [ ] **GNOME keyring / login password mismatch.** After a server-side
      password change, Chrome (and anything else touching the keyring)
      prompts with a mismatch dialog the student has to Cancel through
      repeatedly. Root cause is `pamltsp` missing the PAM `password` phase
      — same underlying issue as the `passwd`-does-nothing bug, real fix is
      SSSD. See `docs/DECISIONS.md`.

## Done

- [x] **Bottom-dock panel launchers: Thunar, Chrome, DrRacket, Terminal**
      (2026-08-20). Replaced the previous set (terminal, file-manager,
      web-browser, appfinder) with these four, in this order, referencing
      each app's own `.desktop` file directly (`thunar.desktop`,
      `google-chrome.desktop`, `drracket.desktop`,
      `xfce4-terminal-emulator.desktop`) rather than Mint's generic
      `xfce4-web-browser.desktop`/`xfce4-file-manager.desktop` aliases, so
      it's not dependent on whatever's currently set as the system default.
      `data/xfce4-panel-default.xml`, tested in `test_desktop.py`.
- [x] **Panel clock shows seconds** (2026-08-20), so a frozen/dead client is
      easy to spot at a glance. `digital-format="%a %I:%M:%S %p"` on the
      clock plugin in the same file.

Note: this system default only applies to sessions that have never
initialized their own panel config. An already-logged-in account (like
`sysadmin` on the template) keeps its own `~/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml`
until that file is deleted so XFCE re-seeds from the default — real student
accounts get it automatically since they've never logged in before.

**Correction (2026-08-20):** the panel-launchers/clock items above were
marked done too early. A genuinely fresh login (wiped `/home/student`, PXE
booted a real client on the production network) still showed Mint's stock
panel — Firefox launcher and all — even though `/etc/xdg/xfce4/panel/default.xml`
had our content. Turns out that file isn't the only (maybe not even the
real) source: Mint ships its own separate XFCE panel override via the
`mint-artwork` package at
`/usr/share/mint-artwork/xfce/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml`,
confirmed to contain the Firefox reference. `configure_panel_defaults` now
writes the same content to that path *and* the standard xfconf
system-wide-default location (`/etc/xdg/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml`,
found completely empty on this machine) as well as the original file — the
exact chain Mint uses between them wasn't fully traced, so this covers all
three rather than picking one. **Rebuilding the image now; not confirmed
working against a real fresh login yet.**
