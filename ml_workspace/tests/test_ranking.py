from ranker import Candidate, rank_candidates


def candidate(pid, **kwargs):
    base = dict(product_id=pid, work_types=("tiling",), material_roles=(("tiling", "primary_material"),),
                room_types=("bathroom",), properties={"moisture_resistant": True}, applicability_score=.8,
                quality_score=None, price=100.0, in_stock=True)
    base.update(kwargs); return Candidate(**base)


def test_ranking_hard_room_and_property_filters():
    items = [candidate(1), candidate(2, room_types=("living_room",)), candidate(3, properties={"moisture_resistant": False})]
    result = rank_candidates(items, "tiling", "primary_material", "bathroom", {"moisture_resistant": True})
    assert [x.product_id for x in result] == [1]


def test_quality_not_price_and_stable_top_k():
    expensive = candidate(2, quality_score=.9, quality_evidence=("load_class",), price=1000)
    cheap = candidate(1, quality_score=.5, price=100)
    result = rank_candidates([cheap, expensive], "tiling", "primary_material", strategy="quality", top_k=2)
    assert [x.product_id for x in result] == [2, 1]
    assert result[0].price == 1000


def test_budget_is_constraint_not_quality_proxy():
    result = rank_candidates([candidate(1, price=90), candidate(2, price=110)], "tiling", "primary_material",
                             strategy="budget", max_price=100)
    assert [x.product_id for x in result] == [1]
