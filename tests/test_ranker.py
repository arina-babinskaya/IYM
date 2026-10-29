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


def test_price_is_normalized_and_moderate():
    cheap, expensive = item(1, price=100, **PACK), item(2, price=900, **PACK)
    assert ids(ContextRanker().rank([expensive, cheap], room())) == [1, 2]
    unknown_stock = item(3, price=900, in_stock=None, **PACK)
    assert ids(ContextRanker().rank([unknown_stock, expensive], room())) == [2, 3]
    assert ContextRanker().score([expensive], room())[0].parts["in_stock"] == 1
    big_can = item(4, price=900, specs={"volume_l": "9"})
    small_can = item(5, price=150, specs={"volume_l": "0.9"})
    best = ContextRanker().score([small_can, big_can], room())
    assert ids([s.product for s in best]) == [4, 5] and best[0].unit_price == 100 and best[0].basis == "l"
    wet_expensive = item(6, price=5000, chars={"Влагостойкость краски": "да"}, **PACK)
    assert ids(ContextRanker().rank([cheap, wet_expensive], room("bathroom"))) == [6, 1]


def test_variants_and_picks():
    premium = item(1, price=3000, chars={"Влагостойкость краски": "да", "Аромат": "без запаха"}, **PACK)
    good_cheap = item(2, price=900, chars={"Влагостойкость краски": "да"}, **PACK)
    junk_cheap = item(3, price=10, **PACK)
    v = ContextRanker().variants([premium, good_cheap, junk_cheap], room("kitchen"))
    assert v["quality"].product.id == 1
    assert v["cheapest"].product.id == 2
    assert ids(ContextRanker().rank([premium, good_cheap, junk_cheap], room("kitchen", picks=[3]))) [0] == 3


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


def test_outdoor_lights_pushed_down_indoors():
    street = item(1, "lighting", name="Светильник уличный настенный IP54")
    indoor = item(2, "lighting", name="Светильник потолочный для ванной IP44")
    assert ids(ContextRanker().rank([street, indoor], room("bathroom"))) == [2, 1]
    assert ContextRanker().score([street], room("bathroom"))[0].parts["outdoor"] == -10
    assert "outdoor" not in ContextRanker().score([street], room("balcony"))[0].parts


def test_typical_product_and_filled_card_win_ties():
    tee = item(1, "pipes", name="тройник ПНД 25х3/4")
    pipe = item(2, "pipes", name="труба полипропиленовая 20 мм 2 м")
    assert ids(ContextRanker().rank([tee, pipe], room("bathroom"))) == [2, 1]
    empty = item(3, "pipes", name="труба ПНД 25 мм")
    filled = item(4, "pipes", name="труба ПНД 32 мм", chars={"Диаметр": "32", "Материал": "ПНД"})
    assert ids(ContextRanker().rank([empty, filled], room())) == [4, 3]


def test_room_in_name_and_refined_typical():
    kitchen = item(1, "plumbing", name="смеситель для кухни AM.PM Gem хром")
    bath = item(2, "plumbing", name="смеситель для ванны с душем")
    assert ids(ContextRanker().rank([kitchen, bath], room("bathroom"))) == [2, 1]
    assert ids(ContextRanker().rank([kitchen, bath], room("kitchen"))) == [1, 2]
    cord = item(3, "cable", name="кабель с вилкой DORI 2x0,75")
    power = item(4, "cable", name="кабель ВВГнг-LS 3х2,5 10м")
    assert ids(ContextRanker().rank([cord, power], room())) == [4, 3]


def test_room_words_match_whole_words_only():
    from app.ml.ranker import room_match

    assert room_match("труба PPR армированная стекловолокном", RoomType.bathroom) == 0
    assert room_match("кабель экранированный", RoomType.bathroom) == 0
    assert room_match("смеситель для ванны", RoomType.bathroom) == 1
    assert room_match("смеситель для кухни", RoomType.bathroom) == -1


def test_typical_outweighs_moisture_of_wrong_product():
    moment = item(1, "wallpaper_glue", name="клей МОМЕНТ особопрочный 30мл", chars={"Влагостойкость": "да"})
    glue = item(2, "wallpaper_glue", name="клей обойный KLEO флизелиновый 240г", **PACK)
    assert ids(ContextRanker().rank([moment, glue], room("bathroom"))) == [2, 1]


def test_quality_pct_is_relative_to_ideal_product():
    from app.taxonomy import Material

    r = ContextRanker()
    plain = item(1, "laminate", name="ламинат Дуб 33 класс", chars={"Износостойкость": "33"}, in_stock=None, **PACK)
    best = item(2, "laminate", name="ламинат Дуб 34 класс", chars={"Износостойкость": "34", "Аромат": "без запаха"},
                in_stock=None, **PACK)
    scored = r.score([plain, best], room("bedroom"))
    ideal = r.ideal_quality(Material.laminate, room("bedroom"), scored)
    pct = {s.product.id: r.quality_pct(s, ideal) for s in scored}
    assert ideal == 11 and pct[2] == 100 and 75 <= pct[1] <= 80

    tile = item(3, "tile", name="керамогранит влагостойкий", chars={"Влагостойкость": "да"}, in_stock=None, **PACK)
    tiles = r.score([tile], room("bathroom"))
    assert r.quality_pct(tiles[0], r.ideal_quality(Material.tile, room("bathroom"), tiles)) == 75


def test_moisture_filter_uses_catalog_characteristics():
    from app.ml.ranker import has_flags

    wet = ["moisture_resistant"]
    assert has_flags(*item(1, chars={"Влагостойкость краски": "да"}), wet)
    assert has_flags(*item(2, name="Гипсокартон влагостойкий ГКЛВ"), wet)
    assert has_flags(*item(3, flags={"moisture_resistant": True}), wet)
    assert has_flags(*item(4, chars={"Тип помещения": "с умеренной влажностью"}), wet)
    assert has_flags(*item(5, name="Краска интерьерная"), wet)
    assert not has_flags(*item(6, chars={"Влагостойкость": "нет"}), wet)
    assert not has_flags(*item(7, chars={"Тип помещения": "сухое"}), wet)
    assert has_flags(*item(8, chars={"Влагостойкость обоев": "влагостойкие"}), wet)


def test_unknown_moisture_ranked_below_resistant_in_bathroom():
    unknown = item(1, name="Краска интерьерная", rating=5, **PACK)
    wet = item(2, name="Краска для стен", chars={"Влагостойкость краски": "да"}, **PACK)
    assert ids(ContextRanker().rank([unknown, wet], room("bathroom"))) == [2, 1]


def test_typical_wiring_cable_socket_and_switch():
    from app.ml.ranker import _typical
    from app.taxonomy import Material

    def typical(name, material):
        return _typical(material, name) == 1

    assert typical("кабель ВВГнг-LS 3х2,5 10м", Material.cable)
    assert typical("кабель NYM 3х1,5", Material.cable)
    assert not typical("провод ПуГВнг(А) LS 1х4 желто-зеленый", Material.cable)
    assert not typical("кабель ШВВП ЭРА 2х0,5 50м гибкий плоский", Material.cable)
    assert typical("розетка 1 пост с заземлением белая", Material.socket)
    assert not typical("розетка встраиваемая Эконом, без заземления, белая", Material.socket)
    assert typical("выключатель 1-клавишный IP20 белый", Material.switch)
    assert not typical("выключатель на шнур TDM с красной кнопкой 6А", Material.switch)


def test_why_warns_when_moisture_unknown():
    from app.api.picker import why

    bath = room("bathroom")
    unknown = ContextRanker().score([item(1, name="Краска интерьерная", **PACK)], bath)[0]
    wet = ContextRanker().score([item(2, chars={"Влагостойкость краски": "да"}, **PACK)], bath)[0]
    assert "влагостойкость не указана — проверьте перед покупкой" in why(unknown, True)
    assert not any("не указана" in w for w in why(wet, True))
    assert not any("не указана" in w for w in why(unknown, False))


def test_decorative_finish_pushed_down_in_plain_works():
    deco = item(1, "plaster", name="штукатурка декоративная BERGAUF Dekor короед 25 кг", rating=5, **PACK)
    plain = item(2, "plaster", name="штукатурка гипсовая Knauf Ротбанд 30 кг", **PACK)
    scored = ContextRanker().score([deco, plain], room())
    assert ids([s.product for s in scored]) == [2, 1] and scored[1].parts["decorative"] == -8
    border = item(3, "tile", name="бордюр настенный Ромашка 25х6", **PACK)
    tile = item(4, "tile", name="плитка настенная Ромашка 25х40", **PACK)
    assert ids(ContextRanker().rank([border, tile], room("bathroom"))) == [4, 3]
    satin = item(5, "paint", name="краска интерьерная шелковисто-матовая 9л", **PACK)
    assert "decorative" not in ContextRanker().score([satin], room())[0].parts
    panel = item(6, "decorative", name="панель декоративная МДФ", **PACK)
    assert "decorative" not in ContextRanker().score([panel], room())[0].parts


def test_phone_and_tv_sockets_are_not_typical():
    from app.ml.ranker import _typical
    from app.taxonomy import Material

    assert not _typical(Material.socket, "розетка 1 пост телефонная 1xRJ11 ONEKEYELECTRO")
    assert not _typical(Material.socket, "розетка TV оконечная")
    assert _typical(Material.socket, "розетка 1 пост BYLECTRICA 16А IP44 с/з белый")
    assert _typical(Material.socket, "розетка с USB и заземлением")


def test_profile_cache_follows_binding_changes():
    p, b = item(1, chars={"Влагостойкость краски": "да"}, **PACK)
    assert signals(p, b)["moisture_resistant"] == 1
    b.material = "tile"
    assert signals(p, b)["moisture_resistant"] == 1 and ContextRanker().score([(p, b)], room())[0].product is p


def test_profile_cache_refreshes_after_catalog_reload():
    p, b = item(1, name="Краска интерьерная", **PACK)
    p.last_seen_run = 1
    assert signals(p, b)["moisture_resistant"] == 0
    p.raw = {"characteristics": [{"name": "Влагостойкость краски", "value": "да"}]}
    p.last_seen_run = 2
    assert signals(p, b)["moisture_resistant"] == 1


def test_roofing_screws_are_not_typical_fasteners():
    from app.ml.ranker import _typical
    from app.taxonomy import Material

    assert not _typical(Material.fasteners, "саморез кровельный св. 4,8х35мм 5 кг синий")
    assert _typical(Material.fasteners, "саморез по гипсокартону 3,5х25 мм 200 шт")
    assert _typical(Material.fasteners, "дюбель-хомут для кабеля 5-10 мм")
