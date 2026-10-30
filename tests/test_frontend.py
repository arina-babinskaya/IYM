import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _inline_javascript(html: str) -> str:
    return "\n".join(re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, flags=re.DOTALL | re.IGNORECASE))


def test_root_calculator_html_has_parseable_javascript(ingested, tmp_path):
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'id="wizard"' in html and 'id="estimate-result"' in html
    assert "showStep(0)" in html and 'api("/api/v1/taxonomy")' in html
    assert "Смету не удалось рассчитать" in html and 'estimateStatus === "unavailable"' in html
    assert not re.search(r"^(<<<<<<<|=======|>>>>>>>)", html, flags=re.MULTILINE)

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the frontend syntax regression check")
    script = tmp_path / "index-inline.js"
    script.write_text(_inline_javascript(html), encoding="utf-8")
    parsed = subprocess.run([node, "--check", str(script)], text=True, capture_output=True)
    assert parsed.returncode == 0, parsed.stderr
