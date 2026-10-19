# Racktivity DCMU for Home Assistant

Custom integration for the **Racktivity DCMU / EnergySwitch PM0816** 8-outlet PDU
(hardware 2.02, firmware 3.00; the SNMP agent reports `DCMU_8port`). The vendor is
gone and there is no published MIB; everything here was worked out from the device's web
UI and its SNMP values.

- **SNMP v2c** (primary): voltage, frequency, per-outlet current / power / apparent power /
  power factor / energy, relay states, internal temperature and humidity, peaks, limits.
- **Web API** (optional, read-only): only values SNMP doesn't have: lifetime (non-resettable)
  energy, firmware/hardware version, external temperature probes, airflow, intrusion
  inputs, device clock, and the device's event log.
- **Relay control** (optional, off by default): SNMP SET with the write community.

No settings are ever changed on the PDU. The only write the integration can make is switching
an outlet relay, and only after you explicitly enable it.

## Installation

### HACS (custom repository)

1. Push this folder to a GitHub repository (the layout already matches HACS:
   `custom_components/racktivity_dcmu/` + `hacs.json`).
2. HACS → ⋮ → *Custom repositories* → add the repository URL, type *Integration*.
3. Install **Racktivity DCMU**, restart Home Assistant.

### Manual

Copy `custom_components/racktivity_dcmu/` to `/config/custom_components/` (e.g. with the
Samba or SSH add-on) and restart Home Assistant.

## Setup

*Settings → Devices & services → Add integration → Racktivity DCMU*

| Field | Default | |
|---|---|---|
| Host | — | IP address of the PDU |
| SNMP port | 161 | |
| Read community | `public` | |

### Options (⋮ → *Configure*)

| Option | Default | What it does |
|---|---|---|
| Scan interval | 5 s | Live values + relay states (2 small SNMP GETs) |
| Configuration interval | 300 s | Names, limits, peaks. Also re-read right after a relay change or a "setting changed" log entry |
| Allow switching outlet relays | off | Turns outlet binary sensors into switches. Needs the write community too |
| Write community | — | SNMP write community. Only used for relay switching |
| Web username / password | — | Enables the read-only web API extras |
| Web API interval | 60 s | Web API extras + event log (3 HTTP requests) |

## Entities

PDU device: voltage, frequency, total current, total power, total energy, internal
temperature, internal humidity, peak total current. Disabled diagnostic entities: total
current warning/off level, voltage and humidity warning limits, peak time.

One device per outlet (named after the outlet name configured on the PDU):

| Entity | Source | Notes |
|---|---|---|
| Relay | SNMP | binary sensor (read-only), or a switch with control enabled |
| Current, power, apparent power, power factor | SNMP | power factor is *unknown* while the outlet draws nothing |
| Energy | SNMP | **resettable** counter (the web UI's "Resettable kWh") |
| Lifetime energy | web API | never reset; the best choice for the Energy dashboard |
| Peak current | SNMP | diagnostic; peak time, warning/off level, priority, power-on delay are disabled by default |
| Apparent energy | web API | VAh, disabled by default |

With the web API: external temperature 1–8 (enabled only for probes connected at setup),
airflow, intrusion 1/2, device clock (disabled by default), and a **Device log** event entity.

## Events

| Event | When | Data |
|---|---|---|
| `racktivity_dcmu_relay_changed` | an outlet relay changed state (by anyone) | `outlet`, `name`, `is_on` |
| `racktivity_dcmu_device_event` | a new row in the PDU's event log (web API) | `level`, `description`, `setting`, `address`, `ip_address`, `timestamp` |

The PDU logs every write made through its web UI, including the source IP. Example automation:

```yaml
trigger:
  - platform: event
    event_type: racktivity_dcmu_device_event
    event_data:
      level: info
condition: "{{ trigger.event.data.setting is not none }}"
action:
  - service: notify.notify
    data:
      message: >
        PDU setting {{ trigger.event.data.setting }} changed from
        {{ trigger.event.data.ip_address }}
```

## Polling and load

Per scan (5 s): 2 SNMP GETs, about 55 values. Every 300 s: 5 more GETs for configuration.
With the web API, every 60 s: 3 HTTP GETs (~1 KB). The PDU's own web UI polls every 2 s, so
this is well within what the device handles.

SNMP traps aren't used. They'd need a trap receiver configured on the PDU (a settings
change), a UDP listener inside Home Assistant, and their content is undocumented. Polling at 5 s
already catches relay changes and threshold-relevant values.

## Known limitations

- **Relay switching via SNMP SET hasn't been verified on hardware yet.** It assumes outlet
  column `.3.1.1.7.<n>` is writable with 1 = on / 0 = off. Test on an unused outlet first.
- The agent drops any request containing an OID it doesn't know (no error, just silence), so the
  integration only ever asks for known OIDs.
- A few OIDs are still unidentified; they're listed under *Download diagnostics*.

## Development

```bash
python -m venv venv && venv/bin/pip install pytest-homeassistant-custom-component
venv/bin/pytest                                   # offline tests (fake agent / mocked HTTP)
DCMU_LIVE_HOST=<pdu-ip> venv/bin/pytest tests/test_live.py -s   # read-only, real PDU
# optionally add DCMU_LIVE_WEB_USER=... DCMU_LIVE_WEB_PASSWORD=...
```

`raw/` is gitignored: keep device captures and notes there. Captures can contain the
device's credentials.

## License

MIT, see [LICENSE](LICENSE).
