# Server/infrastructure TODO

Miscellaneous admin tasks for the real server that aren't student-desktop
tweaks (those go in `desktop-polish-todo.md`) and aren't design decisions
(those go in `DECISIONS.md`). Add freely, check off when done.

## Open

- [ ] **A one-command way to edit and rebuild the client image** (Todd,
      2026-08-27) — **implemented 2026-09-09 as `ltsp-setup image refresh`,
      not yet run for real.** Boots the template, re-clones and re-bootstraps
      this tool on it over SSH, runs the requested client stages
      (`--stage`, default `mirrors`), strips the tooling back off, shuts the
      VM down and builds. Uses only sudoers rules the template already had,
      so nothing new is granted (and nothing new ships to the clients).
      Deliberately stops before publishing — `set-default` and `prune` stay
      separate, per "once we're sure it works". One difference from the
      original wish: it runs *named stages* rather than dropping into an
      interactive shell, because the same code path has to work unattended
      for the cron job below. Leave this open until a real run confirms it.
- [ ] **Weekly unattended rebuild** (Todd, 2026-08-27, scoped 2026-09-12) —
      **implemented 2026-09-15, not yet run for real.** `ltsp-setup image
      schedule` installs a systemd timer that runs `image refresh --publish`
      at `image_refresh.on_calendar` (Saturday 02:00 by default, with a
      30-minute randomised delay). Leave open until a weekend run has
      actually happened; see "What to check after the first weekend run"
      below.

      The "should it publish unattended at all?" question resolved to *yes,
      but only behind a real test*: `publish_image` sets `DEFAULT_IMAGE`,
      netboots `pxe-test-client` against it, and puts the old image straight
      back if the client doesn't come up. The human gate didn't disappear —
      it was replaced by something that can run at 2am. `image prune` now
      also keeps one superseded build by default
      (`image_refresh.keep_rollback_images`), so reverting by hand is
      `image set-default <name>` and a reboot rather than an hour-long
      rebuild.

      dpkg lock contention is fixed: every `apt-get` this tool runs now
      carries `-o DPkg::Lock::Timeout=` (`Settings.apt_lock_timeout_s`,
      600s), so an `apt-daily` timer holding the lock delays a rebuild
      instead of failing it.
- [ ] **Add `openssh-server` to the client image** (2026-09-09). There is
      currently no way to reach a running thin client from the server:
      `CLIENT_PACKAGES` doesn't include it, and `nc -z` against all six
      live clients confirmed port 22 closed. Came up wanting to shut the
      clients down remotely before a server reboot, which turned out to be
      impossible. Worth weighing the tradeoff first — sshd on every client
      is also more attack surface on a network students have physical
      access to, so key-only auth (no passwords) should probably come with
      it.
- [ ] **Work out why Epoptes can't shut clients down** (2026-09-09). Todd:
      "I can't kill them with Epoptes, either." Not a missing-agent
      problem — the server had 219 established connections on port 789 at
      the time, so the clients' `epoptes-client` agents are connecting
      fine. So it's likely configuration or permissions (the admin account
      needs to be in the `epoptes` group, and the agent needs to be running
      with enough privilege to power the machine off). Epoptes is the
      purpose-built tool for this and is already installed on both ends, so
      this may be a better answer than sshd above, or a complement to it.

## What to check after the first weekend run

The whole pipeline is written and unit-tested but has never run end to end
against the real lab. In rough order of how likely each is to be the thing
that breaks:

- [ ] **`image refresh` has still never completed a real run.** Its first
      attempt (2026-09-09) died on SSH auth; the fix is committed but
      unverified. The timer can't work until this does.
- [ ] **Does `epoptes-client` really connect at boot, before anyone logs
      in?** The smoke test depends on it. The evidence it was designed
      against is circumstantial — established connections on port 789 from
      clients sitting at the greeter — not a watched cold boot. If it turns
      out to connect only at login, the smoke test needs a different
      signal and will fail every run until it gets one.
- [ ] **Does `pxe-test-client` get a fresh DHCP lease each boot?** The
      lease check compares expiry timestamps, on the assumption that a
      booting client always renews. A client that reuses an unexpired lease
      without touching dnsmasq would time out at stage one.
- [ ] **Check the new image's kernel count and size.** `--stage mirrors`
      now runs `apt autoremove --purge` and `purge_old_kernels` after the
      upgrade. The expected steady state is *two* kernels in the image (the
      one the template booted, plus the one the upgrade installed), not one:
      the running kernel is never removed, and it becomes removable on the
      next run once GRUB has booted the newer one. If the count keeps
      climbing, something about that assumption is wrong.
- [ ] **Run it by hand first**: `sudo ltsp-setup image smoke-test --no-debug`
      against the image that's already live. It should pass in a few
      minutes. That isolates the smoke test from the rebuild, so a failure
      on Saturday morning is unambiguous.

## Worth doing sometime

- [ ] **The server itself has 15 kernel versions installed** (noticed
      2026-09-15, ~58 packages). `purge_old_kernels` would take 14 of them
      and keep the running `7.0.0-31`, but nothing calls it against the
      server outside `server stage mirrors`, which also rewrites
      sources.list and runs a full upgrade — far more than is wanted here.
      Either a small `ltsp-setup server purge-kernels`, or just do it by
      hand once.

## Done

- [x] **Install the HP LaserJet connected by USB** (2026-08-27). Installed
      as `Lexmark-MS810-Series` on the server, confirmed
      `printer-is-shared=true`. Clients pick it up via the `POST_INIT_CUPS`/
      `POST_INIT_NOCUPSD` lines already live in production's
      `/etc/ltsp/ltsp.conf` (`[clients]` section, ported into the tool's own
      `ltsp.conf` template 2026-08-26) — each client points its
      `/etc/cups/client.conf` at the server's CUPS and masks its own local
      `cups`/`cups-browsed`, so the server's shared printers just show up.
