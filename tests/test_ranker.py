import copy
from decimal import Decimal

from app.ml.ranker import ContextRanker, calculable, signals
from app.models import Product, ProductBinding
from app.schemas import RoomInput, RoomType

PACK = {"package_area": Decimal(5)}


def item(pid, material="paint", name=None, chars=None, in_stock=True, rating=None, recsys=None, confirmed=False,
         flags=None, price=100, **kw):
    p = Product(id=pid, name=name or f"товар {pid}", result_price=Decimal(price), in_stock=in_stock,
                rating=None if rating is None else Decimal(rating), recsys_rating=recsys,
                raw={"characteristics": [{"name": n, "value": v} for n, v in (chars or {}).items()]}, **kw)
    b = ProductBinding(product_id=pid, material=material, work_types=[], room_types=[], flags=flags or {},
                       source="ml", confidence=0.9, confirmed=confirmed)
    return p, b


def room(kind="living_room", **kw):
    return RoomInput(room_type=RoomType(kind), length_m=4, width_m=3, **kw)


def ids(products):
    return [p.id for p in products]


def test_empty_and_no_duplicates():
    assert ContextRanker().rank([], room()) == []
    a = item(1, **PACK)
    assert ids(ContextRanker().rank([a, item(2, **PACK), a], room())) == [1, 2]


def test_signals_from_real_characteristics():
    s = signals(*item(1, name="Краска интерьерная моющаяся", chars={"Влагостойкость краски": "да",
                                                                    "Морозостойкость": "нет"}))
    assert s["washable"] == 1 and s["moisture_resistant"] == 1 and s["frost_resistant"] == 0
    assert signals(*item(2, chars={"Влагостойкость": "нет"}))["moisture_resistant"] == 0
    assert signals(*item(3, chars={"Тип помещения": "сухое"}))["moisture_resistant"] == 0
    assert signals(*item(4, chars={"Тип помещения": "с умеренной влажностью"}))["moisture_resistant"] == 0.5

    wallpaper = signals(*item(5, "wallpaper", chars={"Влагостойкость обоев": "супермоющиеся"}))
    assert wallpaper["washable"] == 1 and wallpaper["moisture_resistant"] == 1
    assert signals(*item(6, "wallpaper", chars={"Влагостойкость обоев": "моющиеся"}))["washable"] == 2 / 3

    assert signals(*item(7, "laminate", chars={"Износостойкость": "33"}))["wear_class"] == 2 / 3
    assert signals(*item(8, "tile", chars={"Износостойкость": "4"}))["wear_class"] == 4 / 5
    assert signals(*item(9, "linoleum", chars={"Тип напольного покрытия": "полукоммерческий"}))["wear_class"] == 2 / 3
    assert signals(*item(10, "laminate", name="Ламинат 34 класс"))["wear_class"] == 1

    assert signals(*item(11, "lighting", chars={"Степень защиты": "IP44"}))["ip_protected"] == 1
    assert signals(*item(12, "lighting", chars={"Класс защиты IP": "20"}))["ip_protected"] == 0
    assert signals(*item(13, chars={"Аромат": "без запаха"}))["low_emission"] == 1


def test_ip_rating_for_bathroom_lighting():
    plain = item(1, "lighting", rating=5)
    ip44 = item(2, "lighting", chars={"Степень защиты": "IP44"})
    assert ids(ContextRanker().rank([plain, ip44], room("bathroom"))) == [2, 1]
    assert ids(ContextRanker().rank([plain, ip44], room("bedroom"))) == [1, 2]


def test_humidity_raises_moisture_weight():
    plain = item(1, rating=5, **PACK)
    wet = item(2, rating=3, chars={"Влагостойкость краски": "да"}, **PACK)
    assert ids(ContextRanker().rank([plain, wet], room("bedroom"))) == [1, 2]
    assert ids(ContextRanker().rank([plain, wet], room("bedroom", humidity="high"))) == [2, 1]


def test_weights_depend_on_material_and_room():
    washable_tile = item(1, "tile", name="Плитка моющаяся", **PACK)
    anti_slip_tile = item(2, "tile", name="Керамогранит противоскользящий R10", **PACK)
    assert ids(ContextRanker().rank([washable_tile, anti_slip_tile], room("bathroom"))) == [2, 1]
    assert ids(ContextRanker().rank([washable_tile, anti_slip_tile], room("bedroom"))) == [1, 2]

    class31 = item(1, "laminate", chars={"Износостойкость": "31"}, **PACK)
    class34 = item(2, "laminate", chars={"Износостойкость": "34"}, rating=1, **PACK)
    best = ContextRanker().score([class31, class34], room("hallway"))
    assert ids([s.product for s in best]) == [2, 1] and best[0].parts["wear_class"] == 4.0


def test_base_signals_and_price_ignored():
    out_of_stock = item(1, in_stock=False, rating=5, **PACK)
    no_pack = item(2, rating=5)
    good = item(3, price=99999, **PACK)
    assert ids(ContextRanker().rank([out_of_stock, no_pack, good], room())) == [3, 2, 1]
    cheap, expensive = item(5, price=1, **PACK), item(4, price=1000, **PACK)
    assert ids(ContextRanker().rank([cheap, expensive], room())) == [4, 5]


def test_missing_data_deterministic_and_no_mutation():
    cands = [item(i, chars=None) for i in (5, 3, 4)]
    for p, _ in cands:
        p.raw = None
    before = copy.deepcopy([(p.id, b.flags) for p, b in cands])
    assert ids(ContextRanker().rank(cands, room())) == ids(ContextRanker().rank(cands[::-1], room())) == [3, 4, 5]
    assert [(p.id, b.flags) for p, b in cands] == before


def test_calculable():
    assert calculable(*item(1, unit="м²"))
    assert calculable(*item(2, "skirting"))
    assert not calculable(*item(3))
