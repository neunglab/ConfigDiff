# ConfigDiff 1.1

Offline Mac desktop tool for comparing Cisco IOS, IOS XE, and NX-OS configuration text. The left file A is the reference; open two files by default and optionally add a third. Drag a file onto a pane or use Browse. The app never connects to a device or sends configuration to a service.

Type an optional directory into Browse folder to start each pane's Browse dialog in that same directory. Plain paths and paths wrapped in matching single or double quotes are accepted. Leave it blank for the system's normal file dialog behavior. Invalid directories are reported without changing loaded files.

Ignore Backspace is enabled by default to hide and disregard stray ASCII Backspace (0x08) bytes in the displayed comparison, section summary, and exported diff. Turn it off to compare every character exactly. This view option never edits source files or the source text saved in a project; Copy original without a selection still copies the raw source.

Closing the main window stops the pending scroll timer and quits the app; macOS reclaims the process memory when it exits.

The workspace opens with the comparison tabs, Browse folder, and the two text panes. Use + Comparison for another independent A/B comparison (each tab can still add C). The macOS menu bar groups commands into File, Compare, View, and Search. View > Show Toolbar temporarily brings back the controls. View > Show Browse Folder hides or restores the folder field. Sections are hidden by default and can be shown from View.

On close, the app remembers open comparison tabs, selected tab, file paths, Browse folder, and view settings in its local application history. On the next launch it reloads the current files from disk; history does not duplicate configuration text. Saved projects are reopened from their project path. Clear History asks for confirmation, closes all tabs, clears the Browse folder, and removes this history without deleting source config or project files.

To align two related commands that appear on different lines, click the desired line in A and choose Actions > Mark line for visual alignment, then do the same for the corresponding line in B. Compare > Mark Current A/B Line and Compare > Align Cursor Lines A ↔ B provide menu alternatives. You can add several pairs as long as they follow the same line order in both files. Compare > Reset Visual Alignment restores the automatic comparison. This adds display gaps only: source line numbers, source text, copy, exported diff, and saved project contents remain unchanged. Alignment pairs remain in each tab during the current session, but are not stored in history or project files. Loading another source or project, or swapping A/B, clears the pairs. With Changes only enabled, aligning turns it off so the selected lines stay visible.

## Run

```bash
python3 -m pip install -r requirements.txt
python3 main.py
```

Use the left list to find changed configuration blocks. Drag the separators to resize the category list and each A/B/C pane independently; the pane toolbar has an Actions menu so long filenames do not block resizing. The viewer is plain text: characters such as `<`, `&`, and Cisco command text are not rendered as HTML or escaped on copy. Read-only bands between A and B span the height of changed blocks and point to their corresponding positions; they follow scrolling, zoom, and resizing and never copy or change config text. The colored minimap locates changes across the displayed lines. The minimap is cached while scrolling; vertical and horizontal pane movements synchronize once per display frame. `Changes only` includes two context lines around each difference. Original line numbers are drawn in a separate gutter; Hide Line Numbers collapses the gutter across all panes. Selecting text or pressing Cmd+C never includes line numbers. Zoom buttons and Cmd/Ctrl +/- change all panes by 0.5 pt while keeping the viewed line in place. Cmd/Ctrl + wheel also zooms. The per-pane Actions menu contains Copy original, Copy block, and Edit Source. `Copy Diff` copies the unified diff; `Dark` changes the display theme.

Find supports literal text or PCRE-compatible regular expressions. Choose A+B, A only, or B only; when C is visible, A+B+C and C only are also available. Next/Previous wrap through matches in display order. Cmd+F focuses Find; Cmd+G and Cmd+Shift+G navigate. Hide Sections expands the comparison area. Focus A+B temporarily hides C while keeping its loaded file. The font picker offers installed macOS fonts and is saved with a project. On macOS, two-finger trackpad pinch uses native zoom gestures and scales the selected font across all visible panes. The bottom bar identifies the plain-text view and each source's decoding: UTF-8, UTF-8 BOM, or Latin-1 fallback. Fallback indicates the codec used to display bytes, not a guarantee of the original encoding.

## Saving and backups

`Save Project` creates a `.cdiff` JSON file with full source text, paths, decoding labels, font family and font size. This can include customer secrets: store it accordingly. Every save requires confirmation. `Edit Source` also asks before replacing a source file and writes using its original display codec, including UTF-8 BOM where present; characters unavailable in Latin-1 cause an error rather than a silent encoding change. An existing target gets a timestamped `.bak` beside it before replacement; at most ten backups are retained per target. `Restore Backup` allows selecting a backup and backs up the current version before restoring. `Export Diff` writes a unified text diff after confirmation. The app writes via a temporary file and atomic replace; a new target has no prior version to back up.

## Build version 1.1 for macOS

```bash
python3 -m pip install -r requirements-build.txt
bash scripts/build_macos.sh
```

The next build publishes only `release/1.1/ConfigDiff-1.1.dmg`; the `.app` is built in `dist/` and packaged inside the DMG. Older releases remain in their version folders. The build generates the app icon from `assets/ConfigDiff-icon.png`. On managed Macs the disk image may use a larger HFS fallback. Builds have only PyInstaller's ad hoc signature, not a Developer ID signature; distribution to other Macs needs signing and notarization. Build from source under MIT; comply separately with PySide6/Qt licensing when distributing the bundled binaries (see `THIRD_PARTY_NOTICES.md`).

## Tests

```bash
python3 -m pytest -q
```

Structured summary recognizes common top-level IOS/IOS XE/NX-OS stanzas. Unknown syntax stays in the raw comparison; no commands are silently ignored. Automated parser classification is advisory and should be checked against the raw view before a production change.
