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
    data = start.data_root_for(repo.resolve(), repo, drive_root=drive)
    assert data == drive / "WPD COMPSTAT"
    assert start.venv_dir_for(data, (3, 14)) == drive / "WPD COMPSTAT" / "Runtime" / "py314"


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
    data = start.data_root_for(program.resolve(), install, drive_root=tmp_path / "other")
    assert data == install.resolve()
    assert start.venv_dir_for(data, (3, 12)) == install.resolve() / "Runtime" / "py312"


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


class FakeInstaller:
    """Stands in for `python -m venv` and pip. Records calls and can fail one step."""

    def __init__(self, fail_pip: bool = False, imports_load: bool = True):
        self.calls: list[list[str]] = []
        self.fail_pip = fail_pip
        self.imports_load = imports_load

    def run(self, argv):
        self.calls.append(list(argv))
        if argv[1:3] == ["-m", "venv"]:
            python = start.venv_python(Path(argv[3]))
            python.parent.mkdir(parents=True)
            python.write_bytes(b"python")
            return subprocess.CompletedProcess(argv, 0)
        if self.fail_pip:
            (Path(argv[0]).parents[1] / "half-installed").mkdir()
            return subprocess.CompletedProcess(argv, 1)
        return subprocess.CompletedProcess(argv, 0)

    def check(self, python, code="import sys", env=None):
        if code == "import sys":
            return Path(python).is_file()
        return self.imports_load

    def pip_calls(self):
        return [argv for argv in self.calls if "pip" in argv]


def test_venv_is_built_once_and_rebuilt_when_requirements_change(extracted_zip):
    drive, repo = extracted_zip
    venv = start.venv_dir_for(drive / "WPD COMPSTAT", (3, 14))
    fake = FakeInstaller()
    python = start.ensure_venv(repo, venv, run=fake.run, check=fake.check)
    assert python == start.venv_python(venv)
    assert not (repo / ".venv").exists()
    pip = fake.pip_calls()[0]
    assert "--no-deps" in pip and "--only-binary=:all:" in pip
    assert pip[-1] == str(repo / "requirements.txt")
    start.ensure_venv(repo, venv, run=fake.run, check=fake.check)
    assert len(fake.calls) == 2
    (repo / "requirements.txt").write_text("pytest\nnumpy\n", encoding="utf-8")
    start.ensure_venv(repo, venv, run=fake.run, check=fake.check)
    assert len(fake.calls) == 4


def test_partial_venv_from_a_failed_install_is_removed_and_rebuilt(extracted_zip):
    drive, repo = extracted_zip
    venv = start.venv_dir_for(drive / "WPD COMPSTAT", (3, 14))
    with pytest.raises(start.StartError, match="did not install"):
        start.ensure_venv(repo, venv, run=FakeInstaller(fail_pip=True).run, check=FakeInstaller().check)
    assert not venv.exists()
    start.venv_python(venv).parent.mkdir(parents=True)
    start.venv_python(venv).write_bytes(b"python")
    (venv / "Lib" / "site-packages" / "PySide6").mkdir(parents=True)
    fake = FakeInstaller()
    start.ensure_venv(repo, venv, run=fake.run, check=fake.check)
    assert fake.calls[0][1:3] == ["-m", "venv"]
    assert not (venv / "Lib" / "site-packages" / "PySide6").exists()
    assert start.venv_is_current(repo, venv)


def test_venv_whose_packages_do_not_load_is_not_kept(extracted_zip):
    drive, repo = extracted_zip
    venv = start.venv_dir_for(drive / "WPD COMPSTAT", (3, 14))
    fake = FakeInstaller(imports_load=False)
    with pytest.raises(start.StartError, match="did not load"):
        start.ensure_venv(repo, venv, run=fake.run, check=fake.check)
    assert not venv.exists()


def test_windows_path_limit_is_checked_before_installing():
    from pathlib import PureWindowsPath

    failed_run = PureWindowsPath(
        "E:/Intelligence-Operational-Management-System-wpd-compstat (1)/"
        "Intelligence-Operational-Management-System-wpd-compstat/.venv"
    )
    problem = start.path_length_problem(failed_run, windows=True, long_paths=False)
    assert problem and "too deep" in problem
    assert start.path_length_problem(failed_run, windows=True, long_paths=True) is None
    short = PureWindowsPath("E:/WPD COMPSTAT/Runtime/py314")
    assert start.path_length_problem(short, windows=True, long_paths=False) is None


def test_python_versions_are_named_in_plain_words():
    for supported in ((3, 12), (3, 13), (3, 14)):
        assert start.python_version_problem(supported) is None
    for unsupported in ((3, 11), (3, 15)):
        message = start.python_version_problem(unsupported)
        found = f"{unsupported[0]}.{unsupported[1]}"
        assert f"Python {found}" in message
        assert "3.12, 3.13, or 3.14" in message


def _pinned(path: Path) -> dict[str, str]:
    from packaging.utils import canonicalize_name

    pins = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            name, version = line.split("==")
            pins[canonicalize_name(name)] = version
    return pins


UNUSED_DECLARED = {
    "pymupdf": {"onnxruntime", "pymupdf4llm", "pymupdf-layout", "networkx", "pyyaml", "psutil", "tabulate"},
}


def test_requirements_are_complete_for_no_deps_install():
    from importlib import metadata

    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name

    pins = _pinned(REPO / "requirements.txt")
    assert "pyside6" not in pins and "pyside6-addons" not in pins and "pyside6-webengine" not in pins
    assert not {"onnxruntime", "pymupdf4llm", "pymupdf-layout"} & set(pins)
    environments = [
        {"sys_platform": "win32", "platform_system": "Windows", "os_name": "nt", "python_version": version}
        for version in ("3.12", "3.13", "3.14")
    ]
    missing = []
    for name in pins:
        for raw in metadata.requires(name) or []:
            requirement = Requirement(raw)
            dependency = canonicalize_name(requirement.name)
            if dependency in UNUSED_DECLARED.get(name, set()):
                continue
            needed = requirement.marker is None or any(
                requirement.marker.evaluate({**env, "extra": ""}) for env in environments
            )
            if needed and dependency not in pins:
                missing.append(f"{name} -> {raw}")
    assert missing == []


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
    assert Path(lines["data"]).name == "WPD COMPSTAT"
    assert Path(lines["venv"]).parent == Path(lines["data"]) / "Runtime"
    assert ZIP_FOLDER not in lines["venv"]
