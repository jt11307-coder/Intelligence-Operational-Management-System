"""Parser acceptance against real Warwick CAD PDFs. It runs only on the agency machine; the PDFs never enter the repository.

Set WPD_CAD_PDF_DIR to a local folder of call-log PDFs to run it. Only file names and counts are reported.
"""

import os
from pathlib import Path

import pytest

from wpd_compstat.import_engine.call_log import CALL_LOG_PROFILE, count_call_starts, parse_call_log
from wpd_compstat.import_engine.extract import extract_pages


@pytest.mark.skipif(
    not os.environ.get("WPD_CAD_PDF_DIR"),
    reason="Set WPD_CAD_PDF_DIR to a folder of real CAD call-log PDFs on the agency machine.",
)
def test_real_call_logs_reconcile(tmp_path):
    pdfs = sorted(Path(os.environ["WPD_CAD_PDF_DIR"]).rglob("*.pdf"))
    assert pdfs
    for pdf in pdfs:
        pages, _warnings = extract_pages(pdf, ocr=False, work_dir=tmp_path)
        output = parse_call_log(pages, CALL_LOG_PROFILE)
        assert output.recognized, pdf.name
        assert output.errors == [], pdf.name
        assert len(output.incidents) == count_call_starts(pages), pdf.name
        assert all(incident.event_date and incident.cad_number for incident in output.incidents), pdf.name
