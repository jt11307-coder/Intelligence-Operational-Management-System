# Test results

Run on 2026-11-13 in `/agent/wpd-compstat` with the project virtual environment, Python 3.12, Linux.

```text
.venv/bin/python -m pytest --tb=short -p no:cacheprovider
33 passed, 1 skipped in 2.97s
```

The skipped test is not a pass.

## Acceptance status

`tests/test_acceptance_blocked.py::test_real_cad_pdf_acceptance` is skipped with the reason: the Warwick CAD call-log PDF was not supplied. Acceptance is not passed.

`test_acceptance_is_not_passed` checks that the acceptance flag remains `blocked_missing_pdf` and that `WPD_CAD_PDF` is unset. That test passed. It proves the suite does not claim department-PDF acceptance.

No department incidents were loaded. Synthetic fixtures are labeled and used only for structure.

## Passed tests

Classification (`tests/test_classification.py`):

- Agency codes do not become categories.
- Arrested-for-burglary counts only after confirmation.
- A bare burglary mention does not count.
- The word citation does not invent a citation flag.
- Forced entry is not use of force.
- Historical and alleged events do not count.
- An injury call type contradicted by the narrative does not count.
- "No firearm located" is not a recovery.
- The token OJI is not expanded.
- Repeat offender is never automatic.
- Shoplifting suppresses a second larceny count.
- A short code matches only the whole call type.

Import structure (`tests/test_import_structure.py`), all on synthetic labeled PDFs:

- A fresh database has no incidents.
- An unconfirmed profile stores the PDF and imports nothing.
- Decoy text is not turned into incidents.
- A missing identifier is not invented.
- One incident keeps many officers and narrative lines, including a page break.
- The same PDF twice does not double incidents.
- A conflicting disposition is kept and flagged.
- A failed commit rolls back.

Security, backup, counting, and launcher (`tests/test_security_and_launcher.py`):

- The sealed database does not start with the SQLite header, and the crypto module has no embedded private key.
- Lockout after five failures, and a read-only user cannot import.
- Backup, encrypted copy, and restore return the database to the earlier incident set.
- Percentages are withheld below the baseline of five.
- A missing prior-year period is not reported as zero.
- Traffic citation references are not verified violations, and the source file is unchanged.
- Completing an assignment does not set the status to effective by itself.
- The launcher finds an installation after the folder moves, refuses a missing drive, asks when two installations exist, refuses a source package unless allowed, and rejects a tampered entry. Shortcut text has no drive letter.
- A source-mode child process receives `PYTHONPATH` pointing at `src`.
- Sensitive person and narrative text is withheld from a read-only user, and the audit row does not keep the password.

Other:

- `tests/test_offline.py` asserts the application source does not import network clients.
- `tests/test_ui_smoke.py` opens the main window offscreen against an empty database and checks that the incident count is zero.

## Not run, and why

| Check | Result |
| --- | --- |
| Parser acceptance on a real Warwick CAD PDF | Blocked. The PDF is not in the workspace or the project store. |
| End-to-end report reconciliation against department records | Blocked by the same missing PDF. The packet path was reviewed against an empty database and against synthetic rows in unit tests. |
| `WPDCompstat.exe` launch on Windows | Not run. This host is Linux. `packaging/check_windows_build.py` is expected to exit 2. |
| Drive-letter change on a physical Windows PC | The selection logic was tested with two temporary directories standing in for drive roots. A physical letter change was not available. |
| Presentation readability on a projector or printed packet | Export code exists. A formatted department packet was not produced because there is no department extract. |

## How to repeat

```bash
cd /agent/wpd-compstat
.venv/bin/python -m pytest --tb=short
```

To run the blocked acceptance test later, place the department PDF somewhere local, set `WPD_CAD_PDF` to that path, and remove the skip only after a person has checked the parse against the document. Until that review, leave the skip in place.
