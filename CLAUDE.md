# ltsp-setup

Scripts to set up an LTSP server and client image on fresh Linux Mint 22.3
(Zena) installs, plus a libvirt lab for testing in two VMs.

**Read `docs/DECISIONS.md` before making changes.** It records why the current
design is the way it is, what has and has not been tested, three bugs found in
the previous implementation, and the one significant feature still missing
(building the client netboot image).

## Conventions

- **Everything defaults to a dry run.** `--no-debug` is required for a real
  run. Preserve this when adding commands.
- **`runner.py` is the only place that executes commands or touches disk.**
  No module may call `subprocess` or write files directly. This is what makes
  the dry run trustworthy — do not work around it.
- **Commands are argument lists, never shell strings.** `Runner.run` takes a
  list and never uses `shell=True`. `Runner.run_shell` exists for genuine
  pipelines only.
- **Config goes in `config.py` as a frozen dataclass field with a default**,
  overridable from TOML. Do not hardcode site-specific values in step modules.
- **Text files dropped onto machines are `string.Template` files in
  `src/ltsp_setup/data/`**, rendered via `templates.render`. A missing
  placeholder raises rather than silently producing a half-filled config.
- Stage names in `plans.py` are persisted in `/var/lib/ltsp-setup/state.json`.
  Renaming one makes already-configured machines re-run it.

## Checks

Dependencies live in a project-local venv (`python3 -m venv .venv`, then
`.venv/bin/pip install -e ".[dev]"`).

```bash
.venv/bin/pytest
.venv/bin/mypy
.venv/bin/black src tests
```

All three must be clean. mypy runs in strict mode.

## Reviewing a change without a machine

```bash
ltsp-setup plan --role server
ltsp-setup server start --no-reboot     # whole plan, prints every command and file
ltsp-setup config                       # settings actually in force
```
