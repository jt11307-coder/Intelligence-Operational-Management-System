# WPD COMPSTAT Intelligence & Operational Management System

Offline desktop application for Warwick Police Department COMPSTAT. The program stores call-log records, classifications, assignments, and reports on an external drive. It does not call cloud APIs and it does not ship with department incidents.

The packaged Windows executable has not been built. This tree was developed on Linux. Windows packaging files are in `packaging/`. See `docs/limitations-register.md`.

## Start on Windows

1. Download the [wpd-compstat zip](https://github.com/jt11307-coder/Intelligence-Operational-Management-System/archive/refs/heads/wpd-compstat.zip).
2. Delete any older extracted copy. Keep `E:\WPD COMPSTAT`, which holds the data.
3. Extract the zip to `E:\`.
4. Double-click `Open WPD COMPSTAT.bat` at the top of the extracted folder.

The first start needs Python 3.12, 3.13, or 3.14 from python.org and an internet connection. Data and the Python packages are kept in `WPD COMPSTAT` at the top of the same drive, with the packages in `WPD COMPSTAT\Runtime`. See `docs/installation-guide.md`.

## Run from source

```bash
python3 -m venv .venv
.venv/bin/pip install --no-deps --only-binary=:all: -r requirements.txt -r requirements-dev.txt
PYTHONPATH=src .venv/bin/python -c "from pathlib import Path; from wpd_compstat.install import initialize_installation; initialize_installation(Path('/path/to/drive/WPD COMPSTAT'), docs_dir=Path('docs'), launcher_dir=Path('launcher'))"
PYTHONPATH=src WPD_COMPSTAT_ALLOW_SOURCE=1 .venv/bin/python -m wpd_compstat --root "/path/to/drive/WPD COMPSTAT"
```

The installation folder name must be `WPD COMPSTAT`. The first launch creates the administrator. There is no default password.

## Tests

```bash
.venv/bin/python -m pytest
```

Parser acceptance against a real Warwick CAD PDF is skipped until that PDF is supplied. See `docs/test-results.md`.
