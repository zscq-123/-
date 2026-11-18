#!/usr/bin/env python3
"""Recreate versioned synthetic template fixtures; these are not an expert benchmark."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
templates = [
    ('劳动争议', '单位拖欠工资', '了解工资记录如何整理'),
    ('劳动争议', '遇到劳动合同争议', '了解劳动合同材料准备流程'),
    ('婚姻家庭', '遇到离婚纠纷', '了解婚姻家庭接待流程'),
    ('交通事故', '发生交通事故', '了解交通事故材料登记流程'),
]
locations = ['烟台市', '青岛市', '济南市', '北京市', '上海市']
cases = []
for i in range(100):
    category, facts, request = templates[i % len(templates)]
    location = locations[(i // 4) % len(locations)]
    event_date = f'2026-10-{i % 28 + 1:02d}'
    cases.append({
        'id': f'synthetic-{i+1:03d}',
        'provenance': '确定性模板生成的虚构记录，未由法律专业人员标注',
        'content': f'我在{location}，{event_date}{facts}，希望{request}。',
        'expected_fields': {'category': category, 'location': location, 'event_date': event_date, 'request': request},
        'expected_status': 'awaiting_confirmation',
    })
path = root / 'tests/fixtures/intake-synthetic-v1.json'
path.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
print(f'Wrote {len(cases)} synthetic cases to {path}')
