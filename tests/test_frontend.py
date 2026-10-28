import re
import json
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


def test_root_serves_the_same_checked_template(ingested):
    with TestClient(app) as client:
        html = client.get("/").text
        taxonomy = client.get("/api/v1/taxonomy").json()
    assert len(taxonomy["product_categories"]) == 38
    assert "currentEstimateData = r" in html
    assert "openAlternatives(${ri}, ${itemIndex})" in html


def test_recommendation_popover_shows_evidence_explanation_and_honest_empty_state(ingested, tmp_path):
    with TestClient(app) as client:
        html = client.get("/").text
    start = html.index("function recommendationPopover(item)")
    end = html.index("function bindEstimateButtons(r)", start)
    function_source = html[start:end]
    script = tmp_path / "recommendation-popover.js"
    script.write_text("""
const T = {works: {tiling: "Укладка плитки"}};
const esc = s => String(s ?? "").replace(/[&<>\"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'\"':"&quot;"}[c]));
const rub = v => v == null ? "—" : Number(v).toLocaleString("ru-RU") + " ₽";
""" + function_source + """
const full = recommendationPopover({
  product:{name:"Плитка API",result_price:1290,unit:"упак."}, work_type:"tiling", title:"Плитка",
  packages:4,cost:5160,why:["в наличии"],reason:null,recommendation_evidence:{status:"available"},
  recommendation_explanation:"Плитка нужна для облицовки; товар прошёл привязку к этой позиции.",
  alternatives:[{name:"Плитка B",result_price:1400},{name:"Плитка C",result_price:null}]
});
const limited = recommendationPopover({product:{name:"Товар API"},work_type:"unknown",title:"Материал",
  packages:0,cost:0,why:[],alternatives:[],recommendation_evidence:null,recommendation_explanation:null});
process.stdout.write(JSON.stringify({full,limited}));
""", encoding="utf-8")
    rendered = subprocess.run([shutil.which("node"), str(script)], text=True, capture_output=True)
    assert rendered.returncode == 0, rendered.stderr
    values = json.loads(rendered.stdout)
    assert "Почему выбран этот товар?" in values["full"]
    assert "Плитка нужна для облицовки" in values["full"]
    assert all(value not in values["full"] for value in ("1 290 ₽", "4 упак.", "5 160 ₽", "Плитка B"))
    assert "недостаточно проверенных данных" in values["limited"]
    assert "estimateRequestVersion" in html and "requestVersion !== estimateRequestVersion" in html
    assert "Не удалось загрузить рекомендации" in html
    assert 'btn.querySelector(".why-pop")' in html and 'querySelectorAll(".why-pop").forEach(x => x.remove())' in html
