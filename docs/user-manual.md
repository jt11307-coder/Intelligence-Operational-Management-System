# User manual

WPD COMPSTAT Intelligence & Operational Management System, version 0.9.0.

This program runs on the computer that has the external drive attached. It does not send records to a cloud service. It starts empty. Counts appear only after a confirmed CAD profile imports real call logs, or after an authorized user enters operational records such as assignments.

## Sign in

The first launch asks for an administrator username and a password of at least 12 characters. There is no default password. An optional recovery passphrase can unwrap the database later. If that field is left blank, a forgotten password cannot be recovered by the program.

Later launches ask for the username and password. Five wrong passwords lock that account for 15 minutes. The window locks after 15 minutes without use. That interval is an administrator setting named `session_timeout_minutes`.

Closing the program encrypts the database back onto the drive and removes the working copy.

## Roles

| Role | What that person can do |
| --- | --- |
| Administrator | Everything, including users, restore, profile confirmation, and deletion. |
| Crime analyst | Import, classify, search narratives and sensitive fields, analyze, draft assignments, export, and back up. |
| Command staff | Read narratives, approve and assess assignments, and export briefings. |
| Supervisor | Read narratives and update assignment progress. |
| Read-only | Dashboard and search. Narratives and person records stay hidden. |

A control that the role cannot use reports an access error and does not change data.

## Screens

The sidebar opens these views:

1. Executive Dashboard. Period counts from imported incidents. Selecting a count lists the supporting CAD numbers. An empty database shows no incidents.
2. Daily Briefing. The same packet sections used for the command briefing, without narrative excerpts unless an administrator turns excerpts on and the role may read narratives.
3. COMPSTAT. Builds the fifteen-section packet for a date range.
4. Crime Analysis. Category readings and pattern records for the period.
5. Traffic Enforcement. Imports a traffic workbook or CSV. The original file is not modified.
6. Crash Analysis. Official accident classifications only.
7. Significant Incidents. Categories marked significant, and only when the classification counts officially.
8. Geographic Intelligence. Points that already have coordinates from an offline reference. The program does not call a geocoding service.
9. Division Performance. One incident is counted once for a division. Placeholder division names are not official until an administrator confirms them.
10. Operational Assignments. Proposed through closed, with notes and measurements.
11. Reports. PDF, PowerPoint, Excel, and CSV exports of the packet.
12. Incident Search. CAD number, date, call type, disposition, address, and narrative full text when the role may read narratives.
13. PDF Import. Select PDFs, then extract, validate, and commit.
14. Data Quality. Missing fields, unconfirmed rules, and open exceptions.
15. Administration. Confirm the CAD profile, call-source lists, and shift hours.
16. System Health. Manual backup and the backup list. The screen repeats the warning that a backup on the same drive does not survive loss of that drive.

Light and dark appearance follow the saved theme control on the window.

## Import a call log

1. An administrator opens Administration and chooses **Confirm the Warwick CAD call-log profile** after comparing a few imported calls with the printout. That profile reads the CAD "Selective Search" and "Dispatch Log" PDFs. The generic labeled profile is only for PDFs that already use the program's labeled fields.
2. Until a profile is confirmed, PDF Import stores the file and creates no incidents.
3. Choose one or more PDFs, or a folder (subfolders included), then choose Extract, validate, and commit. The window is busy until the batch finishes; a month of call logs takes several minutes.
4. For a large backlog, close the program and use the bulk importer from a command prompt. It runs one batch per folder and prints each file's call-line count next to the calls extracted, new, updated, and skipped:

   ```
   "E:\WPD COMPSTAT\Runtime\py314\Scripts\python.exe" -m wpd_compstat.import_cli --root "E:\WPD COMPSTAT" --user <username> "<folder of PDFs>"
   ```

   Run it from the program folder (the one holding `src`) with `PYTHONPATH` set to its `src` folder. It asks for the password and does not store it.
5. Select stores the file under `Source PDFs` and records a batch. Extract reads pages locally. Validate checks identifiers, dates, and duplicates. Commit writes incidents or stops and rolls the batch back.
6. The match key is the CAD number plus the event date. Importing the same PDF again updates in place when values match and records a conflict when a field disagrees. The previous value stays in field history.
7. A page without a CAD number is an exception. The program does not invent an identifier.
8. Officers, narrative lines, citations, and person or vehicle fields from one call stay on that one incident.

Review exceptions in Data Quality before treating a batch as complete.

## How counts work

A keyword in a narrative is not an official count.

- Occurred events can count after the rule is confirmed or a reviewer accepts that incident.
- Alleged, historical, negated, and precautionary wording is stored as a reading and does not count.
- A narrative that contradicts the call type, such as an injury call type with "no injury," does not count as that injury.
- Shoplifting suppresses a second larceny count for the same incident.
- "Forced entry" is not use of force. "No firearm located" is not a firearm recovery. "OJI" is not expanded into a phrase the source did not use.
- Agency codes `1500G`, `1500K`, `0200`, `02`, and `KCMH` are stored as unconfirmed codes. They are not categories and they are not given meanings by this program.
- One incident may belong to more than one category. Do not add category totals and expect the number of calls.
- Percent change is omitted when the comparison baseline is under five incidents. A period with no imported prior-year data is reported as not available, not as zero.
- Officer-initiated and citizen-generated splits stay unavailable until an administrator confirms the call-source lists.
- Citation references in a traffic import are not verified violations. Warnings are counted as warnings only.

## Assignments and the COMPSTAT cycle

Create an assignment from a documented condition. It starts as proposed. Command staff approve it, name one commander, and move it to assigned. Supervisors record progress. Statuses are proposed, approved, assigned, in progress, awaiting resources, completed, effective, partially effective, ineffective, closed, and reopened.

Marking an assignment completed does not mark it effective. Effectiveness is a separate command assessment and needs a measurement note.

A cycle is 14 days:

- Days 1–2: intelligence and assignment.
- Days 3–10: operational implementation.
- Days 11–12: performance assessment.
- Days 13–14: command review.

Opening the next cycle carries unresolved assignments forward and writes that fact on the assignment.

## Reports

The COMPSTAT packet has these sections:

1. Executive summary
2. Previous COMPSTAT action-item review
3. Department-wide activity
4. Significant incidents
5. Crime trends
6. Emerging patterns
7. Geographic hotspots
8. Traffic enforcement
9. Crash analysis
10. Division and shift activity
11. Investigative concerns
12. Resource and staffing considerations
13. Proposed operational interventions
14. Assignments, owners, and deadlines
15. Decisions required from command staff

Each packet lists its qualifications, including that percentages may be withheld and that category counts are not additive. User commentary replaces a section's generated prose and is labeled as edited. Exports go to `Reports` or `Presentations` on the installation drive. CSV cells that start with `=`, `+`, `-`, or `@` are prefixed so a spreadsheet does not treat them as formulas.

Narrative excerpts are off by default.

## Backup

System Health creates an encrypted backup before risky work and on demand. Restore replaces the working database with that snapshot after writing a pre-restore backup. Check `PRAGMA integrity_check` is part of backup creation. Copy encrypted backups to a second approved location. A backup that stays on the COMPSTAT drive is lost with the drive.

## What this program will not do

- It will not fill the dashboard with sample department incidents.
- It will not geocode addresses over the network.
- It will not send narratives to an external model.
- It will not treat an unconfirmed starter rule as an official COMPSTAT number.
- It will not recover a password when no recovery passphrase was set.
