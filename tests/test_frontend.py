import re
import shutil
import subprocess
from pathlib import Path

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


def test_crew_builder_is_integrated_and_logic_is_regression_tested(ingested, tmp_path):
    with TestClient(app) as client:
        html = client.get("/").text
        script_response = client.get("/static/crew_builder.js")

    assert script_response.status_code == 200
    assert 'data-tab="crew"' in html and 'id="crew-builder"' in html
    assert "Подобрать бригаду" in html and "CrewBuilder.setEstimate(r)" in html
    assert "data-tab=\"consultant\"" in html and "function switchTab(tab" in html
    assert "Стоимость работ бригады" in script_response.text
    assert "Материалы по смете" in script_response.text and "Итого с материалами" in script_response.text
    assert "Найдите специалиста для ремонта" in script_response.text
    assert "Вымышленные демонстрационные данные" in script_response.text
    assert "switchTab('crew', 'estimate')" in html

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for crew-builder logic checks")
    check = tmp_path / "crew-check.js"
    module_path = Path(__file__).parents[1] / "app" / "static" / "crew_builder.js"
    check.write_text(f"""
const assert = require('assert');
const crew = require({str(module_path)!r});
const allWorks = Object.keys(crew.WORK_TO_ROLE);
assert.strictEqual(allWorks.length, 20);
assert(allWorks.every(work => crew.WORK_LABELS[work] && !crew.WORK_LABELS[work].includes('_')));
assert.strictEqual(crew.workDescription(['wall_putty', 'priming', 'wall_painting']), 'Шпаклевание, Грунтование, Покраска');
assert.strictEqual(crew.workDescription(['unknown_internal_work']), 'Другие работы');
assert.strictEqual(crew.workDescription(['wall_putty', 'priming', 'wall_painting', 'wallpapering']), '');
const allProfiles = Object.keys(crew.ROLE_DEFS).flatMap(role => crew.candidatesFor(role));
assert.strictEqual(new Set(allProfiles.map(profile => profile.name)).size, allProfiles.length);
assert(allProfiles.every(profile => !('nationality' in profile) && !('ethnicity' in profile)));
const room = (works, floor=20, walls=50) => ({{room: {{works, length_m: 5, width_m: 4, height_m: 2.7}}, floor_area_m2: floor, wall_area_m2: walls, items: []}});
const estimate = {{rooms: [room([
  {{work_type:'electrical_wiring'}}, {{work_type:'electrical_fittings'}},
  {{work_type:'wall_painting', surface:'wall'}}, {{work_type:'tiling', surface:'floor'}}
]), room([{{work_type:'wallpapering', surface:'wall'}}, {{work_type:'tiling', surface:'wall'}}], 10, 30)], total: 125000}};
const roles = crew.deriveCrew(estimate);
assert.deepStrictEqual(new Set(roles.map(x => x.id)), new Set(['electrician', 'painter', 'tiler']));
assert.strictEqual(roles.filter(x => x.id === 'electrician').length, 1);
assert.strictEqual(roles.filter(x => x.id === 'tiler').length, 1);
const selected = Object.fromEntries(roles.map(r => [r.id, crew.candidatesFor(r.id).slice(0, 1)]));
const normal = crew.calculateCost(roles, selected, 999);
const baseline = crew.calculateCost(roles, selected, normal.baselineDays);
const urgent = crew.calculateCost(roles, selected, Math.max(1, normal.baselineDays - 1));
assert.strictEqual(normal.total, baseline.total, 'longer deadlines must not inflate labor cost');
if (normal.baselineDays > 1) assert(urgent.total > baseline.total && urgent.urgency > 1);
assert.strictEqual(crew.calculateCost(roles, selected, 0).valid, false);
assert.strictEqual(crew.calculateCost(roles, selected, -3).valid, false);
assert.strictEqual(crew.deriveCrew({{rooms:[]}}).length, 0);

const painterRole = [{{id:'painter', personDays:6}}];
const painters = crew.candidatesFor('painter');
const onePainter = {{painter:[painters[0]]}};
const twoPainters = {{painter:[painters[0], painters[1]]}};
const threePainters = {{painter:[...painters]}};
const one = crew.calculateCost(painterRole, onePainter, 6);
const two = crew.calculateCost(painterRole, twoPainters, 3);
const three = crew.calculateCost(painterRole, threePainters, 2);
assert.strictEqual(one.baselineDays, 6);
assert.strictEqual(two.baselineDays, 3);
assert.strictEqual(three.baselineDays, 2);
assert.strictEqual(one.baseCost, 6 * painters[0].rate);
assert.strictEqual(two.baseCost, 3 * (painters[0].rate + painters[1].rate));
assert(one.feasible && two.feasible && three.feasible);
assert(!crew.calculateCost(painterRole, onePainter, 2).feasible);
assert(crew.calculateCost(painterRole, onePainter, 2).canAdd);
const multiRole = crew.calculateCost([{{id:'painter', personDays:6}}, {{id:'tiler', personDays:2.5}}],
  {{painter:[painters[0], painters[1]], tiler:[crew.candidatesFor('tiler')[0]]}}, 6);
assert.strictEqual(multiRole.baselineDays, 6); // ceil(6/2) + ceil(2.5/1)
assert.strictEqual(multiRole.workerCount, 3);
const toggled = {{painter:[painters[0]]}};
assert.strictEqual(crew.toggleSpecialist('painter', painters[1].id, toggled).changed, true);
assert.strictEqual(toggled.painter.length, 2);
assert.strictEqual(crew.toggleSpecialist('painter', painters[1].id, toggled).changed, true);
assert.strictEqual(toggled.painter.length, 1);
const blocked = crew.toggleSpecialist('painter', painters[0].id, toggled);
assert.strictEqual(blocked.changed, false);
assert.strictEqual(toggled.painter.length, 1);
assert.strictEqual(new Set(toggled.painter.map(p => p.id)).size, toggled.painter.length);

crew.setEstimate(estimate);
crew.state.selected.electrician = crew.candidatesFor('electrician').slice(0, 2);
const materialTotal = crew.state.estimate.total;
crew.setEstimate({{rooms:[room([{{work_type:'electrical_wiring'}}, {{work_type:'plumbing_rough'}}])], total:100}});
assert.deepStrictEqual(crew.state.selected.electrician.map(p => p.id), crew.candidatesFor('electrician').slice(0, 2).map(p => p.id));
assert.strictEqual(crew.state.selected.plumber.length, 1);
assert(!crew.state.selected.painter && !crew.state.selected.tiler);
assert.strictEqual(materialTotal, 125000);
assert.strictEqual(crew.state.estimate.total, 100);

// Explicit entry modes: a stale estimate does not turn direct navigation into estimate mode.
crew.enterEstimate();
assert.strictEqual(crew.state.mode, 'estimate');
crew.enterDirect();
assert.strictEqual(crew.state.mode, 'direct');
assert.strictEqual(crew.state.estimate.total, 100);

// Direct work/profession search shares the canonical taxonomy and de-duplicates roles.
const direct = {{works:[], professions:[], selected:{{}}, minRate:'', maxRate:'', selectionMessage:''}};
assert(crew.addDirectChoice('work', 'wall_painting', direct));
assert(crew.addDirectChoice('work', 'wallpapering', direct));
assert(crew.addDirectChoice('profession', 'painter', direct));
assert.deepStrictEqual(crew.directRoleIds(direct), ['painter']);
assert(!crew.addDirectChoice('work', 'wall_painting', direct));
assert(crew.addDirectChoice('work', 'electrical_wiring', direct));
assert.deepStrictEqual(new Set(crew.directRoleIds(direct)), new Set(['painter', 'electrician']));

// Multiple specialists and the combined daily rate are independent of estimate costs.
const directPainters = crew.candidatesFor('painter');
assert(crew.toggleDirectSpecialist('painter', directPainters[0].id, direct).changed);
assert(crew.toggleDirectSpecialist('painter', directPainters[1].id, direct).changed);
const electrician = crew.candidatesFor('electrician')[0];
assert(crew.toggleDirectSpecialist('electrician', electrician.id, direct).changed);
let directTotal = crew.directSummary(direct);
assert.strictEqual(directTotal.workerCount, 3);
assert.strictEqual(directTotal.dailyRate, directPainters[0].rate + directPainters[1].rate + electrician.rate);

// Price filters use profile rates and never deselect hidden specialists.
assert.deepStrictEqual(crew.filterCandidates('painter', directPainters[1].rate, directPainters[1].rate).map(p => p.id), [directPainters[1].id]);
assert.strictEqual(crew.filterCandidates('painter', 999999, '').length, 0);
direct.minRate = 999999;
assert.strictEqual(crew.directSummary(direct).workerCount, 3);
direct.minRate = ''; direct.maxRate = '';
assert.strictEqual(crew.filterCandidates('painter', direct.minRate, direct.maxRate).length, 3);

// Removing one of several equivalent works preserves the profession and selection;
// removing the final sources cleans only the now-irrelevant selection.
assert(crew.removeDirectChoice('work', 'wall_painting', direct));
assert(crew.directRoleIds(direct).includes('painter'));
assert.strictEqual(crew.directSummary(direct).workerCount, 3);
assert(crew.removeDirectChoice('work', 'wallpapering', direct));
assert(crew.directRoleIds(direct).includes('painter')); // explicit profession still requires it
assert(crew.removeDirectChoice('profession', 'painter', direct));
assert(!crew.directRoleIds(direct).includes('painter'));
assert(!direct.selected.painter);
assert.strictEqual(crew.directSummary(direct).workerCount, 1);
""", encoding="utf-8")
    checked = subprocess.run([node, str(check)], text=True, capture_output=True)
    assert checked.returncode == 0, checked.stderr
