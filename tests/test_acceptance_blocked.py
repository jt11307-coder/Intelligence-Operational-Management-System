"""Parser acceptance is blocked until a real Warwick CAD PDF is supplied."""

import os
from pathlib import Path

import pytest

ACCEPTANCE_STATUS = "blocked_missing_pdf"


def test_acceptance_is_not_passed():
    assert ACCEPTANCE_STATUS == "blocked_missing_pdf"
    assert not os.environ.get("WPD_CAD_PDF")


@pytest.mark.skip(reason="BLOCKED: the Warwick CAD call-log PDF was not supplied. Acceptance is not passed.")
def test_real_cad_pdf_acceptance():
    pdf = Path(os.environ["WPD_CAD_PDF"])
    assert pdf.is_file()
    raise AssertionError("Do not mark this passed without checking the department PDF by hand.")
