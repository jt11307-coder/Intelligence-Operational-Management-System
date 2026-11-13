# Technical architecture

WPD COMPSTAT is a local Python 3.12–3.14 desktop application. The interface is PySide6. The database is SQLite. Files at rest use AES-GCM. Nothing in the running program calls a network API.

## Process

```text
Desktop shortcut
  -> %LOCALAPPDATA%\WPD-COMPSTAT\WPDCompstatLauncher.exe
  -> scan drives for WPD COMPSTAT\WPD-COMPSTAT-INSTALL.json
  -> verify product name, relative path, and SHA-256
  -> start Application executable with the discovered root
  -> Session unlocks the database into Working\
  -> Main window reads and writes through that connection
  -> close seals the database and deletes Working\
```

`launcher/bootstrap.py` is the source form of that launcher. `src/wpd_compstat/launcher/scan.py` decides the exit code: 0 start, 2 drive missing, 3 not a verified Windows executable, 4 more than one installation.

`src/wpd_compstat/__main__.py` requires `--root` pointing at a folder named `WPD COMPSTAT`. Temporary files are redirected onto that drive.

## Modules

| Path | Responsibility |
| --- | --- |
| `src/wpd_compstat/session.py` | Setup, unlock, lockout, idle lock, permissions, close and seal. |
| `src/wpd_compstat/security/` | scrypt, AES-GCM, role matrix, redaction. |
| `src/wpd_compstat/db/` | Connection, migrations `001_initial.sql` and `002_report_runs.sql`, seed data with no incidents. |
| `src/wpd_compstat/import_engine/` | Profile, PDF extract, parse, merge, four-stage pipeline. |
| `src/wpd_compstat/classification/` | Starter taxonomy, explainable engine, code mentions, persistence. |
| `src/wpd_compstat/analysis/` | Metrics, comparisons, time of day, patterns, offline coordinates, traffic, divisions, draft recommendations. |
| `src/wpd_compstat/assignments/` | Status machine and 14-day cycles. |
| `src/wpd_compstat/reporting/` | Fifteen-section packet, charts, PDF, PPTX, XLSX, CSV. |
| `src/wpd_compstat/backup/` | Encrypted backup, integrity check, restore, export copy. |
| `src/wpd_compstat/ui/` | Login, setup, and the sixteen views. |
| `packaging/` | PyInstaller specs and the Windows build script. |

## Cryptography

- A 32-byte data key is generated with `os.urandom` at setup. It is not in source code.
- The password is stretched with scrypt (`n=2^14`, `r=8`, `p=1`) and a random salt. The data key is wrapped with AES-GCM. A separate check value proves the password before the database opens.
- An optional recovery passphrase wraps the same data key a second time. There is no second hidden key.
- SQLite is written in `Working` while unlocked. On close it is sealed with AES-GCM and the magic `WPDC1` and the plaintext file is removed.
- Source PDFs and backup files use the same seal. Person and vehicle payloads are field-encrypted.
- Audit details pass through a redaction filter before insert. Password values and long narrative-like secrets are not stored in the audit row.

## Database

Foreign keys are on. Narrative insert, update, and delete maintain an FTS5 index. Schema changes are ordered SQL files applied once and recorded in `schema_migrations`.

Seed data inserts settings, placeholder divisions, unconfirmed agency codes, starter classification rules marked `starter_unconfirmed`, and one generic CAD profile marked unconfirmed. The incidents table is empty after setup.

## Import pipeline

1. **Select.** Authorized role only. Each path must be a PDF. The file is hashed and sealed. A batch row is opened.
2. **Extract.** PyMuPDF reads text. pdfplumber counts tables. Pages are stored with the batch. OCR is off unless a caller passes the flag, and there is no cloud OCR.
3. **Validate.** The active profile must be `agency_confirmed`. Otherwise the batch stops with the PDF retained and zero incidents. The parser applies the profile's labels. Unknown labels are ignored. Incidents that cross pages stay one record when the CAD number continues.
4. **Commit.** One transaction. Match key `CAD|DATE`. Insert, exact duplicate, or field-level conflict with history. Child rows for narratives, officers, citations, and encrypted parties are written on the same incident. A raised error rolls the transaction back. System classification is recalculated from the stored text.

The generic profile is a labeled interchange format for structural tests and for a department that chooses to export those labels. It is not accepted as Warwick's CAD layout. That layout is blocked on the missing sample PDF.

## Counting rules

Official dashboard numbers come from incident rows with `excluded = 0` and from classifications with `counts_officially` true.

A proposal counts officially only when the polarity is `occurred` and the rule is `agency_confirmed`, or a reviewer has accepted that incident classification. Structured call-type matches and narrative matches both record the evidence span. Contradiction patterns on the same sentence force polarity `contradictory` and `counts_officially` false.

Polarity from narrative context:

- Negation such as "no" or "not" yields `negated`.
- Historical wording yields `historical`.
- Alleged wording yields `alleged`.
- Precautionary wording yields `precautionary`.
- A bare short token without an affirmative statement yields `insufficient`.

`suppress_if` drops an occurred category when a more specific occurred category is also present. Shoplifting suppresses generic larceny. Category totals are therefore not additive with each other or with calls for service.

Calls for service count imported incidents in the date range. Officer-initiated and citizen-generated counts stay unavailable until `source_lists_confirmed` is true. Accident metrics use the accident category set and require official classifications. Priority is shown only when the CAD field contained a value.

Comparisons:

- Current period versus the previous window of the same length.
- 14-day, 28-day, prior calendar month, prior quarter, and equivalent prior-year period.
- If the prior period has no data coverage, the baseline is null and the percent is null.
- If the baseline is below `percent_change_min_baseline` (default 5), the absolute change is shown and the percent is omitted.

Traffic workbook columns map through a caller-supplied dictionary. `citation_references` never enter `verified_violations`. The weekly benchmark setting defaults to 200 and is a comparison line, not proof that the goal was met.

Repeat-offender flags are never set automatically.

## Assignments

`transition` checks the role and the allowed next status. `completed` does not imply `effective`. `effective`, `partially_effective`, and `ineffective` require `assignments_assess`. `create_cycle` requires `assignments_approve`, spans 14 days, and reassigns unresolved rows onto the new cycle with a progress note.

## Reporting

`build_compstat_packet` reads only stored metrics, comparisons, patterns, traffic sums, and assignments. If the incident table is empty, the qualifications say so. Charts use Matplotlib's Agg backend and are written as image files for the PDF and the slides. Report runs are inserted into `report_runs`.

## Security boundaries

- Read-only search cannot load narrative bodies or person payloads.
- Import, backup, restore, user administration, and profile confirmation each call `session.require`.
- CSV export neutralizes formula injection.
- The source tree does not import `requests`, `httpx`, `openai`, or `boto3`.

## Packaging status

`packaging/wpd_compstat.spec` and `packaging/launcher.spec` describe windowed PyInstaller builds. They have not been executed here. The manifest in a source installation points at `Application/ENTRY` and `packaging_status` `source`.
