# Known limitations register

Each item says what is limited, what the program does instead, and what would close it.

## Blockers

### L1. Warwick CAD call-log PDF was not supplied

The sample PDF was not in the workspace and not in the project store. The parser has a generic labeled profile used by synthetic tests. That profile is not Warwick's CAD layout. No department incidents were invented. `tests/test_acceptance_blocked.py::test_real_cad_pdf_acceptance` is skipped. Official COMPSTAT figures cannot be reconciled to a real extract until the PDF is provided, the profile is confirmed by an administrator against that file, and the acceptance test is reviewed by hand.

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

Do not close L1 by synthesizing a CAD PDF. Do not close L2 by renaming a Linux binary. Record the date, the person, and the evidence when a department reviewer confirms a rule, a code, or a profile.
