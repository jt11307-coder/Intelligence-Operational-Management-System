"""Start WPD COMPSTAT from wherever `Open WPD COMPSTAT.bat` was double-clicked.

Run by the opener with the system Python. Uses only the standard library, because the
program's virtual environment may not exist yet.

Supported layouts, all found from the opener's own folder:

- the extracted GitHub zip, opener at the repository root;
- the same tree, opener inside `launcher\\`;
- the drive layout, opener beside a `program\\` folder inside `WPD COMPSTAT\\`;
- an installation folder whose `Configuration\\program-root.txt` names the program.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

INSTALL_FOLDER_NAME = "WPD COMPSTAT"
MANIFEST_NAME = "WPD-COMPSTAT-INSTALL.json"
POINTER_RELATIVE_PATH = Path("Configuration") / "program-root.txt"
STAMP_NAME = "wpd-requirements.sha256"
MIN_PYTHON = (3, 11)


class StartError(Exception):
    pass


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


def venv_dir_for(program_root: Path) -> Path:
    return program_root / ".venv"


def venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def requirements_digest(program_root: Path) -> str:
    return hashlib.sha256((program_root / "requirements.txt").read_bytes()).hexdigest()


def venv_is_current(program_root: Path, venv: Path) -> bool:
    stamp = venv / STAMP_NAME
    if not venv_python(venv).is_file() or not stamp.is_file():
        return False
    return stamp.read_text(encoding="utf-8").strip() == requirements_digest(program_root)


def _runs(python: Path) -> bool:
    try:
        return subprocess.run([str(python), "-c", "import sys"], capture_output=True).returncode == 0
    except OSError:
        return False


def ensure_venv(program_root: Path, run=subprocess.run) -> Path:
    venv = venv_dir_for(program_root)
    python = venv_python(venv)
    if venv_is_current(program_root, venv) and _runs(python):
        return python
    if venv.exists() and not _runs(python):
        print("Removing an unusable program environment...")
        shutil.rmtree(venv)
    if not python.is_file():
        print(f"Creating the program environment in {venv} ...")
        if run([sys.executable, "-m", "venv", str(venv)]).returncode != 0:
            raise StartError("Python could not create the program environment.")
    print("Installing the program's Python packages. The first start takes several minutes...")
    install = [str(python), "-m", "pip", "install", "--disable-pip-version-check"]
    wheels = program_root / "wheels"
    if wheels.is_dir():
        install += ["--no-index", "--find-links", str(wheels)]
    install += ["-r", str(program_root / "requirements.txt")]
    if run(install).returncode != 0:
        raise StartError("The Python packages did not install. Check the internet connection and open the program again.")
    (venv / STAMP_NAME).write_text(requirements_digest(program_root) + "\n", encoding="utf-8")
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
    if sys.version_info < MIN_PYTHON:
        print("WPD COMPSTAT needs Python 3.11 or newer. Install Python 3.12 from python.org.")
        return 1
    opener_dir = Path(args.opener_dir).resolve()
    try:
        program_root = find_program_root(opener_dir)
        data_root = data_root_for(program_root, opener_dir)
        if args.plan_only:
            print(f"program={program_root}\ndata={data_root}\nvenv={venv_dir_for(program_root)}")
            return 0
        python = ensure_venv(program_root)
        data_root = prepare_data_root(program_root, data_root)
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
