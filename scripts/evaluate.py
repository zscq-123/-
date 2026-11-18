#!/usr/bin/env python3
"""Report synthetic template extraction and HTTP handoff regressions honestly."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from api_client import API

ROOT = Path(__file__).resolve().parents[1]


def matches(field, actual, expected):
    if field == 'request':
        # Exact known label must survive; punctuation/prefix may differ.
        return expected in str(actual)
    return actual == expected


def run(api: API) -> dict:
    fixture = ROOT / 'tests/fixtures/intake-synthetic-v1.json'
    cases = json.loads(fixture.read_text())
    results = []
    for case in cases:
        try:
            session = api.request('POST', '/sessions', {'channel': 'text', 'consent': True})
            token, sid = session['session_token'], session['id']
            api.request('POST', f'/sessions/{sid}/messages', {'content': case['content']}, session_token=token)
            session = api.request('POST', '/orchestrator/run', {'session_id': sid}, session_token=token)
            fields = session.get('fields', {})
            checks = {key: matches(key, fields.get(key), expected) for key, expected in case['expected_fields'].items()}
            citations = session.get('citations', [])
            located = bool(citations) and all(all(c.get(k) for k in ['title', 'source_url', 'version', 'locator']) for c in citations)
            results.append({'id': case['id'], 'fields': fields, 'field_checks': checks, 'route_correct': session['status'] == case['expected_status'], 'citation_metadata_complete': located, 'status': session['status']})
        except Exception as exc:
            results.append({'id': case['id'], 'error': str(exc), 'field_checks': {key: False for key in case['expected_fields']}, 'route_correct': False, 'citation_metadata_complete': False})
    handoffs = []
    for i in range(50):
        try:
            session = api.request('POST', '/sessions', {'channel': 'text', 'consent': True})
            session = api.request('POST', f"/sessions/{session['id']}/handoff", {'reason': '模拟用户主动要求人工'}, session_token=session['session_token'])
            handoffs.append({'id': f'handoff-{i+1:02d}', 'passed': session['status'] == 'handed_off'})
        except Exception as exc:
            handoffs.append({'id': f'handoff-{i+1:02d}', 'passed': False, 'error': str(exc)})
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = 'unknown', True
    field_pass = sum(sum(row['field_checks'].values()) for row in results)
    total_fields = sum(len(row['field_checks']) for row in results)
    return {
        'evaluated_at_utc': datetime.now(timezone.utc).isoformat(),
        'code_commit': commit,
        'working_tree_has_changes': dirty,
        'dataset': fixture.name,
        'dataset_sha256': hashlib.sha256(fixture.read_bytes()).hexdigest(),
        'scope': '100 条固定模板虚构样本、400 项字段标签和 50 次 HTTP 状态转换；非独立业务准确率、真实电话接管或用户研究。引用仅校验模拟来源元数据齐备，不证明外部链接可达或法律正确。',
        'summary': {
            'records': len(results), 'fields_correct': field_pass, 'fields_total': total_fields,
            'field_match_rate': field_pass / total_fields,
            'route_correct': sum(row['route_correct'] for row in results),
            'citation_metadata_complete': sum(row['citation_metadata_complete'] for row in results),
            'http_handoff_passed': sum(row['passed'] for row in handoffs),
            'http_handoff_total': len(handoffs),
            'request_errors': sum('error' in row for row in results + handoffs),
        },
        'cases': results,
        'handoffs': handoffs,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000/api')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/local/evaluation.json')
    args = parser.parse_args()
    api = API(args.base_url)
    api.ready(3)
    report = run(api)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'summary': report['summary'], 'report': str(args.output), 'scope': report['scope']}, ensure_ascii=False, indent=2))
    summary = report['summary']
    # A reproducible software gate for this template set only.
    if summary['request_errors'] or summary['field_match_rate'] < 0.9 or summary['route_correct'] != summary['records'] or summary['citation_metadata_complete'] != summary['records'] or summary['http_handoff_passed'] != 50:
        raise SystemExit(1)
