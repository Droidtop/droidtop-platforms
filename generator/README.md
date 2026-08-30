# Generators

Scripts that rebuild players-database.json from upstream frontend
databases. Run manually; the output is reviewed and committed, never
auto-published.

- `from_esde.py` — parses ES-DE mobile's es_systems.xml +
  es_find_rules.xml (clone https://gitlab.com/es-de/emulationstation-de,
  resources/systems/android/) into database entries. TODO: implement —
  the %EMULATOR_X%/%DATA%/%EXTRA_*% substitution model maps naturally
  onto argumentsTemplate.
- Daijishō Start-Arguments wiki parser — the original seed generator
  (droidtop scratchpad parse_players.py); to be moved here.
- iiSU — source format/license research pending.
