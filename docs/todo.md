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
- [ ] **Cron job: rebuild the image automatically every 2-3 days,
      overnight** (Todd, 2026-08-27). Boot the template, `apt upgrade` it,
      rebuild and publish the image, all unattended. `image refresh` above
      is now the command this would call. Two things to sort out first:
      whether it should publish unattended at all (today's deliberate gate
      says a human looks first), and dpkg lock contention — Mint's
      `apt-daily` timers can hold the lock, and our apt calls fail
      immediately rather than waiting, which is survivable when watching
      and not at 3am. Fix is `-o DPkg::Lock::Timeout=600` on the apt
      helpers in `steps/common.py`.
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

## Done

- [x] **Install the HP LaserJet connected by USB** (2026-08-27). Installed
      as `Lexmark-MS810-Series` on the server, confirmed
      `printer-is-shared=true`. Clients pick it up via the `POST_INIT_CUPS`/
      `POST_INIT_NOCUPSD` lines already live in production's
      `/etc/ltsp/ltsp.conf` (`[clients]` section, ported into the tool's own
      `ltsp.conf` template 2026-08-26) — each client points its
      `/etc/cups/client.conf` at the server's CUPS and masks its own local
      `cups`/`cups-browsed`, so the server's shared printers just show up.
