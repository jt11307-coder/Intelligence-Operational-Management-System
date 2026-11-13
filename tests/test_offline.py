"""Offline boundary: the application does not call cloud APIs."""

from pathlib import Path


def test_source_does_not_import_network_clients():
    banned = ("import requests", "import httpx", "import openai", "import boto3", "api.openai.com")
    root = Path(__file__).resolve().parents[1] / "src"
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for item in banned:
            assert item not in text, path
