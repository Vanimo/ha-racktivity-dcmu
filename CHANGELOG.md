# Changelog

Each `## [X.Y.Z]` section is the release notes for that GitHub release; `manifest.json`
must carry the same version (a test checks this).

## [0.3.0]

### Added
- **Power cycle** button per outlet (with relay control enabled): switches the outlet off and
  back on after the new *Power cycle off time* option (default 10 s). Pressing it again while
  a cycle is running is refused.
- Problem sensors computed from the limits configured on the PDU: *Over current warning
  level* per outlet, and *Over total current warning level* and *Voltage out of range* for the
  PDU. Handy automation triggers without templates.
- *Temperature warning level* diagnostic sensor (disabled by default).
- Re-authentication: if the PDU rejects the web login, Home Assistant asks for the new one
  instead of leaving the web API entities unavailable.

### Changed
- Three previously unidentified SNMP values are now known (humidity and temperature trap
  flags, internal temperature warning level); the external temperature sensor table is read
  in its own request so a firmware without it can't break the configuration read. The one
  remaining unidentified outlet value is no longer polled.
- Diagnostics show the raw external sensor table instead of "unidentified OIDs".

## [0.2.0]

### Added
- Continuous integration: lint, formatting, type check and tests on every push and pull
  request; HACS and hassfest validation on push and weekly.
- A changelog, with a test that keeps it in step with the manifest version.
- Dependabot keeps the test tooling and GitHub Actions up to date.

No functional changes to the integration.

## [0.1.2]

### Added
- Integration icon: a 1U rack PDU with a C20 inlet and C13 outlets, with light and dark
  versions. Home Assistant shows it under *Devices & services* and in the setup dialog.
  Older Home Assistant versions keep working without the icon.

### Changed
- Relay switching is confirmed working on hardware; the "unverified" caveat is removed from
  the docs.

## [0.1.1]

### Fixed
- Entities became unavailable after changing the integration's options (for example after
  enabling relay control or adding the web login) until Home Assistant was restarted.

### Added
- Optional second setup page for relay control and the web login. Leave it empty to start
  read-only; everything stays changeable later with the gear icon on the integration.
- MIT license.

### Changed
- Default scan interval is now 15 s (was 5 s). Existing entries keep their saved value.
- README: options are under the gear icon (⚙) on the integration, not the ⋮ menu.

## [0.1.0]

First release: SNMP polling of the Racktivity DCMU / EnergySwitch PM0816, optional
read-only web API extras, relay control behind an opt-in, config/options flows and
diagnostics.
