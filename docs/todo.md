# Server/infrastructure TODO

Miscellaneous admin tasks for the real server that aren't student-desktop
tweaks (those go in `desktop-polish-todo.md`) and aren't design decisions
(those go in `DECISIONS.md`). Add freely, check off when done.

## Open

- [ ] **A one-command way to edit and rebuild the client image** (Todd,
      2026-08-27). Today, a routine content tweak means: manually starting
      the template VM, SSHing in (no saved shortcut for its IP), running the
      checkout/venv dance by hand, running whichever stage(s) changed,
      `client cleanup`, shutting the VM down, then remembering the exact
      `image build`/`image prune` invocations (`--no-debug`, `--config
      .../examples/school.toml`) from scratch each time. Wanted: a command
      that boots the template, drops into an interactive session there for
      Todd to run whatever's needed, and on exit automatically shuts it
      down, runs `image build`, and runs `image prune` — no options to
      remember. See `DECISIONS.md`'s "Overnight rebuild-and-reimage cron
      job" entry: this is also the missing piece that entry was waiting on.
- [ ] **Cron job: rebuild the image automatically every 2-3 days,
      overnight** (Todd, 2026-08-27). Boot the template, `apt upgrade` it,
      rebuild and publish the image, all unattended. Depends on the item
      above existing first — specifically its "update the template's
      packages with nobody at the console" half.

## Done

- [x] **Install the HP LaserJet connected by USB** (2026-08-27). Installed
      as `Lexmark-MS810-Series` on the server, confirmed
      `printer-is-shared=true`. Clients pick it up via the `POST_INIT_CUPS`/
      `POST_INIT_NOCUPSD` lines already live in production's
      `/etc/ltsp/ltsp.conf` (`[clients]` section, ported into the tool's own
      `ltsp.conf` template 2026-08-26) — each client points its
      `/etc/cups/client.conf` at the server's CUPS and masks its own local
      `cups`/`cups-browsed`, so the server's shared printers just show up.
