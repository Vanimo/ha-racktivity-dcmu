# Notes for AI assistants

Home Assistant custom integration (HACS) for the Racktivity DCMU PDU.
Code in `custom_components/racktivity_dcmu/`, tests in `tests/`, user docs in `README.md`.

- Run `tools/check.sh` before committing; it is exactly what CI runs (ruff, mypy, pytest).
  `main` only changes through pull requests with green CI.
- Never commit real device data: `raw/` (gitignored captures), `.har` files, or values, names,
  IPs or memory dumps from a real PDU. Tests use invented data from `tests/synthetic.py`.
- The device may be in production. Never send SNMP SETs or web API writes to a real PDU
  unless the user explicitly asks. The web API client is read-only by design; keep it so.
- Releasing: bump `version` in `manifest.json` **and** add a `## [X.Y.Z]` section to
  `CHANGELOG.md` in the same PR (a test checks they match). After merging, the user tags
  and creates the GitHub release; don't push tags yourself.
- `manifest.json` keys: `domain`, `name`, then alphabetical. Keep `strings.json` and
  `translations/en.json` identical.
