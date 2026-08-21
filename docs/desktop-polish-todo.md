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
- [ ] **DrRacket as the default app for `.rkt` files.** Currently whatever
      Thunar/xdg-mime falls back to. Needs a MIME/xdg-mime default
      association (`.desktop` file is `drracket.desktop`, confirmed present
      — see the panel-launchers work above) rather than an extension-only
      association, since Linux file-type handling goes through MIME types.
      Exact MIME type for `.rkt` not yet confirmed (Racket may not register
      one via `shared-mime-info`; may need adding one).
- [ ] **DrRacket: highlight untested/uncovered code for the teaching
      languages** (`#lang htdp-bsl` and the rest of the HtDP family —
      htdp-bsl+, htdp-isl, htdp-isl+, htdp-asl presumably). This is a
      DrRacket preference, not an OS setting — need to find where DrRacket
      actually stores its preferences (likely under
      `~/.local/share/racket/` or similar, format not yet confirmed) before
      it can be set as a system-wide default the way `dconf`/`xfconf`
      defaults work for the desktop.
- [ ] **DrRacket: default parenthesis-coloring to "Spring."** Same
      preferences-file question as above — likely the same file/mechanism
      as the untested-code-highlighting setting, worth investigating both
      together.
- [ ] **VS Code: install a standard set of extensions globally**, so every
      student has them without needing marketplace/internet access
      individually. Two open questions: which extensions (not yet
      specified — depends on what's actually taught), and the mechanism
      for a genuinely *global* install rather than per-user (VS Code
      normally installs extensions into `~/.vscode/extensions`; needs
      research into a shared/system-wide extensions directory or baking
      them into the image at build time).

## Done

- [x] **Single bottom panel with launchers: Thunar, Chrome, DrRacket,
      Terminal** — **confirmed working 2026-08-21** against a genuinely
      fresh login (wiped `/home/student`, real PXE boot on the production
      bridge, `mint-22.3-xfce-client-2026-08-21`). Template rebuilt from
      the real stock `mint-artwork` structure (recovered via
      `apt-get install --reinstall mint-artwork` after it had been
      overwritten during the first attempt) — single panel, not the
      earlier split top/bottom layout. Launchers reference each app's own
      `.desktop` file directly (`thunar.desktop`, `google-chrome.desktop`,
      `drracket.desktop`, `xfce4-terminal.desktop`) rather than a Mint
      alias. `data/xfce4-panel-default.xml`, tested in `test_desktop.py`.
- [x] **Panel clock shows seconds** — confirmed 2026-08-21 alongside the
      above. Real property is `digital-time-format` (not `digital-format`,
      which silently does nothing on the actual clock plugin), set to
      `%H:%M:%S` on the same clock plugin.

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
three rather than picking one.

**Second correction (2026-08-21):** the first fix above worked — Mint's
panel content stopped winning — but revealed the underlying template itself
was wrong. `data/xfce4-panel-default.xml` had a split top-bar +
auto-hide-bottom-dock layout that predates this whole effort (from
2026-08-19, believed at the time to be "stock Mint," never actually
verified against a real fresh login). A real fresh login showed exactly
that split layout, which Todd didn't want. `apt-get install --reinstall
mint-artwork` recovered the real, unmodified stock file (single bottom
panel, `whiskermenu`/`showdesktop`/launchers/`tasklist`/systray/clock all
together) — the template has been rebuilt from that real structure instead
of the old split-panel one, keeping only the launcher and clock changes.
Also corrected: the clock plugin's real property is
`digital-time-format`, not `digital-format` (which doesn't exist and was
silently ignored), and the terminal launcher is `xfce4-terminal.desktop`,
not the `xfce4-terminal-emulator.desktop` alias. **Rebuilding the image
now; not confirmed working against a real fresh login yet.**
