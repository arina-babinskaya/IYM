"""Deterministic source-category mapping. Source fields are provenance, never features."""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from .catalog_parser import source_category, clean_text
from ..taxonomy.catalog_taxonomy import CATEGORY_BY_ID

# V2 mappings reviewed against real source-category examples. IDs take precedence over
# names because duplicate/near-duplicate source names can have different meanings.
EXACT_SOURCE_ID: dict[str, str] = {
 "2227":"furniture.kitchen", "1966":"hardware.furniture", "4127":"electrical.switch_socket",
 "4140":"lighting.indoor", "2767":"lighting.indoor", "3971":"apparel.clothing_footwear",
 "1047":"finishing.coatings", "4138":"electrical.protection", "3864":"apparel.clothing_footwear",
 "2221":"furniture.kitchen", "1989":"hardware.metal", "4016":"finishing.painting_tools",
 "2220":"furniture.kitchen", "1426":"furniture.components", "983":"finishing.paint",
 "2612":"electrical.components", "2583":"electrical.switch_socket", "4106":"finishing.decor",
 "924":"doors_windows.hardware", "1691":"tools.accessories", "4006":"home.textiles",
 "1016":"finishing.painting_tools", "1913":"hardware.furniture", "2726":"electrical.power",
 "4181":"kitchen.appliances", "4008":"finishing.decor", "4100":"home.decor",
 "1039":"finishing.painting_tools", "3775":"stationery.office_school", "1915":"hardware.fasteners",
 "4020":"furniture.bathroom", "3280":"personal_care.hygiene", "3219":"personal_care.hygiene",
 "4105":"kitchen.utensils", "2031":"hardware.metal", "2949":"home.textiles",
 "1028":"finishing.painting_tools", "3194":"home.decor", "1592":"tools.power",
 "2947":"home.textiles", "2783":"lighting.indoor", "2733":"lighting.decorative",
 "4055":"plumbing.accessories", "2549":"kitchen.utensils", "2226":"furniture.kitchen",
 "2544":"kitchen.utensils", "2948":"home.textiles", "3879":"seasonal.holiday",
 "4004":"home.textiles", "2269":"furniture.kitchen", "4056":"plumbing.accessories",
 "4037":"plumbing.pipes_fittings", "931":"doors_windows.hardware", "858":"finishing.decor",
 "632":"garden.fertilizers", "793":"finishing.decor", "4076":"tools.accessories",
 "2953":"home.textiles", "4147":"lighting.bulbs", "4045":"plumbing.pipes_fittings",
 "3873":"stationery.office_school", "2117":"furniture.home", "1017":"finishing.painting_tools",
 "1006":"finishing.painting_tools", "929":"doors_windows.hardware", "4194":"kitchen.appliances",
 "4054":"plumbing.accessories", "3206":"personal_care.hygiene", "860":"finishing.decor",
 "4102":"plumbing.sinks", "935":"doors_windows.hardware", "1308":"plumbing.accessories",
 "2393":"kitchen.tableware", "2843":"lighting.indoor", "359":"lighting.outdoor",
 "4178":"personal_care.hygiene", "2001":"hardware.metal", "3213":"personal_care.hygiene",
 "1916":"hardware.fasteners", "4174":"personal_care.hygiene", "2087":"furniture.components",
 "568":"garden.accessories", "912":"hardware.furniture", "2502":"kitchen.tableware",
 "2102":"home.storage", "3881":"seasonal.holiday", "4042":"plumbing.accessories",
 "1066":"plumbing.bath_shower", "1975":"hardware.furniture", "2200":"home.decor",
 "3963":"garden.machinery", "2617":"electrical.components", "684":"tile.floor_porcelain",
 "3880":"seasonal.holiday", "2153":"furniture.home", "3999":"home.decor",
 "4119":"kitchen.tableware", "4002":"home.textiles", "4043":"plumbing.pipes_fittings",
 "2632":"electrical.components", "2966":"home.textiles", "3484":"kitchen.appliances",
 "1598":"tools.power", "2973":"kitchen.tableware", "1180":"plumbing.water_treatment",
 "1423":"furniture.components", "1696":"tools.accessories", "1518":"heating.radiators",
 "1909":"hardware.fasteners", "868":"finishing.decor", "3215":"personal_care.hygiene",
 "4039":"plumbing.pipes_fittings", "3862":"apparel.clothing_footwear", "1050":"finishing.coatings",
 "574":"garden.accessories", "1515":"heating.radiators", "1062":"plumbing.bath_shower",
 "1526":"heating.ventilation", "3081":"home.rugs", "1045":"finishing.paint",
 "693":"tile.installation", "921":"doors_windows.hardware", "1029":"tools.accessories",
 "1325":"plumbing.accessories", "1819":"tools.hand", "2274":"furniture.kitchen",
 "4207":"electrical.components", "692":"tile.installation", "1550":"tools.accessories",
 "4210":"seasonal.holiday", "3709":"auto.accessories", "3202":"personal_care.hygiene",
 "4175":"personal_care.hygiene", "2951":"home.textiles", "990":"building.insulation",
 "2613":"electrical.components", "2158":"furniture.home", "3868":"apparel.clothing_footwear",
 "4180":"personal_care.hygiene", "3764":"stationery.office_school", "2577":"electrical.switch_socket",
 "1967":"hardware.furniture", "936":"doors_windows.hardware", "1175":"plumbing.water_treatment",
 "1993":"hardware.metal", "3181":"apparel.clothing_footwear", "941":"doors_windows.hardware",
 "2913":"lighting.indoor", "2630":"electrical.components", "1918":"hardware.fasteners",
 "3617":"auto.accessories", "4137":"electrical.protection", "2623":"electrical.components",
 "4148":"lighting.bulbs", "937":"doors_windows.hardware", "2140":"furniture.home",
 "4168":"apparel.clothing_footwear", "1036":"finishing.painting_tools", "2610":"electrical.components",
 "294":"garden.machinery", "3475":"kitchen.appliances", "4110":"kitchen.cookware",
 "3109":"cleaning.chemicals", "771":"flooring.accessories", "4183":"kitchen.appliances",
 "3476":"kitchen.appliances", "2402":"kitchen.tableware", "1965":"hardware.furniture",
 "3281":"personal_care.hygiene", "2216":"furniture.kitchen", "2374":"kitchen.utensils",
 "3436":"kitchen.appliances", "753":"home.rugs", "4156":"cleaning.equipment",
 "4161":"cleaning.equipment", "3191":"home.decor", "4197":"kitchen.appliances",
 "4090":"furniture.home", "3114":"cleaning.chemicals", "3419":"kitchen.appliances",
 "1342":"heating.radiators", "3477":"kitchen.appliances", "859":"finishing.decor",
 "1678":"tools.accessories", "1253":"plumbing.pipes_fittings", "2041":"hardware.metal",
 "3447":"cleaning.equipment", "2501":"kitchen.tableware", "631":"garden.fertilizers",
 "2004":"hardware.metal", "4091":"furniture.home", "3487":"kitchen.appliances",
 "2011":"hardware.fasteners", "2406":"kitchen.tableware", "3985":"garden.accessories",
 "1848":"tools.hand", "2962":"home.textiles", "3975":"home.household",
 "1917":"hardware.fasteners", "3087":"cleaning.chemicals", "2069":"furniture.home",
 "2827":"lighting.indoor", "327":"garden.watering", "2961":"home.textiles",
 "3121":"cleaning.chemicals", "4159":"cleaning.equipment", "4189":"heating.radiators",
 "4157":"cleaning.equipment", "4101":"furniture.bathroom", "637":"garden.fertilizers",
 "499":"outdoor.grill", "2424":"kitchen.tableware", "4073":"finishing.painting_tools",
 "3689":"auto.accessories", "2405":"kitchen.tableware", "1988":"hardware.metal",
 "3190":"home.decor", "3072":"home.decor", "1583":"tools.power", "949":"home.household",
 "1987":"hardware.metal", "1280":"plumbing.bath_shower", "3981":"outdoor.leisure",
 "1067":"plumbing.bath_shower", "3166":"personal_care.hygiene", "1914":"hardware.fasteners",
 "1732":"tools.accessories", "2054":"home.household", "1779":"tools.hand",
 "3115":"cleaning.chemicals", "621":"garden.pots", "4187":"kitchen.appliances",
 "352":"lighting.decorative", "2935":"lighting.indoor", "1708":"tools.accessories",
 "1687":"tools.accessories", "1782":"tools.hand", "4192":"kitchen.appliances",
 "2970":"kitchen.utensils", "4058":"plumbing.accessories", "2456":"kitchen.tableware",
 "1429":"furniture.components", "3372":"kitchen.appliances", "961":"doors_windows.windows",
 "3752":"stationery.office_school", "4118":"kitchen.tableware", "3867":"apparel.clothing_footwear",
 "2082":"furniture.home", "2931":"lighting.indoor", "3193":"home.decor",
 "3991":"personal_care.hygiene", "626":"garden.accessories", "2624":"electrical.components",
 "4115":"kitchen.tableware", "4176":"personal_care.hygiene", "4075":"tools.power",
 "3729":"stationery.office_school", "1041":"finishing.coatings", "490":"outdoor.leisure",
 "3915":"stationery.office_school", "493":"outdoor.leisure", "2852":"lighting.indoor",
 "776":"flooring.accessories", "3002":"cleaning.equipment", "1433":"doors_windows.hardware",
 "2553":"kitchen.utensils", "1840":"tools.hand", "4169":"garden.fertilizers",
 "3728":"stationery.office_school", "2711":"electrical.components", "312":"garden.machinery",
 "3610":"auto.accessories", "2000":"hardware.metal", "1719":"tools.accessories",
 "3683":"auto.accessories", "2543":"kitchen.utensils", "2855":"lighting.indoor",
 "2860":"lighting.indoor", "2441":"kitchen.tableware", "4177":"personal_care.hygiene",
 "2005":"hardware.metal", "3970":"garden.tools", "1031":"tools.accessories",
 "4038":"plumbing.pipes_fittings", "889":"plumbing.bath_shower", "1688":"tools.accessories",
 "1427":"furniture.components", "3442":"cleaning.equipment", "1174":"plumbing.water_treatment",
 "3768":"stationery.office_school", "4005":"home.textiles", "2010":"hardware.fasteners",
 "3058":"home.storage", "1714":"tools.accessories", "348":"garden.accessories",
 "2361":"kitchen.utensils", "1438":"finishing.adhesive_sealant", "1309":"plumbing.accessories",
 "602":"garden.fertilizers", "3309":"personal_care.hygiene", "1244":"plumbing.pipes_fittings",
 "4152":"lighting.bulbs", "3801":"stationery.office_school", "2045":"home.storage",
 "441":"garden.tools", "914":"doors_windows.hardware", "3222":"personal_care.hygiene",
 "1844":"tools.hand", "2638":"electrical.components", "1015":"finishing.painting_tools",
 "2950":"home.textiles", "681":"tile.wall", "455":"apparel.clothing_footwear",
 "3129":"cleaning.chemicals", "4120":"kitchen.utensils", "2637":"electrical.components",
 "4170":"garden.fertilizers", "2199":"home.decor", "3712":"auto.accessories",
 "4069":"building.insulation", "4186":"kitchen.appliances", "3972":"apparel.clothing_footwear",
 "2934":"lighting.indoor", "450":"apparel.clothing_footwear", "3921":"outdoor.leisure",
 "4188":"heating.ventilation", "2049":"home.storage", "3708":"auto.accessories",
 "4085":"tools.hand", "3208":"personal_care.hygiene", "2468":"kitchen.tableware",
 "1465":"building.roofing", "4096":"home.rugs", "1157":"plumbing.faucets",
 "1846":"tools.hand", "3807":"stationery.office_school", "2848":"lighting.decorative",
 "3232":"personal_care.hygiene", "289":"garden.machinery", "862":"finishing.decor",
 "3874":"stationery.office_school", "1509":"building.roofing", "864":"finishing.decor",
 "2378":"kitchen.utensils", "3485":"kitchen.appliances", "1008":"finishing.painting_tools",
 "3090":"cleaning.chemicals"
}

# Ordered from specific to broad. Rules intentionally operate on source category text.
RULES: tuple[tuple[str, str, str], ...] = (
 ("personal_care.hygiene", r"шампун|гель для душ|зубн|дезодоран|гигиен|космет|мыл[оа]|брить|уход.*(лиц|тел|волос)|прокладк.*гигиен|тампон", "source.personal_care"),
 ("apparel.clothing_footwear", r"обув|носк|колгот|тапк|халат|одежд|зонт|дождевик", "source.apparel"),
 ("stationery.office_school", r"тетрад|канцеляр|карандаш|ручки? (?:шар|гел)|бумаг|картон|папк|ластик|линейк|книг|открытк", "source.stationery"),
 ("finishing.painting_tools", r"кист[ьи].*маляр|валик|шпател|ленты? маляр|малярн.*инструмент|растворител|колеровочн.*паст", "source.finishing.painting_tools"),
 ("electrical.components", r"клемм|патрон.*ламп|коробк.*(?:монтаж|распредел)|изолент|термоусад|наконечник.*гильз|электр.*разъем", "source.electrical.components"),
 ("plumbing.water_treatment", r"фильтр.*вод|картридж.*фильтр|сменн.*модул", "source.plumbing.water_treatment"),
 ("garden.accessories", r"опор.*раст|подставк.*цвет|садов.*фигур|укрывн.*материал|декор.*сад", "source.garden.accessories"),
 ("garden.seeds", r"семен|лукович|посадочн.*материал|рассад", "source.garden.seeds"),
 ("garden.plants", r"сажен|^растени|^цветы живые|^деревья|^кустарник", "source.garden.plants"),
 ("garden.soils", r"грунт(?!ов)|субстрат|торф|дренаж.*раст", "source.garden.soils"),
 ("garden.fertilizers", r"удобрени|защит.*раст|гербицид|инсектицид|фунгицид", "source.garden.fertilizers"),
 ("garden.pots", r"кашпо|горшк|вазон|ящик.*цвет|поддон.*горш", "source.garden.pots"),
 ("garden.watering", r"полив|лейк|шланг|дождеват|опрыскиват", "source.garden.watering"),
 ("garden.machinery", r"газонокос|триммер|мотоблок|культиватор|снегоубор|садов.*тех", "source.garden.machinery"),
 ("garden.tools", r"садов.*инструмент|секатор|лопат|грабл|тяпк|вилы", "source.garden.tools"),
 ("lighting.decorative", r"гирлянд|светодиодн.*лент|декоративн.*свет|неон", "source.lighting.decorative"),
 ("lighting.outdoor", r"светильник.*(улич|садов|фасад|грунт)|фонари садов|уличное освещ", "source.lighting.outdoor"),
 ("lighting.bulbs", r"ламп[ыа] (светодиод|галоген|накал|люмин)|лампочки", "source.lighting.bulbs"),
 ("lighting.work", r"фонар[иь]|прожектор|переносн.*свет", "source.lighting.work"),
 ("lighting.indoor", r"люстр|бра\b|светильник|спот|лампы настоль|торшер", "source.lighting.indoor"),
 ("tile.installation", r"затирк|клей.*плит|систем.*выравнив.*плит|уголки.*плит|профил.*плит", "source.tile.installation"),
 ("tile.mosaic", r"мозаик", "source.tile.mosaic"),
 ("tile.floor_porcelain", r"керамогранит|плитка наполь", "source.tile.floor"),
 ("tile.wall", r"плитка настен|кафель", "source.tile.wall"),
 ("flooring.laminate", r"ламинат", "source.flooring.laminate"),
 ("flooring.linoleum", r"линолеум", "source.flooring.linoleum"),
 ("flooring.vinyl", r"spc|плитка пвх|кварц.?винил|винилов.*пол", "source.flooring.vinyl"),
 ("flooring.wood", r"паркет|инженерн.*доск|массивн.*доск", "source.flooring.wood"),
 ("flooring.carpet", r"ковролин|ковровая плитка", "source.flooring.carpet"),
 ("flooring.accessories", r"плинтус|подложк|порог.*пол|комплектующие.*плинт", "source.flooring.accessories"),
 ("finishing.primer", r"грунтовк|грунт.*строит", "source.finishing.primer"),
 ("finishing.putty_plaster", r"шпатл|шпакл|штукатур", "source.finishing.putty"),
 ("finishing.paint", r"краск|эмал[ьи]", "source.finishing.paint"),
 ("finishing.coatings", r"лак\b|лаки|масл.*дерев|антисептик|пропитк|морилк", "source.finishing.coatings"),
 ("finishing.wallpaper", r"обои", "source.finishing.wallpaper"),
 ("finishing.adhesive_sealant", r"герметик|клей|монтажн.*пен", "source.finishing.adhesive"),
 ("finishing.decor", r"молдинг|лепнин|декоративн.*панел|потолочн.*плинт", "source.finishing.decor"),
 ("building.sheet_materials", r"гипсокарт|гкл|фанер|osb|осп\b|дсп|двп|цсп", "source.building.sheet"),
 ("building.insulation", r"утеплител|теплоизоля|звукоизоля|гидроизоля|пароизоля|мембран", "source.building.insulation"),
 ("building.roofing", r"кровл|водосток|черепиц|ондулин", "source.building.roofing"),
 ("building.facade", r"фасад|сайдинг", "source.building.facade"),
 ("building.masonry", r"кирпич|газобет|пеноблок|строительн.*блок", "source.building.masonry"),
 ("building.dry_mix", r"сух.*смес|цемент|пескобет|кладочн.*смес|наливн.*пол", "source.building.mix"),
 ("building.lumber", r"пиломатериал|брус|доск|рейк|вагонк", "source.building.lumber"),
 ("doors_windows.hardware", r"дверн.*руч|замк|петл|доводчик|фурнитур.*окон|комплектующие.*двер", "source.doors.hardware"),
 ("doors_windows.doors", r"двер[ьи]|дверное полотно", "source.doors.doors"),
 ("doors_windows.windows", r"окн[ао]|подоконник|москитн", "source.doors.windows"),
 ("electrical.switch_socket", r"розет|выключател|рамки.*розет", "source.electrical.switch"),
 ("electrical.protection", r"автомат.*защит|узо\b|электрощ|счетчик.*элект|контактор", "source.electrical.protection"),
 ("electrical.cable", r"кабел|провод|кабель.?канал|гофр.*каб", "source.electrical.cable"),
 ("electrical.power", r"удлинител|сетев.*фильтр|батарейк|аккумулятор|вилки электр", "source.electrical.power"),
 ("electrical.smart_security", r"видеонаблю|сигнализац|умный дом|датчик.*движ|звонок", "source.electrical.security"),
 ("plumbing.faucets", r"смесител", "source.plumbing.faucets"),
 ("plumbing.sanitary", r"унитаз|раковин|умывальник|биде|инсталляц", "source.plumbing.sanitary"),
 ("plumbing.bath_shower", r"ванн[аы]|душев|поддон", "source.plumbing.shower"),
 ("plumbing.sinks", r"мойк[аи].*(кухон|искус)|кухонн.*мойк", "source.plumbing.sinks"),
 ("plumbing.pipes_fittings", r"фитинг|труб[аы]|кран шар|запорн.*армат", "source.plumbing.pipes"),
 ("plumbing.accessories", r"аксессуар.*ванн|держател.*полотен|ершик|мыльниц", "source.plumbing.accessories"),
 ("heating.ventilation", r"вентиля|вентилятор|воздуховод", "source.heating.ventilation"),
 ("heating.boilers", r"кот[её]л|водонагрев|бойлер", "source.heating.boilers"),
 ("heating.radiators", r"радиатор|конвектор|тепл.*пол|отоплен", "source.heating.radiators"),
 ("tools.accessories", r"св[её]рл|коронк|диск.*(рез|пил|шлиф)|бит[ыа]|оснастк", "source.tools.accessories"),
 ("tools.power", r"дрел|шуруповерт|перфоратор|болгарк|электроинструмент|лобзик|шлифмаш", "source.tools.power"),
 ("tools.workwear", r"спецодеж|рабоч.*обув|перчатк|защитн.*очк|респиратор|каск", "source.tools.workwear"),
 ("tools.hand", r"инструмент|отвертк|молот|пил[ыа]|ключ[и ]|рулетк|уровн", "source.tools.hand"),
 ("hardware.fasteners", r"саморез|шуруп|дюбел|болт|гайк|винт|шайб|гвозд|анкер", "source.hardware.fasteners"),
 ("hardware.furniture", r"мебельн.*(руч|фурнит|направ|опор|пет)|комплектующие.*мебел", "source.hardware.furniture"),
 ("hardware.metal", r"уголки креп|металлопрокат|профил.*металл|сетк.*металл", "source.hardware.metal"),
 ("outdoor.grill", r"мангал|грил|коптиль|щепа.*копчен|шампур", "source.outdoor.grill"),
 ("outdoor.furniture", r"садов.*мебел|качел|гамак|шезлонг", "source.outdoor.furniture"),
 ("outdoor.leisure", r"бассейн|туризм|кемпинг|пикник|палатк|спорт", "source.outdoor.leisure"),
 ("outdoor.structures", r"теплиц|парник|навес|огражден|забор", "source.outdoor.structures"),
 ("home.rugs", r"ковр[ыа]|коврик придвер", "source.home.rugs"),
 ("home.textiles", r"штор|полотен|простын|подуш|одеял|постельн|текстиль", "source.home.textiles"),
 ("home.storage", r"хранени|органайзер|контейнер|корзин|вешалк", "source.home.storage"),
 ("home.decor", r"декор|фоторам|картин|вазы|свечи|зеркал", "source.home.decor"),
 ("cleaning.chemicals", r"средств.*(стир|мыть|чист)|бытов.*хим|порошок стираль", "source.cleaning.chemicals"),
 ("cleaning.equipment", r"швабр|щетк.*уборк|губк|инвентарь.*уборк", "source.cleaning.equipment"),
 ("kitchen.tableware", r"тарелк|кружк|чашк|салатник|бокал|стакан|столов.*прибор", "source.kitchen.tableware"),
 ("kitchen.cookware", r"сковород|кастрюл|сотейник|форм.*выпеч|казан", "source.kitchen.cookware"),
 ("kitchen.utensils", r"кухонн.*принад|ножи|нож кух|разделочн.*доск|терк|половник", "source.kitchen.utensils"),
 ("kitchen.appliances", r"бытов.*тех|чайник электр|микровол|холодиль|пылесос", "source.kitchen.appliances"),
 ("furniture.kitchen", r"кухонн.*(тумб|шкаф|мебел)|фасады.*мдф|столешниц", "source.furniture.kitchen"),
 ("furniture.bathroom", r"мебель.*ванн|тумб.*раков|шкаф.*ванн", "source.furniture.bathroom"),
 ("furniture.home", r"шкаф|стол[ы ]|стул|кресл|кровать|комод|полк[аи]|мебель", "source.furniture.home"),
 ("auto.accessories", r"авто|автомоб", "source.auto"),
 ("pets.supplies", r"животн|кош|собак|зоотовар|аквари", "source.pets"),
 ("seasonal.holiday", r"новогод|рождеств|празднич|ёлк|елочн", "source.seasonal"),
 ("home.household", r"хозяйствен|бытов.*товар|лестниц|стремянк", "source.home.household"),
)
_COMPILED = tuple((cid, re.compile(pattern, re.I), rid) for cid, pattern, rid in RULES)

@dataclass(frozen=True)
class LabelResult:
    target_category_id: str
    target_category_name: str
    mapping_status: str
    label_confidence: str
    labeling_rule_id: str
    candidate_category_ids: str = ""
    review_reason: str = ""
    supervised_eligible: bool = True
    mapping_method: str = "source_name_rule"
    mapping_evidence: str = ""

PRODUCT_RULES = (
 ("garden.tools", re.compile(r"\b(?:кусторез|ножниц\w*\s+(?:для\s+)?(?:живой изгороди|кустарник))", re.I), "product.hedge_shears"),
 ("garden.accessories", re.compile(r"\b(?:подставка|стойка)\s+(?:для\s+)?(?:цветов|растений)\b", re.I), "product.flower_stand"),
 ("furniture.kitchen", re.compile(r"\bстолешниц\w*", re.I), "product.kitchen_countertop"),
 ("finishing.decor", re.compile(r"(?:панел\w*\s+кухон|кухон\w*\s+панел)", re.I), "product.kitchen_wall_panel"),
)

def label_product(product: dict) -> LabelResult:
    source_id, source = source_category(product)
    # Overrides require an explicit phrase in the product name. Descriptions are deliberately
    # excluded here: incidental phrases such as "стойкость цвета" caused false positives.
    evidence = clean_text(product.get("name"))
    for cid, rx, rid in PRODUCT_RULES:
        match = rx.search(evidence)
        if match:
            cat=CATEGORY_BY_ID[cid]
            return LabelResult(cid,cat.name,"confident","high",rid,supervised_eligible=True,mapping_method="product_override",mapping_evidence=match.group(0)[:160])
    if source_id in EXACT_SOURCE_ID:
        cid=EXACT_SOURCE_ID[source_id]; cat=CATEGORY_BY_ID[cid]
        return LabelResult(cid,cat.name,"confident","high",f"source_id.{source_id}",supervised_eligible=True,mapping_method="exact_source_id",mapping_evidence=source)
    matches = [(cid, rid) for cid, rx, rid in _COMPILED if rx.search(source)]
    # Broad rules for newly introduced families fill genuine gaps but never overrule a
    # pre-existing specialist rule. Exact IDs and product overrides above remain stronger.
    new_family_rules={"source.personal_care","source.apparel","source.stationery","source.finishing.painting_tools","source.electrical.components","source.plumbing.water_treatment","source.garden.accessories"}
    if any(rid not in new_family_rules for _,rid in matches):
        matches=[x for x in matches if x[1] not in new_family_rules]
    unique = list(dict.fromkeys(cid for cid, _ in matches))
    if not source:
        return _review("missing_source_category")
    if not unique:
        return _review("unmapped_source_category")
    # Ordered priority resolves overlap; multiple families are retained for audit and excluded.
    if len(unique) > 1 and len({x.split('.')[0] for x in unique}) > 1:
        return _review("conflicting_source_rules", unique)
    cid, rid = matches[0]
    cat = CATEGORY_BY_ID[cid]
    return LabelResult(cid, cat.name, "confident", "high", rid, supervised_eligible=True, mapping_method="source_name_rule", mapping_evidence=source)

def _review(reason: str, candidates: list[str] | None = None) -> LabelResult:
    cat = CATEGORY_BY_ID["review.unresolved"]
    return LabelResult(cat.id, cat.name, "ambiguous" if candidates else "unmapped", "low", "fallback.review", "|".join(candidates or []), reason, False, "review", reason)

def label_dict(product: dict) -> dict:
    return asdict(label_product(product))

def feature_text(row: dict, mode: str = "name") -> str:
    """Leakage-safe features: only pre-category text is accepted."""
    if mode == "name": return clean_text(row.get("name"))
    if mode == "name_description":
        return " ".join(filter(None, [clean_text(row.get("name")), clean_text(row.get("description")), clean_text(row.get("marketing_description")), clean_text(row.get("characteristics_text"))]))
    raise ValueError("mode must be name or name_description")
