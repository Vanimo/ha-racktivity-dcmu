# Racktivity DCMU for Home Assistant

[![Release](https://img.shields.io/github/v/release/Vanimo/ha-racktivity-dcmu)](https://github.com/Vanimo/ha-racktivity-dcmu/releases)
[![Tests](https://github.com/Vanimo/ha-racktivity-dcmu/actions/workflows/tests.yml/badge.svg)](https://github.com/Vanimo/ha-racktivity-dcmu/actions/workflows/tests.yml)
[![Validate](https://github.com/Vanimo/ha-racktivity-dcmu/actions/workflows/validate.yml/badge.svg)](https://github.com/Vanimo/ha-racktivity-dcmu/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A [Home Assistant](https://www.home-assistant.io/) integration for the **Racktivity DCMU /
EnergySwitch PM0816**, a 1U rack PDU with one C20 inlet and eight switched, metered C13
outlets. It reads the PDU over SNMP on your local network, shows every outlet's power use in
Home Assistant, and, if you choose to enable it, lets you switch or power-cycle outlets.

Racktivity no longer exists and never published a MIB for this model. Everything in this
integration was worked out from the device's own web interface and verified on real hardware
(hardware 2.02, firmware 3.00). If you have a DCMU with a different firmware, please
[open an issue](https://github.com/Vanimo/ha-racktivity-dcmu/issues) with your findings.

## What you get

- **Per outlet:** current, power, apparent power, power factor, energy, peak current, relay
  state, and an *over warning level* problem sensor.
- **Whole PDU:** voltage, frequency, total current, power and energy, internal temperature and
  humidity, and *over total warning level* / *voltage out of range* problem sensors.
- **Control** (off by default): a switch and a *Power cycle* button per outlet.
- **Optional web-interface extras:** lifetime (non-resettable) energy for the Energy
  dashboard, firmware version, external temperature probes, airflow, intrusion inputs, and
  the PDU's event log as Home Assistant events.
- **Events** for relay changes and settings changes on the PDU, for automations.

The integration never changes settings on the PDU. The only thing it can write is an outlet
relay, and only after you enable control and enter the SNMP write community.

## Requirements

- Home Assistant 2025.1 or newer.
- A Racktivity DCMU / EnergySwitch PM0816 reachable from Home Assistant over the network.
- SNMP enabled on the PDU with a read community (the factory default is `public`).
- For switching outlets: the PDU's SNMP write community.
- For the extras: the PDU's web interface login.

The PDU speaks plain HTTP and SNMP v2c, neither of which is encrypted. Keep it on a trusted
network segment.

## Installation

### With HACS (recommended)

1. In HACS, open the ⋮ menu (top right) → **Custom repositories**.
2. Add `https://github.com/Vanimo/ha-racktivity-dcmu` with type **Integration**.
3. Search for **Racktivity DCMU**, download it, and restart Home Assistant.

HACS will offer updates when a new release is published.

### Manual

Copy the `custom_components/racktivity_dcmu` folder from the
[latest release](https://github.com/Vanimo/ha-racktivity-dcmu/releases) into your Home
Assistant `config/custom_components/` folder and restart Home Assistant.

## Setup

*Settings → Devices & services → Add integration → Racktivity DCMU*

| Field | Default | |
|---|---|---|
| Host | — | IP address of the PDU |
| SNMP port | 161 | |
| Read community | `public` | |

A second, optional page asks for relay control (checkbox + SNMP write community) and the web
login. Leave it empty to start read-only; everything on it can be changed later. A web login is
checked with one read before it's saved.

You get one device for the PDU and one per outlet, named after the outlet names configured on
the PDU. Rename them in Home Assistant if you like; the integration keeps its own names.

### Options

*Settings → Devices & services → Racktivity DCMU*, then the **gear icon** (⚙) next to the
entry. (The ⋮ menu has no options entry.)

| Option | Default | What it does |
|---|---|---|
| Scan interval | 15 s | Live values and relay states. Energy comes from the PDU's cumulative counters, so faster polling adds little |
| Configuration interval | 300 s | Names, limits and peaks. Also re-read right after a relay change or a settings change on the PDU |
| Allow switching outlet relays | off | Turns the outlet relay sensors into switches and adds the *Power cycle* buttons. Needs the write community too |
| Write community | — | SNMP write community, only used for switching |
| Power cycle off time | 10 s | How long an outlet stays off when its *Power cycle* button is pressed |
| Web username / password | — | Enables the read-only web-interface extras |
| Web API interval | 60 s | How often the extras and the event log are read |

## Entities

**PDU device:** voltage, frequency, total current, total power, total energy, internal
temperature, internal humidity, peak total current, and the problem sensors *Over total current
warning level* and *Voltage out of range*. Diagnostic entities, disabled by default: the current,
voltage, humidity and temperature warning levels, the total current off level, and the peak time.

**Each outlet:**

| Entity | Notes |
|---|---|
| Relay | binary sensor while read-only; a switch once control is enabled |
| Power cycle | button, with control enabled: off → wait the configured time → on |
| Over current warning level | problem sensor: current at or above the outlet's warning level |
| Current, power, apparent power, power factor | power factor shows *unknown* while the outlet draws nothing |
| Energy | the PDU's **resettable** counter |
| Lifetime energy | web extras: never reset, the right one for the Energy dashboard |
| Peak current | diagnostic; peak time, warning/off levels, priority and power-on delay are disabled by default |
| Apparent energy | web extras, disabled by default |

**With the web login:** external temperature 1–8 (enabled only for probes that were connected
at setup), airflow, intrusion 1/2, the device clock (disabled by default), and a *Device log*
event entity.

### Problem sensors

The three problem sensors use the **warning** levels configured on the PDU's Protection page,
not the off levels: they turn on while you can still do something about it, before the PDU
itself cuts the outlet. A short spike between two polls can be missed; sustained overloads
are what they're for.

### Energy dashboard

Use the per-outlet **Lifetime energy** sensors (web login needed). The plain *Energy* sensors
are the PDU's resettable counters: they work too, but drop to zero if someone presses *reset*
in the PDU's web interface.

## Automations

Two events are fired on the Home Assistant event bus:

| Event | When | Data |
|---|---|---|
| `racktivity_dcmu_relay_changed` | an outlet relay changed state, whoever switched it | `outlet`, `name`, `is_on` |
| `racktivity_dcmu_device_event` | a new row in the PDU's event log (web login needed) | `level`, `description`, `setting`, `address`, `ip_address`, `timestamp` |

The PDU logs every settings change made through its web interface, including the source IP, so
you can be told when someone changes it:

```yaml
triggers:
  - trigger: event
    event_type: racktivity_dcmu_device_event
    event_data:
      level: info
conditions:
  - condition: template
    value_template: "{{ trigger.event.data.setting is not none }}"
actions:
  - action: notify.notify
    data:
      message: >
        PDU setting {{ trigger.event.data.setting }} changed from
        {{ trigger.event.data.ip_address }}
```

A typical use of the *Power cycle* button is restarting a modem or switch when a ping fails;
use the `button.press` action on the outlet's power-cycle button.

## Troubleshooting

- **"No SNMP response" during setup:** check that Home Assistant can reach the PDU on UDP
  port 161 (VLANs, firewalls) and that the read community is right. The PDU answers a wrong
  community with silence, which looks the same as a wrong address.
- **Entities unavailable:** the PDU didn't answer two polls in a row. They recover by
  themselves when it does.
- **Reauthenticate prompt:** the PDU rejected the stored web login; enter the current one. The
  SNMP entities keep working meanwhile.
- **Diagnostics:** on the integration entry, ⋮ → *Download diagnostics* gives the decoded
  device state with all passwords and communities redacted. Attach it when you open an issue.

## How it works

Every scan interval the integration sends two small SNMP GET requests (about 55 values); every
configuration interval a few more for names, limits and peaks. With the web login it also
fetches three small pages from the PDU's web interface per web API interval. The PDU's own web
UI polls every 2 seconds, so this is well within what the device handles. SNMP traps are not
used; polling at 15 s already catches relay changes.

## Known limitations

- Only tested on the 8-outlet DCMU with firmware 3.00. Other Racktivity models (the ES series)
  use a different SNMP layout and won't work.
- One SNMP value per outlet is still unidentified and is not polled. The external temperature
  sensor table is read over SNMP and shown raw in the diagnostics; its readings aren't exposed
  as entities until someone with probes confirms the scale.
- Settings on the PDU (thresholds, names, schedules, network) are intentionally not editable
  from Home Assistant. The device page has a **Visit** link to the PDU's web interface for that.

## More

- [Changelog](CHANGELOG.md) and [releases](https://github.com/Vanimo/ha-racktivity-dcmu/releases)
- [Issues](https://github.com/Vanimo/ha-racktivity-dcmu/issues): bug reports, questions, findings
  from other DCMU units
- [Development guide](DEVELOPMENT.md): running the tests, project conventions, releasing
- [License](LICENSE): MIT
