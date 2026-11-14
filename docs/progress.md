# Development progress

Status date: 2026-11-13. Application version: 0.9.0. Workspace: `/agent/wpd-compstat`.

A feature is listed as completed only when the code exists and an automated test or a direct code path covers it. The Warwick CAD call-log parser reconciles against the 2026 year-to-date PDFs on the agency machine; its profile still needs administrator confirmation. A Windows executable was not produced.

## Completed features

- External-drive layout under a folder named `WPD COMPSTAT`, with `Application`, `Launcher`, `Database`, `Source PDFs`, `Imports`, `Reports`, `Presentations`, `Maps`, `Backups`, `Audit`, `Configuration`, `Documentation`, `Working`, and `Logs`.
- Installation manifest `WPD-COMPSTAT-INSTALL.json` with a unique installation id and a SHA-256 of the application entry. The launcher rejects a missing, unreadable, or hash-mismatched manifest.
- Drive-letter scan. Shortcuts and the repair utility use `%LOCALAPPDATA%\WPD-COMPSTAT` and do not embed `E:\` or any other letter. Missing drive, two installations, and a tampered entry are handled.
- First-run administrator setup. Passwords are checked with scrypt. The database key is random, wrapped with AES-GCM, and held only in memory while the session is unlocked. There is no built-in password or key.
- Five roles: administrator, crime analyst, command staff, supervisor, and read-only. Failed sign-in locks the account after five attempts for fifteen minutes. The session locks after idle time.
- Encrypted database at rest, encrypted source PDFs, encrypted backups, and encrypted person and vehicle fields. Audit text is redacted before it is stored.
- SQLite schema with incidents, narratives and FTS5, classifications, officers, locations, citations, vehicles, sensitive persons, agency codes, patterns, recommendations, assignments, cycles, backups, and audit. Migrations run inside the schema scripts.
- Four-stage PDF import: select, extract, validate, commit. Commit is transactional. The match key is `CAD number|event date`. A repeated file does not insert a second incident. A conflicting field is kept and recorded. A failed commit rolls back.
- Without an administrator-confirmed CAD profile, a PDF is stored and no incidents are invented.
- Rule-based classification with occurred, alleged, historical, negated, precautionary, and contradictory readings. Official counts require a confirmed rule or a later acceptance. Nested categories such as shoplifting suppress a second larceny count. Agency codes `1500G`, `1500K`, `0200`, `02`, and `KCMH` stay unconfirmed and have no invented meaning.
- Period comparisons for 14 days, 28 days, prior month, prior quarter, and prior year to date. Percentages are withheld when the baseline is below five. A missing prior year is not shown as zero.
- Traffic workbook import that leaves the source file unchanged. Citation references are not counted as verified violations.
- Pattern, hotspot, division, and recommendation modules. Recommendations stay in draft until command staff act. Completion of an assignment is a different status from effective.
- Fourteen-day COMPSTAT cycle. Days 1–2 are intelligence and assignment, 3–10 implementation, 11–12 assessment, and 13–14 command review. Unresolved assignments carry forward.
- Fifteen-section COMPSTAT packet with PDF, PowerPoint, workbook, and CSV export. Empty installations state that no incidents have been imported.
- Search, incident detail with role limits, data-quality summary, manual backup, restore, and encrypted backup copy.
- PySide6 window with the sixteen navigation views. The dashboard does not invent counts.
- PyInstaller specs, `packaging/build_windows.ps1`, and `packaging/check_windows_build.py`.

## Tests passed

On Python 3.12, Linux, 2026-11-13:

```text
33 passed, 1 skipped in 2.97s
```

The skipped test is `test_real_cad_pdf_acceptance`. It is skipped because the Warwick CAD call-log PDF was not supplied. It is not a pass.

Covered areas: classification polarity and suppression, synthetic import structure, encryption and lockout, backup and restore, launcher selection, percentage rules, traffic citation references, assignment status, redacted audit, offline import ban, and an offscreen window open on an empty database.

Details: `docs/test-results.md`.

The folder to copy onto the Lexar drive is `/agent/WPD COMPSTAT`. It includes `Open WPD COMPSTAT.bat` and the Windows packages under `program/wheels`. This machine cannot write to `L:`. The running copy on this computer was stopped so the program is not left on the desktop.

## Remaining work

- An administrator confirms the `wpd-cad-call-log-v1` profile after spot-checking imported calls against the printout.
- Decide whether merged calls (`Merge:` header) count as calls for service, and confirm call-source lists using the printed sources (Initiated, Telephone, 911, Walk-In, Other, Alarm System, Radio, Cellular, Flock Hit).
- Build `WPDCompstat.exe` and `WPDCompstatLauncher.exe` on Windows with `packaging/build_windows.ps1`, copy the application executable into `Application/`, and set the manifest `packaging_status` to `windows_executable` with the new hash.
- Confirm starter classification rules, shift hours, call-source lists, and division names with the department before they are treated as official.
- Ask the department what `1500G`, `1500K`, `0200`, `02`, and `KCMH` mean. Leave them unconfirmed until then.
- After a real PDF import, reconcile every published COMPSTAT figure to the incident rows.
- Exercise the desktop shortcut installer on a Windows computer whose drive letter changes between launches.

## Known limitations

See `docs/limitations-register.md`. The open blockers for a department release are administrator confirmation of the call-log profile and the missing Windows executable.
