"""Single-worker demonstration API. No real legal decisions or telephony."""
from collections import defaultdict, deque
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
import hmac
import os
from pathlib import PurePath
import secrets
import threading
import time
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select
from .database import Record, database, now, seed
from .model_gateway import configured_provider
from .speech import MAX_AUDIO_BYTES, SpeechError, local_engine, transcribe
from . import schemas as S
from .services import VERSION, CATEGORIES, POLICY, ident, audit, tool, risk_flags, handoff, invalidate, orchestrate, lookup, candidates, append_run, explicit_conflicts


def digest(value): return hashlib.sha256(value.encode()).hexdigest()


def create_app(database_url=None, *, rate_limit=None):
    mode = os.getenv('APP_MODE', 'demo')
    if mode != 'demo':
        raise RuntimeError('当前版本仅支持 demo，真实试点须先完成独立认证、机构隔离与安全验收')
    app = FastAPI(title='法律援助多智能体接待平台（模拟）', version=VERSION)
    engine, factory = database(database_url or os.getenv('DATABASE_URL', 'sqlite:///./data/legal_aid.db'))
    app.state.engine, app.state.session_factory = engine, factory
    with factory() as db: seed(db)
    # Serializes demo writes, including check-and-create work orders. Run ONE worker.
    db_lock = threading.Lock()
    limiter_lock = threading.Lock()
    requests = defaultdict(deque)
    limit = rate_limit if rate_limit is not None else int(os.getenv('RATE_LIMIT_PER_MINUTE', '300'))
    password = os.getenv('DEMO_PASSWORD', 'local-demo-change-me')
    password_salt = secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), password_salt, 100000)
    del password
    app.add_middleware(CORSMiddleware, allow_origins=os.getenv('CORS_ORIGINS', 'http://localhost:3000,http://127.0.0.1:3000').split(','),
                       allow_credentials=False, allow_methods=['GET', 'POST', 'PATCH'], allow_headers=['Authorization', 'Content-Type', 'X-Session-Token'])

    @app.middleware('http')
    async def limits(request, call_next):
        path = request.url.path
        is_audio = request.method == 'POST' and path.startswith('/api/sessions/') and path.endswith('/transcribe')
        size_limit = MAX_AUDIO_BYTES if is_audio else 100000
        if request.headers.get('content-length', '0').isdigit() and int(request.headers.get('content-length', '0')) > size_limit:
            return JSONResponse(status_code=413, content={'detail': '请求体超过限制'})
        if request.method in {'POST', 'PATCH'}:
            body_size = 0
            chunks = []
            async for chunk in request.stream():
                body_size += len(chunk)
                if body_size > size_limit:
                    return JSONResponse(status_code=413, content={'detail': '请求体超过限制'})
                chunks.append(chunk)
            request._body = b''.join(chunks)
        # X-Forwarded-For is intentionally ignored; configure a trusted gateway in pilot.
        key = (request.client.host if request.client else 'unknown', 'login' if request.url.path == '/api/auth/login' else 'general')
        current = time.monotonic()
        with limiter_lock:
            queue = requests[key]
            while queue and queue[0] < current - 60: queue.popleft()
            ceiling = min(limit, 30) if key[1] == 'login' else limit
            denied = len(queue) >= ceiling
            if not denied: queue.append(current)
        if denied: return JSONResponse(status_code=429, content={'detail': '请求过于频繁，请稍后再试'}, headers={'Retry-After': '60'})
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Frame-Options'] = 'DENY'
        return response

    def get_db():
        with db_lock:
            with factory() as db:
                try:
                    yield db
                    db.commit()
                except HTTPException:
                    # Preserve denial audit events; handlers perform all validation before mutation.
                    db.commit()
                    raise
                except BaseException:
                    db.rollback()
                    raise

    def denied(db, action='permission_denied', object_id='', session_id=''):
        audit(db, 'unauthorized', action, object_id, session_id)
        raise HTTPException(403, '无权执行此操作')

    def principal(request, db):
        auth = request.headers.get('authorization', '')
        if not auth.startswith('Bearer '): return None
        hashed = digest(auth[7:])
        record = db.scalar(select(Record).where(Record.kind == 'auth', Record.token_hash == hashed))
        if not record: return None
        if datetime.fromisoformat(record.data['expires_at']) <= datetime.now(timezone.utc): return None
        return record.data

    def require_role(request, db, roles):
        who = principal(request, db)
        if not who or who['role'] not in roles: denied(db)
        return who

    def get_record(db, rid, kind):
        record = db.get(Record, rid)
        if not record or record.kind != kind: raise HTTPException(404, '记录不存在')
        return record

    def session_access(request, db, sid):
        record = get_record(db, sid, 'session')
        who = principal(request, db)
        if who and who['role'] in {'admin', 'staff'}: return record, who['username']
        token = request.headers.get('x-session-token', '')
        if not token or not hmac.compare_digest(record.token_hash or '', digest(token)):
            denied(db, object_id=sid, session_id=sid)
        return record, 'session_holder'

    def editable(s):
        if s['status'] not in {'collecting', 'awaiting_confirmation', 'awaiting_review'}:
            raise HTTPException(409, '当前会话已转人工、建单或关闭，不能继续自动接待')

    def persist(record, s):
        record.data = deepcopy(s)
        return s

    def add_message(db, s, content, actor):
        editable(s)
        if len(s['messages']) >= 100: return handoff(db, s, '会话消息达到限制')
        conflicts = explicit_conflicts(s['fields'], content)
        invalidate(s)
        s['messages'].append({'role': 'user', 'content': content})
        if conflicts:
            s['field_conflicts'] = conflicts
            s['risks'] = sorted(set(s['risks'] + ['关键字段冲突']))
            audit(db, actor, 'field_conflict_detected', s['id'], s['id'], {'fields': [c['field'] for c in conflicts]})
            return handoff(db, s, '补充内容与已登记关键字段冲突，请工作人员核对')
        flags = risk_flags(content)
        if flags:
            s['risks'] = sorted(set(s['risks'] + flags))
            handoff(db, s, '；'.join(flags))
        elif any(word in content for word in ['转人工', '找人工', '人工服务']): handoff(db, s, '用户要求人工')
        audit(db, actor, 'message_added', s['id'], s['id'], {'characters': len(content)})
        return s

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'mode': mode, 'version': VERSION, 'model_mode': os.getenv('MODEL_MODE', 'deterministic'),
                'model_provider': configured_provider() if os.getenv('MODEL_EXTERNAL_CONSENT') == 'true' and os.getenv('MODEL_API_KEY') else None,
                'speech_provider': 'local_whisper' if local_engine() else 'browser',
                'telephony': 'simulator_only', 'knowledge': 'demo_samples'}

    @app.post('/api/auth/login')
    def login(body: S.Login, db=Depends(get_db)):
        check = hashlib.pbkdf2_hmac('sha256', body.password.encode(), password_salt, 100000)
        if body.username not in {'admin', 'staff', 'reviewer', 'auditor'} or not hmac.compare_digest(check, password_hash):
            audit(db, 'anonymous', 'login_failed')
            raise HTTPException(401, '账号或密码错误')
        token = secrets.token_urlsafe(32)
        expiry = (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat()
        db.add(Record(id=ident(), kind='auth', token_hash=digest(token), data={'username': body.username, 'role': body.username, 'expires_at': expiry}))
        audit(db, body.username, 'login_succeeded')
        return {'access_token': token, 'token_type': 'bearer', 'username': body.username, 'role': body.username, 'expires_at': expiry}

    @app.post('/api/auth/logout')
    def logout(request: Request, db=Depends(get_db)):
        who = principal(request, db)
        if not who: raise HTTPException(401, '登录已失效')
        record = db.scalar(select(Record).where(Record.kind == 'auth', Record.token_hash == digest(request.headers['authorization'][7:])))
        db.delete(record)
        audit(db, who['username'], 'logout')
        return {'status': 'ok'}

    @app.post('/api/sessions', status_code=201)
    def new_session(body: S.NewSession, db=Depends(get_db)):
        sid, token = ident(), secrets.token_urlsafe(32)
        data = {'id': sid, 'channel': body.channel, 'status': 'collecting', 'consent': True, 'created_at': now(),
            'messages': [{'role': 'assistant', 'content': '这是模拟接待环境。请勿输入真实个人信息。请说明发生了什么、地点、时间和诉求；您随时可以转人工。'}],
            'fields': {'category': '', 'location': '', 'event_date': '', 'request': '', 'materials': []},
            'summary': '', 'summary_version': 0, 'confirmed_version': None, 'citations': [], 'evidence': [], 'candidates': [],
            'runs': [], 'risks': [], 'handoff_reason': '', 'work_order_id': None, 'clarification_count': 0, 'asr_failures': 0, 'is_demo': True}
        db.add(Record(id=sid, kind='session', data=data, token_hash=digest(token)))
        audit(db, 'session_holder', 'consent_recorded', sid, sid, {'channel': body.channel, 'version': 'demo-consent-v1'})
        return {**data, 'session_token': token}

    @app.get('/api/sessions')
    def sessions(request: Request, status: str | None = None, db=Depends(get_db)):
        require_role(request, db, {'admin', 'staff'})
        rows = [r.data for r in db.scalars(select(Record).where(Record.kind == 'session'))]
        return sorted([r for r in rows if not status or r['status'] == status], key=lambda r:r['created_at'], reverse=True)

    @app.get('/api/sessions/{sid}')
    def session_detail(sid: str, request: Request, db=Depends(get_db)):
        record, _ = session_access(request, db, sid)
        return record.data

    @app.post('/api/sessions/{sid}/messages')
    def messages(sid: str, body: S.Message, request: Request, db=Depends(get_db)):
        record, actor = session_access(request, db, sid)
        return persist(record, add_message(db, deepcopy(record.data), body.content, actor))

    def transcribe_session(sid: str, request: Request, recording: bytes, preview: bool):
        with db_lock, factory() as db:
            try:
                record, actor = session_access(request, db, sid)
                if actor != 'session_holder':
                    denied(db, object_id=sid, session_id=sid)
                editable(record.data)
            finally:
                db.commit()
        # Release the session write lock before decoding or running Whisper.
        try:
            return {'text': transcribe(recording, request.headers.get('content-type', ''), preview=preview)}
        except SpeechError as error:
            raise HTTPException(error.status_code, str(error)) from None

    @app.post('/api/sessions/{sid}/transcribe')
    async def speech_to_text(sid: str, request: Request, preview: bool = False):
        return await run_in_threadpool(transcribe_session, sid, request, await request.body(), preview)

    @app.patch('/api/sessions/{sid}/fields')
    def fields(sid: str, body: S.Fields, request: Request, db=Depends(get_db)):
        record, actor = session_access(request, db, sid)
        s = deepcopy(record.data)
        editable(s)
        patch = body.model_dump(exclude_none=True)
        if not patch: raise HTTPException(422, '请提供要修改的字段')
        invalidate(s)
        s['fields'].update(patch)
        flags = risk_flags(' '.join(str(x) for x in patch.values()))
        if flags:
            s['risks'] = sorted(set(s['risks'] + flags))
            handoff(db, s, '；'.join(flags))
        audit(db, actor, 'fields_updated', sid, sid, {'fields': sorted(patch)})
        return persist(record, s)

    @app.post('/api/orchestrator/run')
    def run(body: S.OrchestrationRun, request: Request, db=Depends(get_db)):
        record, actor = session_access(request, db, body.session_id)
        if body.allow_external_model and actor != 'session_holder':
            raise HTTPException(403, '须由本次咨询的使用者同意外部模型整理')
        s = deepcopy(record.data)
        if s['status'] != 'collecting': raise HTTPException(409, '仅信息收集状态允许运行；请先修改需要补充的字段')
        return persist(record, orchestrate(db, s, max_steps=int(os.getenv('MAX_AGENT_STEPS', '40')),
            max_cost=float(os.getenv('MAX_SESSION_COST', '1.0')), allow_external_model=body.allow_external_model))

    @app.post('/api/sessions/{sid}/confirm')
    def confirm(sid: str, body: S.Confirm, request: Request, db=Depends(get_db)):
        record, actor = session_access(request, db, sid)
        s = deepcopy(record.data)
        if actor != 'session_holder': raise HTTPException(403, '摘要须由会话持有人确认')
        if s['status'] != 'awaiting_confirmation' or body.summary_version != s['summary_version']:
            raise HTTPException(409, '摘要状态或版本已变化，请重新核对')
        s['status'], s['confirmed_version'] = 'awaiting_review', body.summary_version
        audit(db, actor, 'summary_confirmed', sid, sid, {'version': body.summary_version})
        return persist(record, s)

    @app.post('/api/sessions/{sid}/handoff')
    def handoff_route(sid: str, body: S.Handoff, request: Request, db=Depends(get_db)):
        record, actor = session_access(request, db, sid)
        s = deepcopy(record.data)
        if s['status'] in {'work_order_created', 'closed'}: raise HTTPException(409, '会话已建单或关闭')
        # User free text lives in session data only, never in generic audit logs.
        return persist(record, handoff(db, s, body.reason, actor))

    @app.post('/api/sessions/{sid}/phone-events')
    def phone_event(sid: str, body: S.PhoneEvent, request: Request, db=Depends(get_db)):
        record, actor = session_access(request, db, sid)
        s = deepcopy(record.data)
        if s['channel'] != 'phone_simulator': raise HTTPException(409, '仅电话模拟会话可提交测试事件')
        editable(s)
        if body.event == 'transcript':
            if not body.content.strip(): raise HTTPException(422, '转写内容不能为空')
            add_message(db, s, body.content.strip(), actor)
        elif body.event == 'disconnect': handoff(db, s, '模拟电话断线，已保存内容待人工接续')
        elif body.event == 'asr_failure':
            s['asr_failures'] += 1
            if s['asr_failures'] >= 2: handoff(db, s, '连续语音识别失败')
            else: s['messages'].append({'role':'assistant','content':'未识别到有效内容，请重试、使用文字或转人工。'})
        elif body.event == 'interrupt':
            s['messages'].append({'role':'assistant','content':'模拟播报已打断，等待您的补充。'})
        audit(db, actor, 'phone_simulator_event', sid, sid, {'event': body.event})
        return persist(record, s)

    @app.post('/api/evidence/analyze')
    def evidence(body: S.Evidence, request: Request, db=Depends(get_db)):
        record, actor = session_access(request, db, body.session_id)
        s = deepcopy(record.data)
        editable(s)
        if PurePath(body.filename).name != body.filename or '/' in body.filename or '\\' in body.filename or not body.filename.lower().endswith('.txt'):
            raise HTTPException(415, '当前仅支持纯文本 .txt 材料，图片和 PDF 请交工作人员')
        if len(s['evidence']) >= 20: raise HTTPException(413, '单会话材料数量达到限制')
        if '\x00' in body.content or not body.content.strip():
            return persist(record, handoff(db, s, '材料无法按纯文本解析'))
        invalidate(s)
        text = body.content
        flags = risk_flags(text)
        if flags:
            s['risks'] = sorted(set(s['risks'] + flags))
            return persist(record, handoff(db, s, '材料含风险或指令性内容，请人工核对'))
        start = time.perf_counter()
        category = next((x for x in ['劳动合同','工资记录','聊天记录','转账记录','事故认定书'] if x in body.filename+text), '其他材料')
        entry, t = tool(db, s, 'evidence', 'evidence.classify', lambda: {
            'id': ident(), 'filename': body.filename, 'category': category, 'authorized': True,
            'sha256': digest(text), 'characters': len(text), 'created_at': now(),
            'extracted_fields': {'dates': re_dates(text)}, 'status': 'parsed',
            'retention': '仅保存目录与哈希，原文不落盘；请保留原始材料', 'missing_materials': ['原件及真实性需由工作人员核对'],
        })
        s['evidence'].append(entry)
        if category not in s['fields']['materials']: s['fields']['materials'].append(category)
        append_run(s, 'evidence', {'evidence_id': entry['id'], 'category': category}, [t], start)
        audit(db, actor, 'evidence_catalogued', s['id'], s['id'], {'evidence_id': entry['id'], 'sha256': entry['sha256']})
        return persist(record, s)

    @app.post('/api/knowledge/search')
    def search(body: S.Search, request: Request, db=Depends(get_db)):
        record, _ = session_access(request, db, body.session_id)
        from .services import extract_fields
        category = extract_fields(body.query)['category'] or record.data['fields']['category']
        result = lookup(db, category, body.region or record.data['fields']['location'], body.query)
        audit(db, 'knowledge', 'knowledge_searched', body.session_id, body.session_id, {'results': len(result)})
        return result

    @app.post('/api/matching/candidates')
    def match(body: S.Run, request: Request, db=Depends(get_db)):
        record, _ = session_access(request, db, body.session_id)
        s = deepcopy(record.data)
        editable(s)
        result, _ = tool(db, s, 'matching', 'personnel.filter', lambda: candidates(db, s))
        s['candidates'] = result
        if not result: handoff(db, s, '没有满足硬性条件的候选人员')
        persist(record, s)
        return result

    @app.post('/api/work-orders', status_code=201)
    def create_order(body: S.WorkOrderNew, request: Request, db=Depends(get_db)):
        who = require_role(request, db, {'admin', 'staff'})
        record = get_record(db, body.session_id, 'session')
        s = deepcopy(record.data)
        oid = 'wo-' + s['id']
        existing = db.get(Record, oid)
        if existing: return existing.data
        if s['status'] not in {'awaiting_review', 'handed_off'}:
            raise HTTPException(409, '需要本人确认摘要或先转人工并完成复核')
        if s['status'] == 'awaiting_review' and s['confirmed_version'] != s['summary_version']:
            raise HTTPException(409, '摘要确认已失效')
        people = candidates(db, s)
        if body.assignee_id and body.assignee_id not in [p['id'] for p in people]:
            raise HTTPException(409, '候选人员状态已变化或不符合条件')
        data = {'id': oid, 'session_id': s['id'], 'status': 'open', 'assignee_id': body.assignee_id,
            'summary': s['summary'] or '人工接管：' + s['handoff_reason'], 'category': s['fields']['category'],
            'priority': 'urgent' if s['risks'] else 'normal', 'review_note': body.review_note,
            'reviewer': who['username'], 'created_at': now(), 'updated_at': now(),
            'timeline': [{'action':'created','actor':who['username'],'created_at':now(),'note':body.review_note}],
            'is_demo': True, 'assignment_notice': '仅内部接续记录，不构成正式法律援助指派'}
        db.add(Record(id=oid, kind='work_order', data=data))
        s['status'], s['work_order_id'] = 'work_order_created', oid
        persist(record, s)
        audit(db, who['username'], 'work_order_created', oid, s['id'], {'summary_version': s['summary_version']})
        return data

    @app.get('/api/work-orders')
    def orders(request: Request, db=Depends(get_db)):
        require_role(request, db, {'admin', 'staff'})
        return [r.data for r in db.scalars(select(Record).where(Record.kind == 'work_order'))]

    @app.patch('/api/work-orders/{oid}')
    def order_update(oid: str, body: S.WorkOrderPatch, request: Request, db=Depends(get_db)):
        who = require_role(request, db, {'admin', 'staff'})
        record = get_record(db, oid, 'work_order')
        data = deepcopy(record.data)
        if data['status'] == 'closed': raise HTTPException(409, '已关闭工单不能重开')
        if data['status'] == 'in_progress' and body.status == 'open': raise HTTPException(409, '工单状态不能倒退')
        data['status'], data['updated_at'] = body.status, now()
        data['timeline'].append({'action': body.status, 'actor': who['username'], 'note': body.note, 'created_at': now()})
        if body.status == 'closed':
            sr = get_record(db, data['session_id'], 'session')
            sd = deepcopy(sr.data)
            sd['status'] = 'closed'
            persist(sr, sd)
        audit(db, who['username'], 'work_order_updated', oid, data['session_id'], {'status': body.status})
        return persist(record, data)

    @app.get('/api/knowledge')
    def knowledge_list(request: Request, db=Depends(get_db)):
        require_role(request, db, {'admin', 'reviewer', 'staff'})
        return [r.data for r in db.scalars(select(Record).where(Record.kind == 'knowledge'))]

    @app.post('/api/knowledge', status_code=201)
    def knowledge_new(body: S.KnowledgeNew, request: Request, db=Depends(get_db)):
        who = require_role(request, db, {'admin', 'reviewer'})
        kid = ident()
        data = {**body.model_dump(), 'id': kid, 'status': 'draft', 'is_demo': True, 'created_at': now(), 'updated_at': now(), 'reviewer': None}
        db.add(Record(id=kid, kind='knowledge', data=data))
        audit(db, who['username'], 'knowledge_drafted', kid, details={'version': body.version})
        return data

    @app.patch('/api/knowledge/{kid}')
    def knowledge_review(kid: str, body: S.KnowledgePatch, request: Request, db=Depends(get_db)):
        who = require_role(request, db, {'admin', 'reviewer'})
        record = get_record(db, kid, 'knowledge')
        data = deepcopy(record.data)
        data.update(status=body.status, review_note=body.review_note, reviewer=who['username'], updated_at=now())
        audit(db, who['username'], 'knowledge_reviewed', kid, details={'status': body.status, 'version': data['version']})
        return persist(record, data)

    @app.get('/api/personnel')
    def personnel_list(request: Request, db=Depends(get_db)):
        require_role(request, db, {'admin', 'staff'})
        return [r.data for r in db.scalars(select(Record).where(Record.kind == 'personnel'))]

    @app.post('/api/personnel', status_code=201)
    def personnel_new(body: S.PersonnelNew, request: Request, db=Depends(get_db)):
        who = require_role(request, db, {'admin'})
        pid = ident()
        data = {**body.model_dump(), 'id': pid, 'is_demo': True, 'updated_at': now()}
        db.add(Record(id=pid, kind='personnel', data=data))
        audit(db, who['username'], 'personnel_created', pid)
        return data

    @app.patch('/api/personnel/{pid}')
    def personnel_update(pid: str, body: S.PersonnelPatch, request: Request, db=Depends(get_db)):
        who = require_role(request, db, {'admin'})
        record = get_record(db, pid, 'personnel')
        data = deepcopy(record.data)
        data.update(body.model_dump(exclude_none=True), updated_at=now())
        audit(db, who['username'], 'personnel_updated', pid, details=body.model_dump(exclude_none=True))
        return persist(record, data)

    @app.get('/api/audit/events')
    def audit_events(request: Request, session_id: str | None = None, db=Depends(get_db)):
        require_role(request, db, {'admin', 'staff', 'auditor'})
        data = [r.data for r in db.scalars(select(Record).where(Record.kind == 'audit'))]
        return sorted([d for d in data if not session_id or d['session_id'] == session_id], key=lambda d:d['created_at'], reverse=True)

    @app.get('/api/metrics')
    def metrics(request: Request, db=Depends(get_db)):
        require_role(request, db, {'admin', 'staff', 'auditor'})
        sessions = [r.data for r in db.scalars(select(Record).where(Record.kind == 'session'))]
        events = [r.data for r in db.scalars(select(Record).where(Record.kind == 'audit'))]
        return {'sessions': len(sessions), 'work_orders': len(list(db.scalars(select(Record).where(Record.kind == 'work_order')))),
                'handoffs': sum(bool(s['handoff_reason']) for s in sessions), 'agent_runs': sum(len(s['runs']) for s in sessions),
                'total_cost': round(sum(r['cost'] for s in sessions for r in s['runs']), 6),
                'permission_denials': sum(e['action'] == 'permission_denied' for e in events), 'currency': 'configured_model_price_unit',
                'model_mode': os.getenv('MODEL_MODE', 'deterministic')}
    return app


def re_dates(text):
    import re
    return re.findall(r'20\d{2}[-年/]\d{1,2}(?:[-月/]\d{1,2}日?|月)?', text)[:30]


app = create_app()
