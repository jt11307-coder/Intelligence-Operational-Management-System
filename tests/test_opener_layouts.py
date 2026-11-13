"""The double-click opener finds the program from the extracted zip, launcher\\, and the drive layout."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ZIP_FOLDER = "Intelligence-Operational-Management-System-wpd-compstat"


def _load_start():
    spec = importlib.util.spec_from_file_location("wpd_start", REPO / "launcher" / "start.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


start = _load_start()


def _program_tree(root: Path) -> Path:
    (root / "src" / "wpd_compstat").mkdir(parents=True)
    (root / "src" / "wpd_compstat" / "__init__.py").write_text("", encoding="utf-8")
    (root / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (root / "launcher").mkdir()
    return root


@pytest.fixture
def extracted_zip(tmp_path: Path) -> tuple[Path, Path]:
    drive = tmp_path / "E"
    return drive, _program_tree(drive / ZIP_FOLDER / ZIP_FOLDER)


def test_both_openers_are_the_same_file_without_a_drive_letter():
    root_opener = (REPO / "Open WPD COMPSTAT.bat").read_bytes()
    assert root_opener == (REPO / "launcher" / "Open WPD COMPSTAT.bat").read_bytes()
    text = root_opener.decode("ascii")
    assert "%~dp0" in text
    assert "program\\.venv" not in text
    assert "requirements.txt" not in text
    for letter in "CDEFGL":
        assert f"{letter}:\\" not in text
    for candidate in ("launcher\\start.py", "%HERE%start.py", "program\\launcher\\start.py"):
        assert candidate in text


def test_opener_at_the_zip_root(extracted_zip):
    drive, repo = extracted_zip
    assert start.find_program_root(repo) == repo.resolve()
    assert start.data_root_for(repo.resolve(), repo, drive_root=drive) == drive / "WPD COMPSTAT"
    assert start.venv_dir_for(repo.resolve()) == repo.resolve() / ".venv"


def test_opener_inside_launcher_ignores_the_failed_launcher_program_venv(extracted_zip):
    drive, repo = extracted_zip
    leftover = repo / "launcher" / "program" / ".venv" / "Scripts"
    leftover.mkdir(parents=True)
    (leftover / "python.exe").write_bytes(b"")
    opener = repo / "launcher"
    assert start.find_program_root(opener) == repo.resolve()
    assert start.data_root_for(repo.resolve(), opener, drive_root=drive) == drive / "WPD COMPSTAT"


def test_opener_beside_a_program_folder_on_the_drive(tmp_path):
    install = tmp_path / "E" / "WPD COMPSTAT"
    program = _program_tree(install / "program")
    assert start.find_program_root(install) == program.resolve()
    assert start.data_root_for(program.resolve(), install, drive_root=tmp_path / "other") == install.resolve()
    assert start.venv_dir_for(program.resolve()) == program.resolve() / ".venv"


def test_missing_program_is_reported(tmp_path):
    with pytest.raises(start.StartError, match="Extract the whole zip"):
        start.find_program_root(tmp_path)


def test_data_root_is_initialized_and_its_opener_finds_the_program(extracted_zip):
    drive, _fake = extracted_zip
    data = start.prepare_data_root(REPO, drive / "WPD COMPSTAT")
    manifest = json.loads((data / "WPD-COMPSTAT-INSTALL.json").read_text(encoding="utf-8"))
    assert manifest["packaging_status"] == "source"
    assert (data / "Open WPD COMPSTAT.bat").is_file()
    assert (data / "Launcher" / "start.py").is_file()
    assert start.find_program_root(data) == REPO
    assert start.data_root_for(REPO, data, drive_root=drive / "elsewhere") == data.resolve()
    installation_id = manifest["installation_id"]
    start.prepare_data_root(REPO, data)
    again = json.loads((data / "WPD-COMPSTAT-INSTALL.json").read_text(encoding="utf-8"))
    assert again["installation_id"] == installation_id


def test_venv_is_reinstalled_only_when_requirements_change(extracted_zip):
    _drive, repo = extracted_zip
    calls = []

    def fake_run(argv):
        calls.append(argv)
        if argv[1:3] == ["-m", "venv"]:
            python = start.venv_python(Path(argv[3]))
            python.parent.mkdir(parents=True)
            os.symlink(sys.executable, python)
        return subprocess.CompletedProcess(argv, 0)

    python = start.ensure_venv(repo, run=fake_run)
    assert python == start.venv_python(repo / ".venv")
    assert len(calls) == 2
    start.ensure_venv(repo, run=fake_run)
    assert len(calls) == 2
    (repo / "requirements.txt").write_text("pytest\nnumpy\n", encoding="utf-8")
    start.ensure_venv(repo, run=fake_run)
    assert len(calls) == 3


def test_unusable_leftover_venv_is_replaced(extracted_zip):
    _drive, repo = extracted_zip
    broken = start.venv_python(repo / ".venv")
    broken.parent.mkdir(parents=True)
    broken.write_bytes(b"not a program")
    calls = []

    def fake_run(argv):
        calls.append(argv)
        if argv[1:3] == ["-m", "venv"]:
            python = start.venv_python(Path(argv[3]))
            python.parent.mkdir(parents=True)
            os.symlink(sys.executable, python)
        return subprocess.CompletedProcess(argv, 0)

    start.ensure_venv(repo, run=fake_run)
    assert calls[0][1:3] == ["-m", "venv"]
    assert broken.is_symlink()


def test_start_script_plan_from_a_path_with_spaces(tmp_path):
    repo = _program_tree(tmp_path / "E" / "Downloads (1)" / ZIP_FOLDER)
    result = subprocess.run(
        [sys.executable, str(REPO / "launcher" / "start.py"), str(repo / "launcher") + os.sep + ".", "--plan-only"],
        capture_output=True,
        text=True,
        check=True,
    )
    lines = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert Path(lines["program"]) == repo.resolve()
    assert Path(lines["venv"]) == repo.resolve() / ".venv"
    assert Path(lines["data"]).name == "WPD COMPSTAT"
