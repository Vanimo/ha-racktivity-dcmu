# Changelog

Each `## [X.Y.Z]` section is the release notes for that GitHub release; `manifest.json`
must carry the same version (a test checks this).

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
