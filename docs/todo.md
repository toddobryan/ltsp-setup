# Server/infrastructure TODO

Miscellaneous admin tasks for the real server that aren't student-desktop
tweaks (those go in `desktop-polish-todo.md`) and aren't design decisions
(those go in `DECISIONS.md`). Add freely, check off when done.

## Open

(nothing open right now)

## Done

- [x] **Install the HP LaserJet connected by USB** (2026-08-27). Installed
      as `Lexmark-MS810-Series` on the server, confirmed
      `printer-is-shared=true`. Clients pick it up via the `POST_INIT_CUPS`/
      `POST_INIT_NOCUPSD` lines already live in production's
      `/etc/ltsp/ltsp.conf` (`[clients]` section, ported into the tool's own
      `ltsp.conf` template 2026-08-26) — each client points its
      `/etc/cups/client.conf` at the server's CUPS and masks its own local
      `cups`/`cups-browsed`, so the server's shared printers just show up.
