# ConfigDiff — agreed project specification

This is the consolidated scope from the project conversation on 11 November 2026. The app is an offline Mac desktop tool inspired by KDiff3's side-by-side presentation, independently implemented for Cisco configuration text.

## Inputs and comparison

- Start with A and B; add or remove C to compare up to three files. A on the left remains the reference. With C, compare A↔B and A↔C separately; this is comparison, not automatic three-way merge.
- Drop a file directly into each pane or click Browse. Show source filename, detected IOS/IOS XE/NX-OS profile, and original line count. Plain text of any Cisco configuration can be compared even if the parser does not recognize a stanza.
- Raw mode retains the entire original file, order and line numbers. Structured summary groups top-level interfaces, routing, ACL, route maps, QoS, VRF and NX-OS feature/vPC stanzas. A section is a category; a block is an individual stanza. Unknown or ambiguous syntax remains visible in Raw mode.
- Align lines to the left A source with display-only gaps. Keep original line numbers for each side. Provide synchronized vertical scrolling, a colored clickable minimap, and a change-only view with context.
- Allow independent drag resizing of the category sidebar and the A/B/C text panes. Keep pane controls compact so long filenames cannot lock the splitters. Render the config as plain text and copy raw characters without HTML escaping or display-only line numbers.
- Find literal text or PCRE-compatible regex in A+B, A only, B only, and optionally C or all three. Navigate matches in both directions. Hide the Sections sidebar or temporarily focus A+B without discarding C. Support native macOS two-finger pinch zoom across panes.
- Use muted background colors for added (green), removed (red), and changed (yellow) lines. Use a readable monospaced font, synchronized zoom, and Light/Dark themes. Show per-file line counts and added/removed/changed display-row counts.
- Allow selecting and copying original text without generated line numbers, copying a full top-level block, copying the unified diff, and exporting a unified diff after confirmation.

## Saving and safety

- Project saves include all loaded source text and UI font size in `.cdiff`; opening a project restores the comparison. Ask before every Save. The file may contain credentials and must be handled as a config file.
- Source files open read-only in the comparison view. Edit Source opens an explicit raw editor; before overwriting an existing file, check if it changed on disk and require confirmation.
- Before any overwrite of an existing project, source, or exported diff, create a timestamped `.bak` beside it. Retain at most 10 backups per target. Restore Backup requires confirmation and first backs up the current target. Use temporary-file writing followed by atomic replacement. New files have no prior backup.
- Processing is local. No device connection, deployment, telemetry, upload, or automatic execution of Cisco commands.

## Release and license

- Release folder is `release/1.0/` with macOS `.app` and `.dmg` built by `scripts/build_macos.sh`.
- Project source is MIT licensed; PySide6/Qt have separate licensing obligations. KDiff3 code is not used. The app bundle is unsigned, so distribution requires signing/notarization by the distributor.

## Honest limitations of 1.0

- Structured summary is advisory and uses conservative top-level stanzas; it is not a complete semantic parser for all Cisco releases. ACL and route-map order must be checked in Raw mode.
- The minimap and changed count refer to displayed aligned rows, not a count of Cisco commands or production impact.
- The build script prefers a compressed UDZO `.dmg`; on a managed Mac without DiskManagement, it falls back to an uncompressed HFS hybrid `.dmg`.
