# Development

## Layout

```
custom_components/racktivity_dcmu/   the integration
  snmp.py        self-contained asyncio SNMP v2c client (GET/SET); no runtime dependencies
  pdu.py         OID map and decoding into a PduState dataclass
  http_api.py    read-only client for the PDU's web interface (/Data.php)
  coordinator.py polling: SNMP (live + configuration tiers) and optional web API
  config_flow.py setup, reconfigure, reauth and options flows
  *.py           entity platforms (sensor, binary_sensor, switch, button, event)
tests/           pytest suite on synthetic data; tests/test_live.py is an opt-in hardware test
tools/check.sh   the checks CI runs
assets/          SVG sources of the brand icon
```

## Running the checks

```bash
python -m venv venv && venv/bin/pip install -r requirements_test.txt
tools/check.sh          # ruff lint, ruff format --check, mypy, pytest: exactly what CI runs
```

`check.sh` uses `./venv` or `./.venv` if present, or set `PYTHON=/path/to/python`.

Against a real PDU (read-only; nothing is switched or changed):

```bash
DCMU_LIVE_HOST=<pdu-ip> venv/bin/pytest tests/test_live.py -s
# add DCMU_LIVE_WEB_USER=... DCMU_LIVE_WEB_PASSWORD=... to include the web API
```

The live test checks the decoded values for physical plausibility, which is the only way to
catch a wrong scale factor or OID mapping without a MIB.

## Conventions

- **No real device data in the repo.** Tests use invented data from `tests/synthetic.py`.
  Never commit captures from a PDU, `.har` files, or values, names, IPs or memory dumps taken
  from a real device. `raw/` is gitignored for local captures and notes.
- The web API client is read-only by design: it can only build read requests and refuses the
  flash ranges that hold credentials. Keep it that way.
- The only write the integration makes is the outlet relay via SNMP SET, and only with control
  enabled and a write community set.
- `manifest.json` keys: `domain`, `name`, then alphabetical (hassfest checks this).
- `strings.json` and `translations/en.json` are kept identical.
- Changes go through pull requests; `main` only moves with green CI.

## Device notes

The SNMP agent (`1.3.6.1.4.1.34097`) has quirks worth knowing before changing `pdu.py`:

- A GET with more than about 56 OIDs, or one containing an OID the agent doesn't know, gets
  **no answer at all** (a timeout, not an error). The client chunks requests to 30 and the
  integration only asks for known OIDs; the external sensor table is read in its own request
  so a firmware without it can't break the configuration read.
- A single unknown OID is echoed back with `.0` appended, so responses are mapped by position.
- GETBULK returns at most 20 repetitions; plain GETs are simpler and fast enough.
- Not exposed over SNMP: per-outlet trap enable bits and the outlet schedule.

## Releasing

1. In a pull request, bump `version` in `custom_components/racktivity_dcmu/manifest.json` and
   add a `## [X.Y.Z]` section to [CHANGELOG.md](CHANGELOG.md). A test fails if they don't
   match, so a forgotten bump can't be merged.
2. Merge, then tag: `git tag vX.Y.Z && git push <remote> vX.Y.Z`.
3. On GitHub, *Releases → Draft a new release*: pick the tag, paste the changelog section as
   the notes, publish. HACS offers the update from the release.
