#!/usr/bin/env python3
"""Exercise consent, authorization, confirmation, human review, and closure."""
import argparse
import json
from api_client import API


def run(api: API) -> dict:
    api.request('POST', '/sessions', {'channel': 'text', 'consent': False}, expect=[400, 422])
    session = api.request('POST', '/sessions', {'channel': 'text', 'consent': True})
    sid, token = session['id'], session['session_token']
    api.request('GET', f'/sessions/{sid}', expect=[401, 403, 404])
    other = api.request('POST', '/sessions', {'channel': 'text', 'consent': True})
    api.request('GET', f'/sessions/{sid}', session_token=other['session_token'], expect=[401, 403, 404])
    api.request('POST', f'/sessions/{sid}/messages', {'content': '模拟咨询：我在烟台市遇到拖欠工资，希望了解申请材料。'}, session_token=token)
    api.request('PATCH', f'/sessions/{sid}/fields', {'category': '劳动争议', 'location': '烟台市', 'event_date': '2026-10-01', 'request': '了解劳动争议援助申请材料', 'materials': ['工资记录']}, session_token=token)
    session = api.request('POST', '/orchestrator/run', {'session_id': sid}, session_token=token)
    assert session['status'] == 'awaiting_confirmation', session
    old_version = session['summary_version']
    api.request('PATCH', f'/sessions/{sid}/fields', {'request': '了解工资记录与合同如何整理'}, session_token=token)
    session = api.request('POST', '/orchestrator/run', {'session_id': sid}, session_token=token)
    assert session['summary_version'] > old_version, 'Summary mutation did not change version'
    assert session['citations'] and session['runs'], 'Missing trace or source'
    for citation in session['citations']:
        assert all(citation.get(k) for k in ['title', 'source_url', 'version', 'locator']), citation
    api.request('POST', '/work-orders', {'session_id': sid, 'review_note': '不允许群众自行建单'}, session_token=token, expect=[401, 403])
    staff = api.login()
    api.request('POST', '/work-orders', {'session_id': sid, 'review_note': '尚未本人确认'}, bearer=staff, expect=[400, 409, 422])
    api.request('POST', f'/sessions/{sid}/confirm', {'summary_version': old_version}, session_token=token, expect=[400, 409, 422])
    confirmed = api.request('POST', f'/sessions/{sid}/confirm', {'summary_version': session['summary_version']}, session_token=token)
    assert confirmed['status'] == 'awaiting_review', confirmed
    order = api.request('POST', '/work-orders', {'session_id': sid, 'review_note': '模拟工作人员核对摘要、材料及业务边界，登记人工待办。'}, bearer=staff)
    assert order['id']
    duplicate = api.request('POST', '/work-orders', {'session_id': sid, 'review_note': '重复请求检查'}, bearer=staff, expect=[200, 201, 409])
    if isinstance(duplicate, dict) and 'id' in duplicate:
        assert duplicate['id'] == order['id'], 'Duplicate work order was created'
    api.request('PATCH', f"/work-orders/{order['id']}", {'status': 'in_progress', 'note': '模拟人工受理登记'}, bearer=staff)
    api.request('PATCH', f"/work-orders/{order['id']}", {'status': 'closed', 'note': '模拟工单结束'}, bearer=staff)
    closed = api.request('GET', f'/sessions/{sid}', session_token=token)
    assert closed['status'] == 'closed', closed
    auditor = api.login('auditor')
    api.request('GET', '/audit/events', bearer=auditor)
    api.request('GET', '/metrics', bearer=auditor)
    api.request('POST', '/work-orders', {'session_id': other['id'], 'review_note': '只读角色不得建单'}, bearer=auditor, expect=[401, 403])
    return {'result': 'passed', 'scope': 'HTTP prototype workflow, synthetic data only', 'session_id': sid, 'work_order_id': order['id']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000/api')
    parser.add_argument('--wait', action='store_true')
    args = parser.parse_args()
    api = API(args.base_url)
    api.ready(30 if args.wait else 1)
    print(json.dumps(run(api), ensure_ascii=False, indent=2))
