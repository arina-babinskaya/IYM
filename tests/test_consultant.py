import asyncio
import concurrent.futures
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.api.deps import get_gigachat
from app.config import get_settings
from app.consultant_prompt import CONSULTANT_SYSTEM_PROMPT, automatic_chat_title
from app.llm.gigachat import GigaChatError
from app.main import app
from app.db import get_engine, get_sessionmaker
from app.models import ConsultantMessage


class FakeGiga:
    def __init__(self):
        self.calls = []

    async def consultant_chat(self, messages):
        self.calls.append(messages)
        return "Какое помещение вы ремонтируете?"


@pytest.fixture
def consultant(ingested):
    fake = FakeGiga()
    app.dependency_overrides[get_gigachat] = lambda: fake
    with TestClient(app) as client:
        yield client, fake
    app.dependency_overrides.clear()


def test_chat_crud_order_and_prompt(consultant):
    client, fake = consultant
    created = client.post("/api/v1/consultant/chats", json={"title": "Детская"})
    assert created.status_code == 201
    chat_id = created.json()["id"]
    assert client.patch(f"/api/v1/consultant/chats/{chat_id}", json={"title": "Комната ребёнка"}).json()["title"] == "Комната ребёнка"
    answer = client.post(f"/api/v1/consultant/chats/{chat_id}/messages", json={
        "content": "Нужен практичный ремонт", "request_id": "request_0001"
    })
    assert answer.status_code == 200
    detail = client.get(f"/api/v1/consultant/chats/{chat_id}").json()
    assert [x["role"] for x in detail["messages"]] == ["user", "assistant"]
    assert fake.calls[0][0] == {"role": "system", "content": CONSULTANT_SYSTEM_PROMPT}
    assert fake.calls[0][-1]["content"] == "Нужен практичный ремонт"
    assert client.delete(f"/api/v1/consultant/chats/{chat_id}").status_code == 204
    assert client.get(f"/api/v1/consultant/chats/{chat_id}").status_code == 404


def test_independent_histories_idempotence_and_session_isolation(consultant):
    client, fake = consultant
    one = client.post("/api/v1/consultant/chats", json={"title": "Ванная"}).json()["id"]
    two = client.post("/api/v1/consultant/chats", json={"title": "Кухня"}).json()["id"]
    payload = {"content": "Есть ванна", "request_id": "same_request_1"}
    first = client.post(f"/api/v1/consultant/chats/{one}/messages", json=payload)
    second = client.post(f"/api/v1/consultant/chats/{one}/messages", json=payload)
    assert first.json()["id"] == second.json()["id"] and len(fake.calls) == 1
    client.post(f"/api/v1/consultant/chats/{two}/messages", json={"content":"Часто готовим", "request_id":"request_kitchen"})
    assert "Есть ванна" not in str(fake.calls[-1])
    with TestClient(app) as stranger:
        assert stranger.get(f"/api/v1/consultant/chats/{one}").status_code == 404


def test_history_survives_new_client_with_same_cookie(consultant):
    client, _ = consultant
    chat_id = client.post("/api/v1/consultant/chats", json={"title": "Гостиная"}).json()["id"]
    cookie = client.cookies.get("repaircalc_consultant_session")
    with TestClient(app, cookies={"repaircalc_consultant_session": cookie}) as reloaded:
        assert reloaded.get(f"/api/v1/consultant/chats/{chat_id}").json()["title"] == "Гостиная"


def test_provider_error_does_not_persist_exchange(consultant):
    client, fake = consultant
    async def fail(_):
        raise GigaChatError("GigaChat unavailable: TimeoutException")
    fake.consultant_chat = fail
    chat_id = client.post("/api/v1/consultant/chats", json={"title": "Ошибка"}).json()["id"]
    response = client.post(f"/api/v1/consultant/chats/{chat_id}/messages", json={"content":"Тест", "request_id":"request_error"})
    assert response.status_code == 503
    assert client.get(f"/api/v1/consultant/chats/{chat_id}").json()["messages"] == []


def test_provider_timeout_is_actionable_and_not_persisted(consultant):
    client, fake = consultant
    async def timeout(_):
        raise asyncio.TimeoutError
    fake.consultant_chat = timeout
    chat_id = client.post("/api/v1/consultant/chats", json={"title": "Таймаут"}).json()["id"]
    result = client.post(f"/api/v1/consultant/chats/{chat_id}/messages", json={"content":"Тест", "request_id":"request_timeout"})
    assert result.status_code == 504 and "Попробуйте" in result.json()["detail"]
    assert client.get(f"/api/v1/consultant/chats/{chat_id}").json()["messages"] == []


def test_typed_provider_timeout_is_actionable_and_not_persisted(consultant):
    client, fake = consultant
    async def timeout(_):
        raise GigaChatError("GigaChat unavailable: timeout", kind="timeout", diagnostic={"step":"transport"})
    fake.consultant_chat = timeout
    chat_id = client.post("/api/v1/consultant/chats", json={"title":"Таймаут"}).json()["id"]
    result = client.post(f"/api/v1/consultant/chats/{chat_id}/messages", json={"content":"Тест", "request_id":"request_typed_timeout"})
    assert result.status_code == 504
    assert client.get(f"/api/v1/consultant/chats/{chat_id}").json()["messages"] == []


def test_missing_credentials_message(ingested):
    app.dependency_overrides.pop(get_gigachat, None)
    settings = get_settings()
    old_enabled, old_credentials = settings.gigachat_enabled, settings.gigachat_credentials
    settings.gigachat_enabled, settings.gigachat_credentials = False, None
    try:
        with TestClient(app) as client:
            chat_id = client.post("/api/v1/consultant/chats", json={"title":"Без ключа"}).json()["id"]
            result = client.post(f"/api/v1/consultant/chats/{chat_id}/messages", json={"content":"Привет", "request_id":"request_nokey"})
            assert result.status_code == 503 and "не настроен" in result.json()["detail"]
    finally:
        settings.gigachat_enabled, settings.gigachat_credentials = old_enabled, old_credentials


def test_frontend_has_consultant_and_calculator_navigation():
    html = Path("app/static/index.html").read_text()
    assert 'data-tab="consultant"' in html and "Консультант" in html
    assert 'id="chat-to-calc"' in html and 'switchTab("calc")' in html
    assert 'data-copy-message' in html and 'data-edit-message' in html
    assert 'navigator.clipboard.writeText(message.content)' in html
    assert 'document.execCommand("copy")' in html
    assert 'Скопировано' in html and 'Сохранить и отправить' in html
    assert 'current.preview = answer.content' in html
    assert 'const chatId = C.store.active' in html
    assert 'Консультант печатает…' in html


def test_frontend_state_keeps_out_of_order_chats_isolated():
    script = r'''
      const Store=require('./app/static/consultant_state.js');
      const s=new Store();
      s.select('a'); const ao=s.beginOperation('a'); s.ensure('a').messages.push({content:'A user'});
      s.select('b'); const bo=s.beginOperation('b'); s.ensure('b').messages.push({content:'B user'});
      s.ensure('a').editing={id:1,content:'edit A'};
      if (s.ensure('b').editing!==null || !s.ensure('a').loading || !s.ensure('b').loading) process.exit(6);
      s.ensure('b').messages.push({content:'B answer'}); s.finishOperation('b',bo);
      if (s.active!=='b' || s.ensure('a').messages.some(x=>x.content.includes('B'))) process.exit(1);
      s.ensure('a').messages.push({content:'A answer'}); s.finishOperation('a',ao);
      if (s.active!=='b' || s.ensure('b').messages.some(x=>x.content.includes('A'))) process.exit(2);
      const old=s.beginLoad('b'), fresh=s.beginLoad('b');
      if (s.applyLoad('b',old,[{content:'stale'}])) process.exit(3);
      if (!s.applyLoad('b',fresh,[{content:'fresh'}],42) || !s.hasFreshHistory('b',42)) process.exit(4);
      if (s.hasFreshHistory('b',43)) process.exit(7);
      s.ensure('b').historyFetchedAt=0; if (s.hasFreshHistory('b',42)) process.exit(8);
      s.select('c'); const cg=s.beginHistory('c'); if (cg===null || s.beginHistory('c')!==null) process.exit(9);
      s.cancelHistory('c'); const retry=s.beginHistory('c'); if (retry===null || retry===cg) process.exit(10);
      s.finishHistory('c',retry); if (s.ensure('c').historyLoading) process.exit(11);
      let aborted=false; const hg=s.beginHistory('b'); s.ensure('b').historyAbort={abort:()=>aborted=true};
      const send=s.beginOperation('b');
      if (send===null || !aborted || s.ensure('b').historyLoading) process.exit(12);
      if (s.applyLoad('b',hg,[{content:'obsolete snapshot'}])) process.exit(13);
      s.finishOperation('b',send);
      const pending=s.beginOperation('a'); s.remove('a');
      if (s.finishOperation('a',pending)) process.exit(5);

      // Exact browser regression: null used to survive in messages until renderMessages read
      // m.content, throwing before sendChat entered its try/finally and leaving loading=true.
      s.select('null-chat'); s.ensure('null-chat').messages=[null,{role:'assistant',content:null},
        {role:'assistant',content:'valid',created_at:new Date().toISOString()}];
      if (s.ensure('null-chat').messages.length!==1) process.exit(14);
      const ng=s.beginHistory('null-chat');
      if (!s.applyLoad('null-chat',ng,[null,{role:'user',content:'ok'}],7)) process.exit(15);
      if (s.ensure('null-chat').messages.length!==1 || s.ensure('null-chat').messages[0].content!=='ok') process.exit(16);
      if (s.appendMessage('null-chat',null) || s.appendMessage('null-chat',{role:'assistant',content:null})) process.exit(17);
      if (!s.appendMessage('null-chat',{role:'assistant',content:'answer'})) process.exit(18);
    '''
    subprocess.run(["node", "-e", script], check=True)


def test_frontend_navigation_keeps_other_chat_history_request_alive():
    html = Path("app/static/index.html").read_text()
    open_chat = html[html.index("async function openChat"):html.index("function showChatError")]
    assert "cancelHistory(previousId)" not in open_chat
    assert "if (state.historyLoading)" in open_chat
    assert "consultant_state.js?v=" in html


def test_frontend_null_messages_are_defensive_and_send_cleanup_wraps_render():
    html = Path("app/static/index.html").read_text()
    render = html[html.index("function renderMessages"):html.index("function setChatControls")]
    send = html[html.index("async function sendChat"):html.index("async function copyChatMessage")]
    edit = html[html.index("async function saveEditedMessage"):html.index("chatMessages.onclick")]
    assert "ConsultantStateStore.validMessages(state?.messages)" in render
    assert send.index("try {") < send.index("renderChatList(); renderMessages()")
    assert "C.store.appendMessage(chatId, answer)" in send
    assert "C.store.finishOperation(chatId, operation)" in send
    assert edit.index("try {") < edit.index("renderMessages(); renderChatList()")
    assert "consultant_state.js?v=20261031-3" in html


def test_complete_frontend_first_message_flow_has_no_false_edit_mode():
    """Execute the real renderMessages/sendChat source for a new chat in Node.

    The first optimistic message deliberately has no id. This reproduced the browser exception:
    null?.id and message.id were both undefined, so the renderer entered edit mode and read
    state.editing.content even though editing was null.
    """
    script = r'''
      const fs=require('fs'), Store=require('./app/static/consultant_state.js');
      const html=fs.readFileSync('./app/static/index.html','utf8');
      const take=(start,end)=>html.slice(html.indexOf(start),html.indexOf(end));
      const source=take('function chatMarkup','function setChatControls') + '\n' +
        take('async function sendChat','async function copyChatMessage');
      const C={chats:[{id:'new-chat',title:'Новый чат',preview:null,last_message_id:null,
        created_at:new Date().toISOString(),updated_at:new Date().toISOString()}],store:new Store(),loaded:true};
      C.store.select('new-chat'); const initial=C.store.ensure('new-chat');
      initial.historyLoaded=true; initial.lastMessageId=null;
      const chatInput={value:'Хочу сделать гостиную в стиле бохо.',disabled:false};
      const chatMessages={innerHTML:'',scrollTop:0,scrollHeight:0,
        insertAdjacentHTML(_where,value){this.innerHTML+=value;}};
      const chatList={innerHTML:'',querySelectorAll(){return [];}};
      const calc={hidden:true};
      const document={getElementById(id){if(id==='chat-to-calc') return calc; throw new Error('unexpected element '+id);}};
      const ConsultantStateStore=Store, activeChatState=()=>C.store.activeState();
      const esc=s=>String(s??'').replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));
      const renderChatError=()=>{}, setChatControls=()=>{};
      const showChatError=(message,id)=>{ C.store.ensure(id).error=message; };
      const refreshChatList=async()=>{};
      const replies=[
        {id:2,role:'assistant',content:'Рекомендую натуральные материалы.',created_at:new Date().toISOString()},
        {id:'new-chat',title:'Гостиная',title_source:'auto',preview:'Рекомендую натуральные материалы.',
          last_message_id:2,created_at:new Date().toISOString(),updated_at:new Date().toISOString(),messages:[
            {id:1,role:'user',content:'Хочу сделать гостиную в стиле бохо.',created_at:new Date().toISOString()},
            {id:2,role:'assistant',content:'Рекомендую натуральные материалы.',created_at:new Date().toISOString()}]}
      ];
      const api=async()=>replies.shift();
      global.crypto={randomUUID:()=> 'request-12345678'};
      eval(source);
      (async()=>{
        await sendChat();
        const state=C.store.ensure('new-chat');
        if(state.loading || state.error) process.exit(1);
        if(state.messages.length!==2 || state.messages[0].content!=='Хочу сделать гостиную в стиле бохо.') process.exit(2);
        if(!chatMessages.innerHTML.includes('Рекомендую натуральные материалы.')) process.exit(3);
        if(chatInput.value!=='' || C.chats[0].title!=='Гостиная') process.exit(4);
      })().catch(error=>{console.error(error);process.exit(5);});
    '''
    subprocess.run(["node", "-e", script], check=True)


@pytest.mark.parametrize(("message", "title"), [
    ("Хочу сделать гостиную в стиле бохо", "Гостиная"),
    ("Что лучше использовать в гостиной?", "Гостиная"),
    ("Планирую ремонт детской комнаты", "Детская"),
    ("Какие материалы нужны для ванной?", "Ванная"),
    ("Что положить на кухне?", "Кухня"),
    ("Помоги выбрать пол в спальню", "Спальня"),
    ("Делаю ремонт всей квартиры", "Вся квартира"),
    ("Ремонт кухни и спальни", "Несколько комнат"),
    ("Хочу подобрать обои", "Подбор обоев"),
    ("Нужна помощь с материалами", "Консультация по материалам"),
])
def test_automatic_chat_title(message, title):
    assert automatic_chat_title(message) == title


def test_preview_auto_title_order_and_reload(consultant):
    client, _ = consultant
    first = client.post("/api/v1/consultant/chats", json={}).json()
    empty = client.post("/api/v1/consultant/chats", json={}).json()
    sent = client.post(f"/api/v1/consultant/chats/{first['id']}/messages", json={
        "content":"Хочу сделать гостиную в стиле бохо", "request_id":"preview_title_1"
    })
    assert sent.status_code == 200
    rows = client.get("/api/v1/consultant/chats").json()
    assert rows[0]["id"] == first["id"]
    assert rows[0]["title"] == "Гостиная" and rows[0]["title_source"] == "auto"
    assert rows[0]["preview"] == "Какое помещение вы ремонтируете?"
    assert next(x for x in rows if x["id"] == empty["id"])["preview"] is None
    cookie = client.cookies.get("repaircalc_consultant_session")
    with TestClient(app, cookies={"repaircalc_consultant_session": cookie}) as reloaded:
        persisted = reloaded.get("/api/v1/consultant/chats").json()[0]
        assert persisted["preview"] == "Какое помещение вы ремонтируете?"


def test_manual_title_is_never_overwritten(consultant):
    client, _ = consultant
    chat_id = client.post("/api/v1/consultant/chats", json={}).json()["id"]
    renamed = client.patch(f"/api/v1/consultant/chats/{chat_id}", json={"title":"Мой проект"}).json()
    assert renamed["title_source"] == "manual"
    client.post(f"/api/v1/consultant/chats/{chat_id}/messages", json={
        "content":"Ремонт ванной", "request_id":"manual_title_1"
    })
    assert client.get(f"/api/v1/consultant/chats/{chat_id}").json()["title"] == "Мой проект"


def _chat_with_two_turns(client):
    chat_id = client.post("/api/v1/consultant/chats", json={}).json()["id"]
    client.post(f"/api/v1/consultant/chats/{chat_id}/messages", json={"content":"Ремонт гостиной", "request_id":"edit_base_1"})
    client.post(f"/api/v1/consultant/chats/{chat_id}/messages", json={"content":"Бюджет средний", "request_id":"edit_base_2"})
    return chat_id, client.get(f"/api/v1/consultant/chats/{chat_id}").json()


def test_edit_older_message_regenerates_branch_and_auto_title(consultant):
    client, fake = consultant; chat_id, before = _chat_with_two_turns(client)
    first_user = before["messages"][0]
    result = client.patch(f"/api/v1/consultant/chats/{chat_id}/messages/{first_user['id']}", json={
        "content":"Хочу сделать спальню в минималистичном стиле",
        "request_id":"edit_regenerate_1", "expected_last_message_id":before["last_message_id"],
    })
    assert result.status_code == 200
    chat = result.json()
    assert chat["title"] == "Спальня"
    assert [x["role"] for x in chat["messages"]] == ["user", "assistant"]
    assert chat["messages"][0]["content"].startswith("Хочу сделать спальню")
    assert "Бюджет средний" not in str(chat["messages"])
    assert fake.calls[-1][-1]["content"].startswith("Хочу сделать спальню")
    assert len(fake.calls[-1]) == 2  # system + revised first message
    assert client.get("/api/v1/consultant/chats").json()[0]["preview"] == chat["messages"][-1]["content"]


def test_edit_latest_user_preserves_prior_context_and_is_idempotent(consultant):
    client, fake = consultant; chat_id, before = _chat_with_two_turns(client)
    latest_user = before["messages"][-2]
    payload = {"content":"Бюджет высокий", "request_id":"edit_latest_1",
               "expected_last_message_id":before["last_message_id"]}
    first = client.patch(f"/api/v1/consultant/chats/{chat_id}/messages/{latest_user['id']}", json=payload)
    second = client.patch(f"/api/v1/consultant/chats/{chat_id}/messages/{latest_user['id']}", json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json()["messages"] == second.json()["messages"]
    assert len(fake.calls) == 3  # two sends and one regeneration
    assert [x["role"] for x in fake.calls[-1][1:]] == ["user", "assistant", "user"]


def test_edit_failure_rolls_back_and_conflict_is_detected(consultant):
    client, fake = consultant; chat_id, before = _chat_with_two_turns(client)
    original = before["messages"]
    async def fail(_):
        raise GigaChatError("provider failed", kind="connection")
    fake.consultant_chat = fail
    target = original[0]
    failed = client.patch(f"/api/v1/consultant/chats/{chat_id}/messages/{target['id']}", json={
        "content":"Ремонт кухни", "request_id":"edit_failure_1",
        "expected_last_message_id":before["last_message_id"],
    })
    assert failed.status_code == 503
    assert client.get(f"/api/v1/consultant/chats/{chat_id}").json()["messages"] == original
    conflict = client.patch(f"/api/v1/consultant/chats/{chat_id}/messages/{target['id']}", json={
        "content":"Ремонт кухни", "request_id":"edit_conflict_1",
        "expected_last_message_id":before["last_message_id"] - 1,
    })
    assert conflict.status_code == 409


def test_edit_authorization_and_assistant_rejection(consultant):
    client, _ = consultant; chat_id, detail = _chat_with_two_turns(client)
    assistant = detail["messages"][1]
    rejected = client.patch(f"/api/v1/consultant/chats/{chat_id}/messages/{assistant['id']}", json={
        "content":"Нельзя", "request_id":"edit_assistant_1",
        "expected_last_message_id":detail["last_message_id"],
    })
    assert rejected.status_code == 403
    with TestClient(app) as stranger:
        denied = stranger.patch(f"/api/v1/consultant/chats/{chat_id}/messages/{detail['messages'][0]['id']}", json={
            "content":"Чужое", "request_id":"edit_stranger_1",
            "expected_last_message_id":detail["last_message_id"],
        })
        assert denied.status_code == 404


def test_concurrent_chats_have_isolated_context_and_out_of_order_responses(consultant):
    client, _ = consultant
    class DelayedGiga:
        def __init__(self): self.calls=[]
        async def consultant_chat(self, messages):
            self.calls.append([dict(x) for x in messages])
            text=messages[-1]["content"]
            await asyncio.sleep(.10 if "детск" in text.lower() else .02)
            return "Ответ детской" if "детск" in text.lower() else "Ответ гостиной"
    fake=DelayedGiga(); app.dependency_overrides[get_gigachat]=lambda:fake
    one=client.post("/api/v1/consultant/chats",json={}).json()["id"]
    two=client.post("/api/v1/consultant/chats",json={}).json()["id"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        slow=pool.submit(client.post,f"/api/v1/consultant/chats/{one}/messages",json={"content":"Обои для детской","request_id":"parallel_child_1"})
        time.sleep(.01)
        fast=pool.submit(client.post,f"/api/v1/consultant/chats/{two}/messages",json={"content":"Бохо в гостиной","request_id":"parallel_living_1"})
        fast_result=fast.result(); slow_result=slow.result()
    assert fast_result.json()["content"]=="Ответ гостиной"
    assert slow_result.json()["content"]=="Ответ детской"
    child=client.get(f"/api/v1/consultant/chats/{one}").json()
    living=client.get(f"/api/v1/consultant/chats/{two}").json()
    assert [x["content"] for x in child["messages"]]==["Обои для детской","Ответ детской"]
    assert [x["content"] for x in living["messages"]]==["Бохо в гостиной","Ответ гостиной"]
    child_call=next(x for x in fake.calls if x[-1]["content"]=="Обои для детской")
    living_call=next(x for x in fake.calls if x[-1]["content"]=="Бохо в гостиной")
    assert "гостин" not in str(child_call).lower()
    assert "детск" not in str(living_call).lower()
    rows=client.get("/api/v1/consultant/chats").json()
    previews={x["id"]:x["preview"] for x in rows}
    assert previews=={one:"Ответ детской",two:"Ответ гостиной"}


def test_delete_waits_for_pending_message_and_removes_complete_chat(consultant):
    client, _ = consultant
    class SlowGiga:
        async def consultant_chat(self, _): await asyncio.sleep(.08); return "Готово"
    app.dependency_overrides[get_gigachat]=lambda:SlowGiga()
    chat_id=client.post("/api/v1/consultant/chats",json={}).json()["id"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        pending=pool.submit(client.post,f"/api/v1/consultant/chats/{chat_id}/messages",json={"content":"Тест","request_id":"delete_pending_1"})
        time.sleep(.01)
        removed=pool.submit(client.delete,f"/api/v1/consultant/chats/{chat_id}")
        assert pending.result().status_code==200
        assert removed.result().status_code==204
    assert client.get(f"/api/v1/consultant/chats/{chat_id}").status_code==404


def test_concurrent_same_chat_requests_are_ordered_and_second_sees_first(consultant):
    client, _ = consultant
    class OrderedGiga:
        def __init__(self): self.calls=[]
        async def consultant_chat(self, messages):
            self.calls.append([dict(x) for x in messages])
            await asyncio.sleep(.05 if messages[-1]["content"]=="Первое" else .01)
            return f"Ответ: {messages[-1]['content']}"
    fake=OrderedGiga(); app.dependency_overrides[get_gigachat]=lambda:fake
    chat_id=client.post("/api/v1/consultant/chats",json={}).json()["id"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(client.post,f"/api/v1/consultant/chats/{chat_id}/messages",json={"content":"Первое","request_id":"same_chat_parallel_1"})
        time.sleep(.01)
        second=pool.submit(client.post,f"/api/v1/consultant/chats/{chat_id}/messages",json={"content":"Второе","request_id":"same_chat_parallel_2"})
        assert first.result().status_code==second.result().status_code==200
    assert len(fake.calls)==2
    second_context=fake.calls[1]
    assert [x["content"] for x in second_context[1:]] == ["Первое", "Ответ: Первое", "Второе"]
    detail=client.get(f"/api/v1/consultant/chats/{chat_id}").json()
    assert [x["content"] for x in detail["messages"]] == ["Первое", "Ответ: Первое", "Второе", "Ответ: Второе"]


def test_failed_request_can_retry_same_id_without_duplicate(consultant):
    client, fake = consultant
    chat_id=client.post("/api/v1/consultant/chats",json={}).json()["id"]
    async def fail(_): raise GigaChatError("offline",kind="connection")
    fake.consultant_chat=fail
    payload={"content":"Повтор","request_id":"retry_after_failure_1"}
    assert client.post(f"/api/v1/consultant/chats/{chat_id}/messages",json=payload).status_code==503
    async def succeed(messages): fake.calls.append(messages); return "Получилось"
    fake.consultant_chat=succeed
    assert client.post(f"/api/v1/consultant/chats/{chat_id}/messages",json=payload).status_code==200
    detail=client.get(f"/api/v1/consultant/chats/{chat_id}").json()
    assert [x["content"] for x in detail["messages"]]==["Повтор","Получилось"]


def test_chat_list_uses_one_summary_query_not_full_history_n_plus_one(consultant):
    client, _ = consultant
    chat_ids=[client.post("/api/v1/consultant/chats",json={}).json()["id"] for _ in range(3)]
    with get_sessionmaker()() as db:
        for chat_id in chat_ids:
            for i in range(40):
                db.add(ConsultantMessage(chat_id=chat_id,exchange_id=f"bulk_{chat_id}_{i}",
                    role="user" if i%2==0 else "assistant",content=f"message {i}"))
        db.commit()
    statements=[]
    def record(_, __, statement, ___, ____, _____):
        if statement.lstrip().lower().startswith("select"): statements.append(statement)
    event.listen(get_engine(),"before_cursor_execute",record)
    try:
        response=client.get("/api/v1/consultant/chats")
    finally:
        event.remove(get_engine(),"before_cursor_execute",record)
    assert response.status_code==200
    assert len(statements)==1 and len(response.json())==3
    assert all(x["preview"]=="message 39" for x in response.json())
    assert "db;dur=" in response.headers["server-timing"]


def test_long_history_load_is_local_and_has_server_timing(consultant):
    client, _ = consultant
    chat_id=client.post("/api/v1/consultant/chats",json={}).json()["id"]
    with get_sessionmaker()() as db:
        for i in range(300):
            db.add(ConsultantMessage(chat_id=chat_id,exchange_id=f"long_{i}",
                role="user" if i%2==0 else "assistant",content="Длинная история " + str(i)))
        db.commit()
    started=time.perf_counter(); response=client.get(f"/api/v1/consultant/chats/{chat_id}")
    elapsed=time.perf_counter()-started
    assert response.status_code==200 and len(response.json()["messages"])==300
    assert elapsed < 1.0
    assert "db;dur=" in response.headers["server-timing"]


def test_provider_wait_releases_database_connection_for_history_reads(consultant):
    client, _ = consultant
    class ObservedSlowGiga:
        def __init__(self): self.checked_out=None
        async def consultant_chat(self, _):
            self.checked_out=get_engine().pool.checkedout()
            await asyncio.sleep(.08)
            return "Готово"
    fake=ObservedSlowGiga(); app.dependency_overrides[get_gigachat]=lambda:fake
    slow_id=client.post("/api/v1/consultant/chats",json={}).json()["id"]
    read_id=client.post("/api/v1/consultant/chats",json={}).json()["id"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        pending=pool.submit(client.post,f"/api/v1/consultant/chats/{slow_id}/messages",json={"content":"Ждать","request_id":"db_release_wait_1"})
        time.sleep(.02); started=time.perf_counter()
        history=client.get(f"/api/v1/consultant/chats/{read_id}")
        read_elapsed=time.perf_counter()-started
        assert pending.result().status_code==200
    assert history.status_code==200 and read_elapsed < .07
    assert fake.checked_out==0
