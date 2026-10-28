import asyncio, json, ssl, time
from pathlib import Path
import httpx, pytest
from app.config import Settings
from app.llm.gigachat import GigaChatClient, GigaChatError, GigaClassification
from app.ml.hybrid import decide_hybrid, eligible_for_gigachat
from app.models import Product
from app.schemas import Suggestion
from app.taxonomy import Material, ProductCategory, WorkType

def response(body, usage=None):
    return httpx.Response(200, json={"choices":[{"message":{"content":body if isinstance(body,str) else json.dumps(body)}}], **({"usage":usage} if usage is not None else {})})

def client(tmp_path, replies, **overrides):
    calls=[]
    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/oauth"):
            return httpx.Response(200,json={"access_token":"token","expires_at":int((time.time()+1000)*1000)})
        item=replies.pop(0); return item(request) if callable(item) else item
    options={"gigachat_retries":0,**overrides}
    settings=Settings(gigachat_enabled=True,gigachat_credentials="secret",gigachat_cache_path=tmp_path/"giga.sqlite",**options)
    return GigaChatClient(settings,httpx.MockTransport(handler)),calls

def product(): return Product(id=1,name="Светильник",categories={"1":"Освещение"})

def test_public_model_discovery_uses_oauth_and_configured_tls(tmp_path, monkeypatch):
    calls=[]
    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/oauth"):
            return httpx.Response(200,json={"access_token":"token","expires_at":int((time.time()+1000)*1000)})
        assert request.url.path.endswith("/models")
        assert request.headers["Authorization"]=="Bearer token"
        return httpx.Response(200,json={"data":[{"id":"GigaChat-Pro"},{"id":"GigaChat-2"}]})
    settings=Settings(gigachat_enabled=True,gigachat_credentials="secret",gigachat_cache_path=tmp_path/"giga.sqlite",
                      gigachat_ca_bundle=Path(httpx.__file__).parent/"_config.py")
    c=GigaChatClient(settings,httpx.MockTransport(handler))
    verified=[]
    monkeypatch.setattr(c,"_verify",lambda: verified.append(True) or True)
    assert asyncio.run(c.models())==["GigaChat-2","GigaChat-Pro"]
    assert verified==[True] and [x.url.path for x in calls]==["/api/v2/oauth","/api/v1/models"]
    assert [x["kind"] for x in c.cache.records()]==["oauth","model_discovery"]

def test_notebook_connection_cell_uses_current_public_discovery_interface():
    notebook=json.loads(Path("ml_workspace/notebooks/gigachat_matching_experiment.ipynb").read_text(encoding="utf-8"))
    cell=next(c for c in notebook["cells"] if c.get("id")=="bf2cfd12")
    source="".join(cell["source"])
    assert "importlib.reload(gigachat_module)" in source
    assert "await giga.models()" in source
    assert "giga._authenticate" not in source and "httpx.AsyncClient" not in source

def test_valid_estimate_ready_structured_response_and_cache(tmp_path):
    body={"decision":"accept","product_category":"lighting","material":"lighting","work_types":["lighting_install"],"evidence":["Светильник"],"reason":"явная маркировка"}
    c,calls=client(tmp_path,[response(body,{"prompt_tokens":100,"completion_tokens":20,"total_tokens":120})])
    first=asyncio.run(c.classify(product())); second=asyncio.run(c.classify(product()))
    assert first==second and first.result_level=="estimate_ready"
    chats=[x for x in calls if x.url.path.endswith("chat/completions")]
    assert len(chats)==1 and json.loads(chats[0].content)["response_format"]["type"]=="json_schema"
    assert c.stats["cache_hits"]==1 and c.stats["tokens"]==120

def test_valid_category_only_and_rejection_or_abstention(tmp_path):
    c,_=client(tmp_path,[response({"decision":"accept","product_category":"lighting","reason":"clear"},{"total_tokens":10})])
    assert asyncio.run(c.classify(product())).result_level=="category_only"
    for decision in ("reject","uncertain"):
        c,_=client(tmp_path/decision,[response({"decision":decision,"reason":"not enough"})])
        assert asyncio.run(c.classify(product())).result_level=="abstention"

@pytest.mark.parametrize("bad",[{"decision":"accept","product_category":"socket","reason":"invented"},{"decision":"accept","reason":"missing"}])
def test_schema_failures_are_classified_and_usage_retained(tmp_path,bad):
    c,_=client(tmp_path,[response(bad,{"prompt_tokens":7,"completion_tokens":3,"total_tokens":10})],gigachat_repair_invalid_response=False)
    with pytest.raises(GigaChatError) as exc: asyncio.run(c.classify(product()))
    assert exc.value.kind=="schema_validation" and c.cache.tokens()==10
    assert c.cache.records()[-1]["status"]=="schema_validation"

def test_invalid_json_one_controlled_repair_and_both_calls_count(tmp_path):
    fixed={"decision":"accept","product_category":"lighting","reason":"repaired"}
    c,calls=client(tmp_path,[response('{"decision":',{"total_tokens":11}),response(fixed,{"total_tokens":13})])
    assert asyncio.run(c.classify(product())).result_level=="category_only" and c.cache.tokens()==24
    assert len([x for x in calls if x.url.path.endswith("chat/completions")])==2

def test_malformed_repair_failure_stops_after_one_retry(tmp_path):
    c,calls=client(tmp_path,[response("bad",{"total_tokens":5}),response("still bad",{"total_tokens":6})])
    with pytest.raises(GigaChatError) as exc: asyncio.run(c.classify(product()))
    assert exc.value.kind=="invalid_json" and c.cache.tokens()==11
    assert len([x for x in calls if x.url.path.endswith("chat/completions")])==2

@pytest.mark.parametrize("body",[
 {"decision":"accept","product_category":"lighting","material":"lighting","work_types":["wallpapering"],"reason":"bad"},
 {"decision":"accept","product_category":"primer","material":"paint","work_types":[],"reason":"bad"}])
def test_taxonomy_conflicts_are_explicit_abstentions(tmp_path,body):
    c,_=client(tmp_path,[response(body,{"total_tokens":9})]); result=asyncio.run(c.classify(product()))
    assert result.decision=="uncertain" and result.validation_status=="taxonomy_conflict"

def test_ssl_bundle_is_configurable(tmp_path):
    pem=tmp_path/"ca.pem"; pem.write_text("invalid certificate",encoding="utf-8")
    c,_=client(tmp_path,[],gigachat_ca_bundle=pem)
    with pytest.raises(ssl.SSLError): c._verify()
    c.s.gigachat_ca_bundle=tmp_path/"missing.pem"
    with pytest.raises(GigaChatError): c._verify()

def test_unknown_usage_and_budget_reservation(tmp_path):
    body={"decision":"accept","product_category":"lighting","reason":"ok"}
    c,_=client(tmp_path,[response(body)],gigachat_token_budget=2000,gigachat_token_reservation=2500)
    with pytest.raises(GigaChatError) as exc: asyncio.run(c.classify(product()))
    assert exc.value.kind=="budget"
    c,_=client(tmp_path,[response(body)],gigachat_token_budget=3000); asyncio.run(c.classify(product()))
    assert c.cache.records()[-1]["total_tokens"] is None and c.stats["unknown_usage"]==1

def test_api_unavailable_keeps_admin_fallback(tmp_path):
    def down(_): raise httpx.ConnectError("offline")
    c,_=client(tmp_path,[down])
    with pytest.raises(GigaChatError): asyncio.run(c.classify(product()))
    ml=Suggestion(product_category=ProductCategory.lighting,material=Material.lighting,work_types=[WorkType.lighting_install],confidence=.4,flags={"domain_renovation":True},model="tfidf")
    assert decide_hybrid(ml,None,.6).action=="admin_review" and eligible_for_gigachat(ml,.6)

@pytest.mark.parametrize("failure", [httpx.ReadTimeout("slow"), ssl.SSLError("bad CA")])
def test_timeout_and_ssl_failures_are_normalized(tmp_path, failure):
    def down(_): raise failure
    c,_=client(tmp_path,[down])
    with pytest.raises(GigaChatError) as exc: asyncio.run(c.classify(product()))
    assert exc.value.kind=="api_error" and c.cache.records()[-1]["status"]=="api_error"

def test_authentication_failure_is_normalized_without_chat_request(tmp_path):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(401,json={"message":"invalid credentials"})
    settings=Settings(gigachat_enabled=True,gigachat_credentials="secret",
        gigachat_cache_path=tmp_path/"giga.sqlite",gigachat_retries=0)
    c=GigaChatClient(settings,httpx.MockTransport(handler))
    with pytest.raises(GigaChatError) as exc: asyncio.run(c.classify(product()))
    assert exc.value.kind=="api_error"
    assert [x.url.path for x in calls]==["/api/v2/oauth"]

def test_retry_usage_is_counted_and_budget_is_rechecked(tmp_path):
    busy=httpx.Response(500,json={"usage":{"total_tokens":600}})
    ok=response({"decision":"accept","product_category":"lighting","reason":"ok"},{"total_tokens":10})
    c,calls=client(tmp_path,[busy,ok],gigachat_retries=1,gigachat_token_budget=3000,
                   gigachat_token_reservation=2500)
    with pytest.raises(GigaChatError) as exc: asyncio.run(c.classify(product()))
    assert exc.value.kind=="budget" and c.cache.tokens()==600
    assert len([x for x in calls if x.url.path.endswith("chat/completions")])==1

def test_hybrid_auto_acceptance_requires_estimate_ready_evidence():
    ml=Suggestion(product_category=ProductCategory.lighting,material=Material.other,work_types=[],confidence=.4,flags={"domain_renovation":True,"ml_unknown":True},model="tfidf")
    broad=GigaClassification(decision="accept",product_category="lighting",reason="broad")
    ready=GigaClassification(decision="accept",product_category="lighting",material="lighting",work_types=["lighting_install"],evidence=["Светильник"],reason="clear")
    assert decide_hybrid(ml,broad).action=="admin_review" and decide_hybrid(ml,ready).action=="accept_gigachat"
    assert not eligible_for_gigachat(ml.model_copy(update={"flags":{"domain_non_renovation":True}}))

def test_cache_namespace_and_product_identity_invalidate_old_classification(tmp_path):
    body={"decision":"accept","product_category":"lighting","reason":"ok"}
    c,calls=client(tmp_path,[response(body,{"total_tokens":5}),response(body,{"total_tokens":5})])
    asyncio.run(c.classify(product()))
    c.s.gigachat_cache_namespace="rerun-v3"
    asyncio.run(c.classify(product()))
    assert len([x for x in calls if x.url.path.endswith("chat/completions")])==2
