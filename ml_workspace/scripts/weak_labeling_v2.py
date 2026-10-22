"""Расширение проверенных v1-правил для taxonomy_v2."""
from __future__ import annotations
import json,re
from typing import Any
import pandas as pd
from ml_workspace.scripts.weak_labeling_v1 import label_product as label_v1
from ml_workspace.taxonomy.taxonomy_v2 import TAXONOMY_VERSION,WORK_ROLE_MAP,stages_for_work_types

def norm(v:Any)->str: return re.sub(r"\s+"," ",str(v or "").lower().replace("ё","е")).strip()
def match(patterns:tuple[str,...],text:str)->list[str]:
 return [m.group(0) for p in patterns if (m:=re.search(p,text,re.I))]

ENGINEERING_RULES=(
 ("electrical_wiring","electrical_goods",(r"кабель электрический",r"кабельные каналы",r"углы для кабель-каналов",r"коробки распределительные",r"скобы для крепления кабеля",r"арматура для монтажа сип",r"клеммы, зажимы",r"инструмент электромонтажный",r"клещи для электропроводки"),(r"телефон|интернет|акустическ|телевизион|автомобил|готовый со штекером",)),
 ("plumbing_rough","plumbing",(r"^трубы$",r"^фитинги$",r"арматура для трубопроводов",r"канализац",r"клипсы для труб",r"соединители для труб",r"изоляция для труб",r"монтажа канализационных"),(r"полив|садов|хранения джокер|трубочки.*коктейл|домофон|гофрированн.*кабел",)),
 ("ventilation_install","ventilation",(r"вентиляторы вытяжные",r"вентиляционные (?:соединители|решетки|фланцы|анемостаты)",r"^воздуховоды$",r"хомуты для воздуховодов",r"крепеж для вентиляционных"),(r"автомобил",)),
 ("heating_climate_install","heating_climate",(r"радиаторы (?:секционные|панельные|трубчатые)",r"комплектующие для радиаторов",r"теплый пол",r"терморегуляторы для теплых",r"трубы для теплых полов",r"комплектующие для котлов",r"котлы отопления",r"баки расширительные",r"коллекторные группы"),()),
)
TOOL_RULES=(
 ("hand_tools",(r"ножи строительные",r"^ножовки$",r"шпатели",r"молотки",r"отвертки",r"плоскогубцы",r"ключи гаечные",r"рулетки"),()),
 ("power_tools",(r"дрели",r"шуруповерты",r"перфораторы",r"лобзики",r"шлифовальные машины",r"пилы (?:дисковые|торцовочные|сабельные)"),()),
 ("tool_accessories",(r"^биты$",r"^буры$",r"^коронки$",r"наборы сверл",r"пилки для лобзиков",r"полотна (?:для дисковых пил|к ножовкам)",r"диски отрезные",r"насадки для сверления",r"шаблоны для сверления"),(r"садов|мотобур|ледоруб",)),
 ("consumables",(r"бруски абразивные",r"шлифовальная (?:бумага|сетка)",r"ленты малярные",r"мешки для строительного мусора"),(r"губки.*мочалки",)),
 ("protective_equipment",(r"респираторы, защитные маски",r"каски, шлемы, щитки защитные",r"очки защитные"),(r"садов",)),
)
FURNISHING_RULES=(
 ("tables",(r"столы для столовой",r"столы журнальные",r"столы письменные",r"столы компьютерные")),
 ("seating",(r"стулья для столовой",r"^кресла$",r"кресла офисные",r"^диваны$",r"табуреты")),
 ("shelving_storage",(r"^стеллажи$",r"полки (?:настенные|мебельные)",r"обувницы",r"вешалки")),
 ("cabinets_wardrobes",(r"шкафы распашные",r"шкафы-купе",r"кухонные тумбы",r"навесные шкафы",r"каркасы для .*шкаф",r"каркасы для кухонных тумб",r"комоды",r"тумбы прикроватные",r"тумбы в ванную",r"шкафы для ванной",r"фасады - мдф")),
 ("beds",(r"кровати",r"кровати для спальни")),
 ("countertops",(r"столешницы",r"планки для столешниц",r"кромочная лента для столешниц",r"плинтусы.*столешниц")),
 ("mirrors",(r"^зеркала$",r"зеркала в ванную")),
 ("interior_accessories",(r"рейлинговые системы",r"мебельные ручки",r"мебельные крючки",r"ножки мебельные")),
 ("decorative_objects",(r"^репродукции$",r"фоторамки",r"настенный декор")),
)
MOUNTED_DECOR=(r"консоли декоративные",r"стеновые панели",r"декоративные стеновые панели",r"молдинги",r"^карнизы$",r"комплектующие к панелям",r"профили для стеновых панелей")
ROOM_RULES=(
 ("kitchen",(r"кухн",r"столешниц")),("dining_room",(r"столов",r"обеденн")),("living_room",(r"гостин",r"диван|журнальн")),
 ("bedroom",(r"спальн|кроват|прикроват",)),("bathroom",(r"ванн|сануз|туалет",)),("hallway",(r"прихож|обувниц",)),
 ("home_office",(r"офисн|письменн|компьютерн",)),("utility_room",(r"кладов|хоз.*помещ",)),("balcony",(r"балкон|лоджи",)),
)

def label_product(row:pd.Series|dict[str,Any])->dict[str,Any]:
 base=label_v1(row); category=norm(row.get("source_category","")); source_text=norm(" ".join(str(row.get(x,"")) for x in ("name","description_clean","marketing_description_clean","important_attributes_json","characteristics_json")))
 evidence=list(base["label_evidence"]); works=list(base["work_types"]); product=base["product_category"]
 if product=="tools": product="hand_tools"
 activities=["renovation"] if base["domain_label"]=="renovation" else []
 domain=base["domain_label"]
 for work,cat,positive,negative in ENGINEERING_RULES:
  hits=match(positive,category); neg=match(negative,f"{category} {source_text}")
  if hits and not neg:
   if work not in works: works.append(work)
   product=cat; domain="renovation"; activities=["renovation"]
   evidence.append({"rule_id":f"v2:engineering:{work}","dimension":"work_type","label":work,"source":"source_category","matches":hits,"score":1.0})
 for cat,positive,negative in TOOL_RULES:
  hits=match(positive,category); neg=match(negative,f"{category} {source_text}")
  if hits and not neg:
   product=cat; domain="renovation"; activities=["renovation"]
   if cat=="tool_accessories" and "абразив" in category: works=[w for w in works if w!="lighting_install"]
   evidence.append({"rule_id":f"v2:tool:{cat}","dimension":"product_category","label":cat,"source":"source_category","matches":hits,"score":1.0})
 decor_hits=match(MOUNTED_DECOR,category)
 if decor_hits:
  product="decorative_materials" if "панел" not in category else "decorative_panels"; domain="renovation"; activities=["renovation"]
  if "decorative_finish_install" not in works: works.append("decorative_finish_install")
  evidence.append({"rule_id":"v2:mounted_decor","dimension":"work_type","label":"decorative_finish_install","source":"source_category","matches":decor_hits,"score":1.0})
 furnishing=None
 for cat,patterns in FURNISHING_RULES:
  if hits:=match(patterns,category): furnishing=(cat,hits); break
 if furnishing and not works:
  product,hits=furnishing; domain="furnishing"; activities=["room_furnishing"]
 evidence.append({"rule_id":f"v2:furnishing:{product}","dimension":"activity","label":"room_furnishing","source":"source_category","matches":hits,"score":1.0})
 if category in {"стаканы","бокалы","кружки","тарелки","салатники, миски"} and not works:
  domain="non_renovation"; activities=[]; product=""
  evidence.append({"rule_id":"v2:non_renovation:tableware","dimension":"domain","label":"non_renovation","source":"source_category","matches":[category],"score":1.0})
 rooms=[]
 if "room_furnishing" in activities:
  for room,patterns in ROOM_RULES:
   if match(patterns,f"{category} {source_text}"): rooms.append(room)
  if not rooms and product in {"mirrors","decorative_objects","interior_accessories","shelving_storage"}: rooms=["general_indoor"]
 works=list(dict.fromkeys(works)) if domain=="renovation" else []
 stages=stages_for_work_types(works) if works else []
 confidence=max([float(x.get("score",0)) for x in evidence]+[0.0])
 known=domain!="unknown_needs_review"
 return {"domain_label":domain,"activities":activities,"product_category":product if known else "","work_types":works,"renovation_stages":stages,"room_types":rooms,
  "material_roles":[{"work_type_id":w,"roles":WORK_ROLE_MAP[w]} for w in works],"label_confidence":round(confidence,3),"label_evidence":evidence,"label_conflicts":base["label_conflicts"],
  "domain_status":"known" if known else "unknown","activity_status":"known" if known else "unknown","product_category_status":"known" if known and product else "unknown",
  "work_types_status":"known" if known else "unknown","room_types_status":"known" if domain!="furnishing" or rooms else "unknown","label_status":"auto_labeled" if known else base["label_status"],"labeling_method":"deterministic_rules_taxonomy_v2","taxonomy_version":TAXONOMY_VERSION}

def serialize_labels(result:dict[str,Any])->dict[str,Any]:
 return {k:json.dumps(v,ensure_ascii=False,sort_keys=True) if isinstance(v,(list,dict)) else v for k,v in result.items()}
