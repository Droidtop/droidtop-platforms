# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the
repository does not cut versioned releases yet, so everything is recorded
under Unreleased.

## [Unreleased]

### Added

- `storagePathTemplate` on the eight AetherSX2/NetherSX2 PS2 rows (plain `bootPath` launch), so a PS2 game boots without a content URI when the emulator holds all-files access.
- The catalog: 195 platforms with their RetroArch cores, 463 standalone-emulator presets and 109 BIOS sets, generated from other frontends' own maintained databases (ES-DE, Batocera, Daijishō) rather than hand-written.
- A 71-row engine registry that drives detection and launch routing for both apps, so covering another engine ships as a database update instead of an app rebuild, and droidtop and Enginehost can never classify one folder differently.
- Detection rows for 41 more engine families, from ONScripter, AGS and RealLive to GameMaker, TyranoScript and the NW.js/Electron fallbacks.
- Detection rows for the engines a real library census found unrecognised: LOVE, XNA/FNA/MonoGame, HashLink, Torque, GoldSrc, Source and more.
- A plugins index, so the plugin catalog no longer depends on GitHub's API allowance: devices read one file and fall back to the API only when it is stale.
- A hardware collection recording what a real handheld reports (panel, pad identity, key and axis ranges), starting with the Retroid Pocket 5.

### Changed

- The data is now one file per row with an index naming each file and its checksum, so an app downloads only what it does not already have instead of four monolithic documents.
- The HTML engine row matches any folder with a page at its root and is checked last, so web exports of other engines are classified first.
- NScripter games launch through Enginehost rather than only through Wine.
- The Steam and Epic platforms are marked as store-owned.
- Continuous integration actions are pinned to specific commits and token permissions are stated explicitly.
- Repository links point at the droidtop organization.

### Fixed

- Platform RetroArch cores come from ES-DE's Android systems file, so droidtop's own RetroArch launch names a core RetroArch for Android actually has (Nintendo 64 is mupen64plus_next_gles3, arcade systems mamearcade); 31 platforms changed.
- The Switch legacy emulator install is covered, and a player entry whose label and package pointed at different apps was removed.
- LOVE games can launch through Enginehost; the row still said no runtime was published and blocked the launch before it started.
- Player presets with quoted launch arguments are no longer skipped by the generator, and more ES-DE placeholders are understood, growing the catalog from 361 to 448 presets.
- File-content substitution and array launch arguments are understood, adding 16 more presets and the first two PS Vita players.
- Twenty player presets that had been issued the same id now have unique ids.
- The PC platform is named PC, not IBM PC.
