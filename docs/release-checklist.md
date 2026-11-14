# Release checklist

Use this before anyone treats an installation as the department system. Version 0.9.0 does not clear the checklist. The failed items are the release blockers.

## Package

- [ ] `packaging/build_windows.ps1` has been run on Windows.
- [ ] `build\dist\WPDCompstat.exe` exists and starts.
- [ ] `build\dist\WPDCompstatLauncher.exe` exists and starts.
- [ ] `packaging/check_windows_build.py` exits 0 on that Windows machine.
- [ ] The manifest `packaging_status` is `windows_executable`.
- [ ] The manifest SHA-256 matches the executable that was copied into `Application\`.
- [ ] A modified executable is rejected by the launcher.
- [x] Source packaging files exist in this tree. They are not a Windows build. This box records the files only.

Current result: the executable boxes are open. This environment printed that Windows executables were not built.

## Drive

- [x] Installation folder name is `WPD COMPSTAT`.
- [x] Subfolders match the layout in `docs/installation-guide.md`.
- [x] Shortcut text has no drive letter. Covered by `test_launcher_drive_letters_and_shortcut`.
- [ ] A Windows PC launches after the drive moves from one letter to another.
- [ ] Disconnecting the drive shows the not-connected message and does not point the shortcut at a guessed letter.
- [ ] Two connected copies ask the operator to choose.
- [x] The selection logic for missing, duplicate, source, and tampered installs passed in automated tests against temporary directories.

## Security

- [x] No default password.
- [x] No encryption key in source. The database file is sealed.
- [x] Five failed passwords lock the account.
- [x] Read-only users cannot import and cannot read person or narrative detail.
- [x] Audit storage redacts password material.
- [ ] An administrator has stored the recovery passphrase off the drive, or has accepted that a lost password is unrecoverable.
- [ ] Encrypted backups have been copied to a second approved location.
- [x] The same-drive warning is attached to backup results.

## Data

- [ ] The real Warwick CAD PDF is on file and has been compared with the parser output.
- [ ] `tests/test_acceptance_local.py` passes with `WPD_CAD_PDF_DIR` set on the agency machine, and an administrator has confirmed the `wpd-cad-call-log-v1` profile.
- [ ] An administrator confirmed the CAD profile after that comparison. The generic profile has not been confirmed against Warwick's export.
- [ ] Starter rules that the department accepts are marked confirmed. The rest stay unconfirmed.
- [ ] Agency codes remain unconfirmed until the department defines them.
- [ ] Source lists and shift hours are confirmed or the dashboard still shows those metrics as unavailable.
- [x] A new installation contains zero incidents. Covered by tests.
- [x] Synthetic fixtures are labeled and are not loaded as department history.

## Counts and products

- [x] Negated, historical, alleged, and precautionary readings do not count in unit tests.
- [x] Small baselines omit percentages.
- [x] Missing prior-year data is not zero.
- [x] Citation references are not verified violations.
- [x] Assignment completion is distinct from effective.
- [ ] A packet built from a real import reconciles every published number to incident rows.
- [ ] PDF and PowerPoint output from that import has been read for formatting.

## Offline

- [x] Application source does not import a cloud HTTP client. Covered by `test_source_does_not_import_network_clients`.
- [ ] The installed Windows program was started with the network disconnected and still opened the local database.

## Documents

- [x] `docs/user-manual.md`
- [x] `docs/installation-guide.md`
- [x] `docs/architecture.md`
- [x] `docs/test-results.md`
- [x] `docs/limitations-register.md`
- [x] `docs/progress.md`
- [x] This checklist

## Release decision

Not releasable as the Warwick production system until L1 and L2 in `docs/limitations-register.md` are closed and the open boxes above are checked on Windows with the department PDF.
