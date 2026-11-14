# Known limitations register

Each item says what is limited, what the program does instead, and what would close it.

## Blockers

### L1. Warwick CAD call-log profile needs administrator confirmation

The parser now reads the real Warwick CAD call-log printout ("Selective Search" and "Dispatch Log"). It was checked against the 2026 year-to-date PDFs on the agency machine: every file's parsed call count equals its count of printed call-number lines. The profile `wpd-cad-call-log-v1` is seeded `unconfirmed`. An administrator confirms it under Administration (or with `--confirm-call-log-profile` on the bulk importer) after comparing a few calls with the printout. `tests/test_acceptance_local.py` repeats the reconciliation when `WPD_CAD_PDF_DIR` points at local PDFs; the PDFs are never committed.

Known layout decisions, each visible in the stored record:

- `Refer To Incident` numbers ending `-OF` are stored as offense report references, `-AR` arrest, `-AC` accident, `Refer To Summons` as `summons`, and `Refer To Field Int` as `field_interview`. Other formats are stored as `other` with a warning.
- `Refer To Citation` numbers are citation references only. Neither form (`-CN` or the long numeric form) is treated as a verified violation or a warning.
- A `Merge:` header line is stored as a `merged_with` reference. Merged calls have no printed action, so their disposition stays blank. Merged calls are still counted as calls until the department decides otherwise.
- The location is the first `Location/Address` (or `Location`, `Vicinity of`). Later `Location Change` lines are kept as stamped narrative entries.
- Officers are stored by the printed `USERID - Rank Name` text. The first `ID:` is the primary; later IDs are assisting. Dispatch and arrival times are the first printed `Disp-` and `Arvd-` values; clear time is the `Call Closed By` time, or the last `Clrd-` value.
- Names, addresses, SSNs, dates of birth, arrest charges, insurance, and wrapped person lines stay in the encrypted person payload. Plates and VINs stay in the encrypted plate field.

### L2. Windows executables were not built

The host is Linux. PyInstaller does not cross-compile to a Windows `.exe` here. `packaging/wpd_compstat.spec`, `packaging/launcher.spec`, and `packaging/build_windows.ps1` are the build. `packaging/check_windows_build.py` reports that the executables do not exist. There is no file named `WPDCompstat.exe` or `WPDCompstatLauncher.exe` in this tree. A Windows machine must run the build script.

## Counting and data

### L3. Starter classification rules are unconfirmed

Call-type phrases and narrative patterns ship as `starter_unconfirmed`. They explain a possible reading and do not enter official counts until an administrator confirms the rule or a reviewer accepts one incident. Confirming them without a department review would overstate the taxonomy.

### L4. Agency codes have no definition in this program

`1500G`, `1500K`, `0200`, `02`, and `KCMH` are stored with status `unconfirmed`, a null label, and a null definition. The program does not guess that they are statutes, units, or hospitals. They do not classify incidents.

### L5. Call-source lists, shifts, and divisions are placeholders

Officer-initiated and citizen-generated metrics stay unavailable until source lists are confirmed. Shift hours are a placeholder and `shifts_confirmed` is false. Division names from the specification are listed with a note that command and effective dates are unconfirmed. Cleared-by dispositions start empty.

### L6. Geocoding is offline and incomplete

Coordinates appear only when an administrator has stored an offline reference for an address. There is no network geocoder. Hotspot language in the packet says that exact coordinates are required. Intersections and businesses without a reference stay ungeocoded.

### L7. Traffic citation references are not verified violations

A traffic import can carry a citation count from another system. Those numbers are stored as references. Verified violations stay at zero unless a confirmed classification says the violation occurred. The weekly figure of 200 is a setting, not a measured result.

### L8. Repeat offenders are not inferred

The program never marks a person as a repeat offender from name matching. That action stays manual because name matching would create false links.

### L9. Empty database is the supported demonstration

Dashboards, briefings, and packets on a new installation say that no incidents are imported. They do not show sample crime.

## Security and recovery

### L10. No password recovery without a recovery passphrase

If the first-run recovery field is left blank, the data key cannot be unwrapped. The program will not add a backdoor key.

### L11. Same-drive backups do not survive loss of the drive

Every backup record includes that warning. Restore and integrity checks work for a backup file that is still present. The department must copy the encrypted backup to a second approved location. That copy step is operational, not automatic.

### L12. Session lock is local

Idle lock and the five-attempt lockout protect the open session and the account record. They do not encrypt the drive against someone who copies the sealed files. Sealed files still require the password or recovery passphrase.

### L13. Read-only users do not receive narratives

Search results for that role omit narrative text and person payloads. A role that can read narratives can still export a packet. Narrative excerpts in the packet stay off unless the setting is enabled.

## Product scope

### L14. The generic CAD profile is an interchange format

Confirming "generic labeled profile" in Administration tells the importer to trust labels such as CAD number and narrative. It does not mean the department's PDF uses those labels. Leave it unconfirmed until the real export is compared.

### L15. OCR and scanned PDFs

Text extraction uses the embedded PDF text. A scanned image without a text layer will not become incidents. Local OCR is not wired as a default, and cloud OCR is out of scope.

### L16. Maps are data, not a basemap service

The Maps folder can hold files the department places there. The program does not download tiles.

### L17. One commander per assignment

The assignment record holds a single commander. Shared command would need a later schema change.

### L18. UI coverage is a smoke test

Automated UI coverage opens the main window offscreen and checks an empty incident table. It does not click through every dialog on Windows. Desktop shortcut installation was checked by reading the generated script text, not by clicking a Windows desktop.

## Closing a limitation

Do not close L1 by synthesizing a CAD PDF or committing a department PDF. Do not close L2 by renaming a Linux binary. Record the date, the person, and the evidence when a department reviewer confirms a rule, a code, or a profile.
