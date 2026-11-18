"""Deterministic demo agents. User content never changes policy or tool names."""
import hashlib
import re
import uuid
from copy import deepcopy
from time import perf_counter
from sqlalchemy import select
from .database import Record, now
from .schemas import AgentRun
from .model_gateway import ModelGateway, GatewayError

VERSION = '0.1.0'
CATEGORIES = {'劳动争议', '婚姻家庭', '交通事故', '其他'}
POLICY = {
    'supervisor': {'risk.check', 'state.read'},
    'intake': {'fields.extract'},
    'knowledge': {'knowledge.search'},
    'evidence': {'evidence.classify'},
    'matching': {'personnel.filter', 'work_order.draft'},
}


def ident(): return uuid.uuid4().hex


def audit(db, actor, action, object_id='', session_id='', details=None):
    # Details are structured metadata constructed by code, never raw request bodies.
    eid = ident()
    db.add(Record(id=eid, kind='audit', data={'id': eid, 'actor': actor, 'action': action,
        'object_id': object_id, 'session_id': session_id, 'created_at': now(), 'details': details or {}}))
    return eid


def tool(db, session, agent, name, operation):
    if name not in POLICY.get(agent, set()):
        audit(db, agent, 'permission_denied', session['id'], session['id'], {'tool': name})
        raise PermissionError('智能体工具未获授权')
    if session['status'] in {'closed', 'work_order_created', 'handed_off'}:
        raise PermissionError('当前状态禁止智能体工具调用')
    result = operation()
    aid = audit(db, agent, 'tool_called', session['id'], session['id'], {'tool': name, 'allowed': True})
    return result, {'tool': name, 'allowed': True, 'audit_id': aid}


def risk_flags(text):
    rules = [
        ('人身安全风险', r'杀人|杀了|自杀|伤害自己|生命危险|被打|家暴|殴打|持刀'),
        ('未成年人事项', r'未成年|未满18|儿童|孩子被|(?<!\d)(?:[1-9]|1[0-7])岁'),
        ('紧急期限需人工核实', r'今天.*到期|明天.*到期|马上开庭|紧急|最后一天|即将到期'),
        ('群体性事项', r'集体上访|群体性|几十名|数十人|一百人'),
        ('提示注入或越权要求', r'忽略.{0,12}(规则|指令)|绕过.{0,10}(审核|权限)|system\s*prompt|system:|自动审批|直接批准|泄露.{0,5}密钥'),
    ]
    return [label for label, pattern in rules if re.search(pattern, text, re.I)]


def handoff(db, s, reason, actor='supervisor'):
    if s['status'] == 'handed_off': return s
    s['status'] = 'handed_off'
    s['handoff_reason'] = reason
    s['confirmed_version'] = None
    s['messages'].append({'role': 'assistant', 'content': '已保存当前信息并转入人工队列。' + reason})
    audit(db, actor, 'session_handed_off', s['id'], s['id'], {'reason_code': 'manual_review'})
    return s


def invalidate(s):
    s['status'] = 'collecting'
    s['confirmed_version'] = None
    s['summary'] = ''
    s['citations'] = []
    s['candidates'] = []



def explicit_conflicts(fields, text):
    patterns = {'location': r'(?:地点|发生地点)[:：]\s*([^，。；;\n]{2,120})',
                'event_date': r'(?:时间|发生时间)[:：]\s*([^，。；;\n]{2,80})',
                'category': r'(?:事项|事项类型)[:：]\s*([^，。；;\n]{2,40})'}
    conflicts = []
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match and fields.get(key) and fields[key].strip() != match.group(1).strip():
            conflicts.append({'field': key, 'previous': fields[key], 'reported': match.group(1).strip()})
    # Explicit correction language is not ordinary field supplementation. Never
    # silently retain the first historical extraction when the user retracts it.
    correction = re.search(r'更正|纠正|之前说错|刚才说错|说得不对|不对[，,。；]|实际上|其实', text)
    if correction and any(fields.get(key) for key in ('location', 'event_date', 'category')):
        reported = extract_fields(text)
        already = {item['field'] for item in conflicts}
        for key in ('location', 'event_date', 'category'):
            if key not in already and fields.get(key) and reported.get(key) and fields[key].strip() != reported[key].strip():
                conflicts.append({'field': key, 'previous': fields[key], 'reported': reported[key]})
        if not conflicts:
            # A retraction can be meaningful even when the deterministic parser
            # cannot identify its replacement value; preserve it for staff.
            conflicts.append({'field': 'pending_correction', 'previous': '已有登记信息待重新核实', 'reported': text})
    return conflicts


def extract_fields(text):
    category = ''
    for label, pattern in [('劳动争议', r'工资|劳动|欠薪|公司|辞退|工伤|加班'), ('婚姻家庭', r'离婚|抚养|婚姻|赡养|夫妻'), ('交通事故', r'交通事故|车祸|撞车|交通|追尾')]:
        if re.search(pattern, text):
            category = label
            break
    location = ''
    match = re.search(r'(?:地点[:：]?|发生在|我在|位于)\s*([^，。；\s]{2,20})', text)
    if match: location = match.group(1)
    else:
        match = re.search(r'(烟台|青岛|济南|北京|上海|深圳|广州|南京|杭州|成都)(?:市)?', text)
        if match: location = match.group(0)
    date = re.search(r'20\d{2}[-年/]\d{1,2}(?:[-月/]\d{1,2}日?|月)?|今年\d{1,2}月|上个月|昨天|今天|去年', text)
    request = re.search(r'(?:希望|诉求[:：]?|想要|想咨询)\s*(.{2,300})', text)
    materials = [word for word in ['劳动合同', '工资记录', '聊天记录', '身份证明', '事故认定书', '结婚证', '转账记录'] if word in text]
    return {'category': category, 'location': location, 'event_date': date.group(0) if date else '',
            'request': request.group(1) if request else '', 'materials': materials}


def lookup(db, category, region, query=''):
    found = []
    for record in db.scalars(select(Record).where(Record.kind == 'knowledge')):
        k = record.data
        if k['status'] != 'approved': continue
        if k['category'] != category: continue
        if k['region'] != '全国' and k['region'] not in region: continue
        if not all(k.get(x) for x in ['source_url', 'version', 'locator']): continue
        found.append({key: k[key] for key in ['id', 'title', 'source_url', 'version', 'locator', 'region', 'updated_at', 'content', 'is_demo'] if key in k})
    return found


def candidates(db, s):
    found = []
    for record in db.scalars(select(Record).where(Record.kind == 'personnel')):
        p = record.data
        if not (p['active'] and p['available'] and p['qualification']): continue
        if s['fields']['category'] not in p['domains']: continue
        if not any(r == '全国' or r in s['fields']['location'] for r in p['regions']): continue
        found.append({**p, 'match_reason': '领域、服务地区、资格字段和可用排班满足模拟筛选规则；仍需人工核查利益冲突。'})
    return found


def append_run(s, agent, output, tools, start, citations=None, cost=0):
    run = AgentRun(id=ident(), agent=agent, version=VERSION,
        input_summary={'field_names': sorted(k for k, v in s['fields'].items() if v), 'message_count': len(s['messages'])},
        output=output, citations=citations or [], tools=tools, risks=list(s['risks']),
        next_step=s['status'], duration_ms=round((perf_counter()-start)*1000, 3), cost=cost,
        status='handoff' if s['status'] == 'handed_off' else 'success', created_at=now()).model_dump()
    s['runs'].append(run)


def orchestrate(db, s, max_steps=40, max_cost=1.0):
    start = perf_counter()
    if len(s['runs']) + 4 > max_steps or sum(r['cost'] for r in s['runs']) >= max_cost:
        return handoff(db, s, '调用次数或费用达到限制')
    text = '\n'.join(m['content'] for m in s['messages'] if m['role'] == 'user')
    flags, t = tool(db, s, 'supervisor', 'risk.check', lambda: risk_flags(text + ' '.join(str(v) for v in s['fields'].values())))
    s['risks'] = sorted(set(s['risks'] + flags))
    if flags or re.search(r'转人工|找人工|人工服务', text):
        handoff(db, s, '；'.join(flags) or '用户要求人工')
        append_run(s, 'supervisor', {'decision': 'handoff'}, [t], start)
        return s
    append_run(s, 'supervisor', {'decision': 'continue'}, [t], start)
    extracted, t = tool(db, s, 'intake', 'fields.extract', lambda: extract_fields(text))
    cost = 0
    try:
        gateway = ModelGateway.from_env()
        if gateway and text:
            result = gateway.extract(text, remaining_budget=max_cost-sum(r['cost'] for r in s['runs']), allowed_categories=CATEGORIES)
            extracted = {key: extracted.get(key) or value for key, value in result.fields.items()}
            cost = result.cost
            t['model'] = result.model
            t['attempts'] = result.attempts
            t['cost'] = cost
    except (GatewayError, ValueError):
        handoff(db, s, '模型不可用或输出未通过校验，请工作人员接续')
        append_run(s, 'intake', {'decision': 'handoff'}, [t], start)
        return s
    for key, value in extracted.items():
        if value and not s['fields'].get(key): s['fields'][key] = value
    missing = [key for key in ['category', 'location', 'event_date', 'request'] if not s['fields'].get(key)]
    append_run(s, 'intake', {'fields': deepcopy(s['fields']), 'missing': missing}, [t], start, cost=cost)
    if missing:
        s['clarification_count'] += 1
        if s['clarification_count'] > 2:
            return handoff(db, s, '连续补问仍缺少必要信息')
        labels = {'category': '事项类型', 'location': '发生地点', 'event_date': '发生时间', 'request': '希望解决的问题'}
        s['messages'].append({'role': 'assistant', 'content': '请补充：' + '、'.join(labels[k] for k in missing) + '。也可以在信息确认区填写。'})
        return s
    citations, t = tool(db, s, 'knowledge', 'knowledge.search', lambda: lookup(db, s['fields']['category'], s['fields']['location']))
    s['citations'] = citations
    if not citations:
        handoff(db, s, '未找到经过审核且适用的知识来源，停止自动答复')
        append_run(s, 'knowledge', {'found': 0}, [t], start)
        return s
    if len({c['content'] for c in citations}) > 1:
        handoff(db, s, '检索到不同内容的适用来源，需人工核实来源冲突')
        append_run(s, 'knowledge', {'found': len(citations), 'conflict': True}, [t], start, citations)
        return s
    append_run(s, 'knowledge', {'found': len(citations), 'answer': citations[0]['content']}, [t], start, citations)
    people, t = tool(db, s, 'matching', 'personnel.filter', lambda: candidates(db, s))
    s['candidates'] = people
    if not people:
        handoff(db, s, '没有满足硬性条件的候选人员')
        append_run(s, 'matching', {'candidate_ids': []}, [t], start)
        return s
    append_run(s, 'matching', {'candidate_ids': [p['id'] for p in people], 'draft_only': True}, [t], start)
    f = s['fields']
    s['summary'] = f"事项：{f['category']}；地点：{f['location']}；时间：{f['event_date']}；诉求：{f['request']}；已有材料：{'、'.join(f['materials']) or '暂未提供'}。本摘要待本人确认及工作人员审核。"
    s['summary_version'] += 1
    s['confirmed_version'] = None
    s['status'] = 'awaiting_confirmation'
    s['messages'].append({'role': 'assistant', 'content': '已整理咨询摘要，请核对并确认。' + citations[0]['content']})
    audit(db, 'orchestrator', 'summary_created', s['id'], s['id'], {'version': s['summary_version']})
    return s
