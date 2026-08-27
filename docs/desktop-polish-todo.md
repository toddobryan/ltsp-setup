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

- [ ] **VS Code: install a standard set of extensions globally**, so every
      student has them without needing marketplace/internet access
      individually. Two open questions: which extensions (not yet
      specified — depends on what's actually taught), and the mechanism
      for a genuinely *global* install rather than per-user (VS Code
      normally installs extensions into `~/.vscode/extensions`; needs
      research into a shared/system-wide extensions directory or baking
      them into the image at build time).

- [ ] **Chrome: cache size + redirect off NFS-mounted home** (flagged again
      2026-08-26; originally noted in `DECISIONS.md` 2026-08-19 as the
      concern that motivated the whole NFSv3-vs-SSHFS-vs-NFSv4+Kerberos
      timing-test question, never resolved). Chrome's cache currently lives
      inside the NFS-mounted profile directory, so every cache read/write
      goes over the network — the likely cause of Chrome being slow to
      open when many students launch it at once, and of unbounded growth
      eating into each student's NFS-homed quota. Proposed fix: a Chrome
      managed policy (`/etc/opt/chrome/policies/managed/*.json`) setting
      `DiskCacheDir` to local/tmpfs storage and `DiskCacheSize` to a fixed
      cap, while leaving the actual profile (bookmarks, cookies, history)
      on NFS so it stays persistent across sessions. Not yet implemented or
      tested. Todd's aside (2026-08-26): wishes this year's old home
      directories had been sized up (`du -sh`) before `remove-stale`
      deleted them — would have shown exactly what was eating disk/network.
      Worth having `students.remove_all()` capture that automatically next
      time, alongside the file-count announcement it already does per
      account before deleting.

- [x] **Student home directory permissions** (checked 2026-08-26, real
      accounts). `useradd -m`'s Debian/Ubuntu defaults (`UMASK=022` +
      per-user private groups + `adduser.conf`'s `DIR_MODE=0750`) already
      produce `drwxr-x---` homes — a student not deliberately attacking the
      system cannot `cd`/`ls` into another student's home at all. Confirmed
      on real created accounts (`tbelt30`, `v1kakarl30`, `student`,
      `sysadmin`). One much lower-stakes note: `/home` itself is `0755`
      (world-listable), so `ls /home` shows every username, just not file
      contents — not fixed, probably not worth it. This is about casual/
      accidental access only; deliberate attacks (a student with root on
      their own client, or their own device on the LTSP network segment)
      are a separate, harder problem — see `DECISIONS.md`'s NFSv3 section.

- [ ] **xfwm4 window theme: Kokodi** (added 2026-08-26). Wider grab areas
      around window edges than the stock theme, easier to resize windows
      with. `steps/students.py`'s `RESETTABLE_DEFAULTS` now maps
      `xfwm4.xml` -> `data/xfwm4-default.xml` (just the one `theme`
      property, same minimal style as `keyboard-layout-default.xml`), same
      per-student `/etc/skel` + property-level merge mechanism as the panel
      and keyboard layout. Not yet confirmed against a real fresh login.

## Done

- [x] **GNOME keyring / login password mismatch** (2026-08-26). After a
      server-side password change, Chrome (and anything else touching the
      keyring) prompted with a mismatch dialog the student had to Cancel
      through repeatedly. Root cause: an admin-driven `passwd` reset has no
      way to re-encrypt the student's existing keyring (that needs the
      *old* password), so it's left permanently locked. Fixed not by
      chasing the SSSD-based real-account fix once flagged here, but by
      making the reset itself clear the stale keyring:
      `ltsp-setup student reset-password <username>` runs `passwd`
      interactively, then deletes `~/.local/share/keyrings`, so GNOME
      builds a fresh one — auto-unlocked with the new password — at the
      next login (`steps/students.py::reset_password`).
- [x] **Chrome's stale singleton lockfile** (2026-08-26). Real recurring
      problem last school year: a session ending uncleanly leaves
      `~/.config/google-chrome/Singleton{Lock,Cookie,Socket}` behind, and
      the next login's Chrome silently exits trying to hand off to that
      "existing" instance -- no error, no window, just nothing when you
      click the launcher. `steps/common.py::configure_chrome_singleton_cleanup`
      removes those three files at every session start, before Chrome ever
      runs (`data/chrome-singleton-cleanup.sh`, run via an XFCE autostart
      entry). Only safe because of the concurrent-login lock added the same
      day (`configure_session_lock`) -- without it, a second still-active
      session on another client would leave a *real*, non-stale lock, and
      unconditionally deleting it would break that other session.
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
