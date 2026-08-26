# Desktop/user-settings polish list

Running list of tweaks to the student desktop experience, found while
testing the two real lab machines against `mint-22.3-xfce-client-2026-08-20`
and later builds. Unlike `docs/DECISIONS.md` (why things are the way they
are, what's verified), this is just a working checklist — add to it freely,
check items off as they're fixed and confirmed, delete items that turn out
not to matter.

System-wide settings (same for every account) are applied by
`steps/common.py::configure_dconf` / `configure_autostart` /
`configure_racket_mime`, run as part of the `desktop` stage. Per-student
settings (panel, keyboard layout, DrRacket prefs) go through
`steps/students.py::configure_skel`/`apply_defaults`/`reset_defaults`
instead — see `docs/DECISIONS.md`, "Student default configuration".

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
- [ ] **VS Code: install a standard set of extensions globally**, so every
      student has them without needing marketplace/internet access
      individually. Two open questions: which extensions (not yet
      specified — depends on what's actually taught), and the mechanism
      for a genuinely *global* install rather than per-user (VS Code
      normally installs extensions into `~/.vscode/extensions`; needs
      research into a shared/system-wide extensions directory or baking
      them into the image at build time).

## Done

- [x] **DrRacket: highlight untested/uncovered code** (2026-08-26). The
      `plt:framework-pref:drracket:language-settings` vector's last field
      controls this: `debug` (the value htdp/bsl defaulted to) doesn't
      highlight untested code, `test-coverage` does. Confirmed by Todd after
      changing it in DrRacket's own dialog. Only that one field changed in
      `racket-prefs-default.rktd` -- a same-session diff also showed a batch
      of unrelated changes (a `defs/ints-labels` toggle, the language-picker
      dialog's remembered tree position, an extra `recent-language-names`
      entry, window-geometry entries for a second resolution, and personal
      file-history pointing at `/home/student/Desktop/file.rkt`) that Todd
      asked to leave out of the template.
- [x] **Keyboard layout switcher (Dvorak).** Todd uses Dvorak; students get
      standard US qwerty by default with a one-click switch via the `xkb`
      panel plugin (id `16`, right of the expanding separator, left of the
      systray — `xfce4-xkb-plugin` is already part of stock Mint XFCE, no
      new package needed). Lives in `data/keyboard-layout-default.xml`,
      written only to the standard system-wide xfconf-default path — no
      `mint-artwork` override exists for this channel (checked directly via
      `dpkg -L`, unlike the panel).

      **Correction (2026-08-24):** the first variant, `alt-intl`, was wrong
      — it puts `dead_acute`/`dead_diaeresis` on the *base* level of the
      quote/apostrophe key (confirmed by reading
      `/usr/share/X11/xkb/symbols/us` directly), so a plain `"` silently
      became a dead key waiting for a second keystroke instead of typing a
      quote. Switched to `altgr-intl`, which keeps the literal character on
      the base level and puts the dead key behind AltGr (Right-Alt+`"` for
      an umlaut, plain `"` for a quote) — the Dvorak variant didn't need to
      change, since plain `us(dvorak)` already had it right for that key.
      Also dropped the `compose:ralt` XkbOption, which was fighting with
      AltGr for the same physical key. Todd tested both layouts live and
      confirmed correct 2026-08-24; config captured verbatim from his
      tested session rather than re-derived.

      **Correction (2026-08-25):** the `alt-intl`/`altgr-intl` fix above was
      necessary but not sufficient — a genuinely fresh skel-provisioned
      account still showed only one layout, nothing to switch to. Root
      cause: `XkbLayout` in the template was `type="empty"` (no value at
      all), while `XkbVariant` had two comma-separated entries — the plugin
      needs a matching two-item `XkbLayout` (`us,us`) to have two groups to
      cycle between. Fixed and confirmed working against a fresh account by
      Todd.

- [x] **Single bottom panel with launchers: Thunar, Chrome, DrRacket, VS
      Code, Terminal** — **confirmed working 2026-08-21** against a
      genuinely fresh login (wiped `/home/student`, real PXE boot on the
      production bridge, `mint-22.3-xfce-client-2026-08-21`). Template
      rebuilt from the real stock `mint-artwork` structure (recovered via
      `apt-get install --reinstall mint-artwork` after it had been
      overwritten during the first attempt) — single panel, not the
      earlier split top/bottom layout. Launchers reference each app's own
      `.desktop` file directly (`thunar.desktop`, `google-chrome.desktop`,
      `drracket.desktop`, `code.desktop`, `xfce4-terminal.desktop`) rather
      than a Mint alias. `data/xfce4-panel-default.xml`, tested in
      `test_students.py`. VS Code launcher added 2026-08-25, positioned
      after DrRacket and before the terminal to match Todd's live edit.
- [x] **Panel clock shows seconds** — confirmed 2026-08-21 alongside the
      above. Real property is `digital-time-format` (not `digital-format`,
      which silently does nothing on the actual clock plugin), set to
      `%H:%M:%S` on the same clock plugin.
- [x] **DrRacket as the default app for `.rkt` files** (2026-08-25).
      `application/x-racket` is a real registered MIME type
      (`/usr/share/mime/packages/racket.xml` — already shipped, not
      Racket's own doing), so this only needed a default-app mapping:
      `steps/common.py::configure_racket_mime` writes that MIME type plus
      `/etc/xdg/mimeapps.list` (`application/x-racket=drracket.desktop`).
      System-wide, not per-student, since which app opens a `.rkt` file
      isn't something a student should need to customize — requires an
      image rebuild to reach clients.
- [x] **DrRacket: default parenthesis-coloring to "Spring"** (2026-08-25).
      Preferences live in `~/.config/racket/racket-prefs.rktd`, a flat
      Racket association list — `framework:paren-color-scheme` is the key.
      Per-student, via `/etc/skel` like the panel/keyboard defaults
      (`steps/students.py`, `data/racket-prefs-default.rktd`), with the
      same kind of property-level three-way merge as the xfconf files
      (`steps/racket_prefs.py`) so a later default change doesn't get
      blocked by an unrelated student customization, or vice versa.

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
