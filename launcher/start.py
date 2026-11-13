"""Start WPD COMPSTAT from wherever `Open WPD COMPSTAT.bat` was double-clicked.

Run by the opener with the system Python. Uses only the standard library, because the
program's virtual environment may not exist yet.

Supported layouts, all found from the opener's own folder:

- the extracted GitHub zip, opener at the repository root;
- the same tree, opener inside `launcher\\`;
- the drive layout, opener beside a `program\\` folder inside `WPD COMPSTAT\\`;
- an installation folder whose `Configuration\\program-root.txt` names the program.

The Python packages go in `Runtime\\py3NN` inside the data folder, for example
`E:\\WPD COMPSTAT\\Runtime\\py314`. That path is short, so PySide6 files stay under the
260-character Windows path limit wherever the zip was extracted.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

INSTALL_FOLDER_NAME = "WPD COMPSTAT"
MANIFEST_NAME = "WPD-COMPSTAT-INSTALL.json"
POINTER_RELATIVE_PATH = Path("Configuration") / "program-root.txt"
RUNTIME_FOLDER = "Runtime"
STAMP_NAME = "wpd-install-complete.txt"
SUPPORTED_PYTHON = ((3, 12), (3, 13), (3, 14))
WINDOWS_PATH_LIMIT = 259
# Longest file inside the installed wheels is 151 characters below site-packages, in PySide6.
DEEPEST_PACKAGE_PATH = 160
SMOKE_IMPORTS = (
    "PySide6.QtWidgets, PySide6.QtGui, PySide6.QtCore, pymupdf, pdfplumber, pandas, numpy, "
    "matplotlib, reportlab, pptx, openpyxl, cryptography"
)


class StartError(Exception):
    pass


def python_version_problem(version: tuple[int, ...] = tuple(sys.version_info[:2])) -> str | None:
    if tuple(version[:2]) in SUPPORTED_PYTHON:
        return None
    found = ".".join(str(part) for part in version[:2])
    return (
        f"This PC is running Python {found}. WPD COMPSTAT needs Python 3.12, 3.13, or 3.14.\n"
        "Install Python 3.14 from python.org, then double-click Open WPD COMPSTAT.bat again."
    )


def is_program_root(path: Path) -> bool:
    return (path / "requirements.txt").is_file() and (path / "src" / "wpd_compstat" / "__init__.py").is_file()


def _pointer_target(folder: Path) -> Path | None:
    pointer = folder / POINTER_RELATIVE_PATH
    if not pointer.is_file():
        return None
    text = pointer.read_text(encoding="utf-8").strip()
    return Path(text) if text else None


def program_candidates(opener_dir: Path) -> list[Path]:
    candidates = [opener_dir, opener_dir / "program", opener_dir.parent]
    target = _pointer_target(opener_dir)
    if target is not None:
        candidates.append(target)
    return candidates


def find_program_root(opener_dir: Path) -> Path:
    opener_dir = Path(opener_dir).resolve()
    for candidate in program_candidates(opener_dir):
        if is_program_root(candidate):
            return candidate.resolve()
    raise StartError(
        f"The program files were not found from {opener_dir}. "
        "Extract the whole zip and double-click Open WPD COMPSTAT.bat in the extracted folder."
    )


def data_root_for(program_root: Path, opener_dir: Path, drive_root: Path | None = None) -> Path:
    """Data stays outside the extracted tree, so deleting that tree for an update keeps the database."""
    opener_dir = Path(opener_dir).resolve()
    if program_root == (opener_dir / "program").resolve() and opener_dir.name == INSTALL_FOLDER_NAME:
        return opener_dir
    if opener_dir.name == INSTALL_FOLDER_NAME and _pointer_target(opener_dir) is not None:
        return opener_dir
    if drive_root is None:
        drive_root = Path(program_root.anchor)
    return Path(drive_root) / INSTALL_FOLDER_NAME


def venv_dir_for(data_root: Path, version: tuple[int, ...] = tuple(sys.version_info[:2])) -> Path:
    return data_root / RUNTIME_FOLDER / f"py{version[0]}{version[1]}"


def venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def install_fingerprint(program_root: Path) -> str:
    digest = hashlib.sha256((program_root / "requirements.txt").read_bytes()).hexdigest()
    return f"python={sys.version_info[0]}.{sys.version_info[1]} requirements={digest}"


def venv_is_current(program_root: Path, venv: Path) -> bool:
    """Only a venv whose install finished and passed the import check carries a matching stamp."""
    stamp = venv / STAMP_NAME
    if not venv_python(venv).is_file() or not stamp.is_file():
        return False
    return stamp.read_text(encoding="utf-8").strip() == install_fingerprint(program_root)


def long_paths_enabled() -> bool:
    if os.name != "nt":
        return True
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return winreg.QueryValueEx(key, "LongPathsEnabled")[0] == 1
    except OSError:
        return False


def path_length_problem(venv: Path, *, windows: bool = os.name == "nt", long_paths: bool | None = None) -> str | None:
    if not windows:
        return None
    if long_paths is None:
        long_paths = long_paths_enabled()
    if long_paths:
        return None
    if len(str(venv / "Lib" / "site-packages")) + 1 + DEEPEST_PACKAGE_PATH <= WINDOWS_PATH_LIMIT:
        return None
    return (
        f"The folder {venv} is too deep for Windows to hold the program's files.\n"
        f"Move the {INSTALL_FOLDER_NAME} folder to the top of the drive, for example E:\\{INSTALL_FOLDER_NAME}, "
        "then double-click Open WPD COMPSTAT.bat again."
    )


def _long_path(path: Path) -> str:
    text = str(path.resolve())
    if os.name == "nt" and not text.startswith("\\\\?\\"):
        return "\\\\?\\" + text
    return text


def _clear_readonly_and_retry(function, path, _exc):
    os.chmod(path, stat.S_IWRITE)
    function(path)


def remove_tree(path: Path) -> None:
    if path.exists() or path.is_symlink():
        shutil.rmtree(_long_path(path), onexc=_clear_readonly_and_retry)


def _runs(python: Path, code: str = "import sys", env: dict[str, str] | None = None) -> bool:
    try:
        return subprocess.run([str(python), "-c", code], capture_output=True, env=env).returncode == 0
    except OSError:
        return False


def ensure_venv(program_root: Path, venv: Path, run=subprocess.run, check=_runs) -> Path:
    python = venv_python(venv)
    if venv_is_current(program_root, venv) and check(python):
        return python
    if venv.exists():
        print("Removing an unfinished program environment from an earlier start...")
        remove_tree(venv)
    problem = path_length_problem(venv)
    if problem:
        raise StartError(problem)
    print(f"Creating the program environment in {venv} ...")
    venv.parent.mkdir(parents=True, exist_ok=True)
    if run([sys.executable, "-m", "venv", str(venv)]).returncode != 0:
        raise StartError("Python could not create the program environment.")
    print("Installing the program's Python packages. The first start takes several minutes...")
    install = [
        str(python), "-m", "pip", "install",
        "--no-deps", "--only-binary=:all:", "--disable-pip-version-check", "--no-warn-script-location",
    ]
    wheels = program_root / "wheels"
    if wheels.is_dir():
        install += ["--no-index", "--find-links", str(wheels)]
    install += ["-r", str(program_root / "requirements.txt")]
    if run(install).returncode != 0:
        remove_tree(venv)
        raise StartError(
            "The Python packages did not install. Check the internet connection, "
            "then double-click Open WPD COMPSTAT.bat again. The unfinished environment was removed."
        )
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    if not check(python, f"import {SMOKE_IMPORTS}", env):
        remove_tree(venv)
        raise StartError(
            "The Python packages installed but did not load. "
            "Double-click Open WPD COMPSTAT.bat again. The unfinished environment was removed."
        )
    (venv / STAMP_NAME).write_text(install_fingerprint(program_root) + "\n", encoding="utf-8")
    return python


def prepare_data_root(program_root: Path, data_root: Path) -> Path:
    try:
        data_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        fallback = program_root.parent / INSTALL_FOLDER_NAME
        print(f"{data_root} could not be created. Using {fallback} instead.")
        data_root = fallback
        data_root.mkdir(parents=True, exist_ok=True)
    if not (data_root / MANIFEST_NAME).is_file():
        sys.path.insert(0, str(program_root / "src"))
        from wpd_compstat.install import initialize_installation

        initialize_installation(data_root, docs_dir=program_root / "docs", launcher_dir=program_root / "launcher")
    pointer = data_root / POINTER_RELATIVE_PATH
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(str(program_root) + "\n", encoding="utf-8")
    return data_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="start.py")
    parser.add_argument("opener_dir", help="Folder that holds the Open WPD COMPSTAT.bat that was double-clicked")
    parser.add_argument("--plan-only", action="store_true", help="Print the resolved folders and stop")
    args = parser.parse_args(argv)
    problem = python_version_problem()
    if problem:
        print(problem)
        return 1
    opener_dir = Path(args.opener_dir).resolve()
    try:
        program_root = find_program_root(opener_dir)
        data_root = data_root_for(program_root, opener_dir)
        if args.plan_only:
            print(f"program={program_root}\ndata={data_root}\nvenv={venv_dir_for(data_root)}")
            return 0
        data_root = prepare_data_root(program_root, data_root)
        python = ensure_venv(program_root, venv_dir_for(data_root))
    except StartError as exc:
        print(exc)
        return 1
    print(f"Program: {program_root}")
    print(f"Data:    {data_root}")
    env = os.environ.copy()
    src = str(program_root / "src")
    env["PYTHONPATH"] = src if not env.get("PYTHONPATH") else os.pathsep.join((src, env["PYTHONPATH"]))
    return subprocess.call([str(python), "-m", "wpd_compstat", "--root", str(data_root)], env=env, cwd=str(program_root))


if __name__ == "__main__":
    raise SystemExit(main())
