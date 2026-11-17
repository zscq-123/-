from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, String, JSON, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

class Base(DeclarativeBase):
    pass

class Record(Base):
    __tablename__ = 'records'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    data: Mapped[dict] = mapped_column(JSON)
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


def now():
    return datetime.now(timezone.utc).isoformat()


def database(url):
    if url.startswith('sqlite:///') and ':memory:' not in url:
        Path(url.removeprefix('sqlite:///')).parent.mkdir(parents=True, exist_ok=True)
    options = {'check_same_thread': False, 'timeout': 30} if url.startswith('sqlite') else {}
    kwargs = {}
    if ':memory:' in url:
        from sqlalchemy.pool import StaticPool
        kwargs['poolclass'] = StaticPool
    engine = create_engine(url, connect_args=options, **kwargs)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)


def seed(db):
    if db.scalar(select(Record).where(Record.kind == 'knowledge').limit(1)):
        return
    for i, category in enumerate(['劳动争议', '婚姻家庭', '交通事故']):
        kid = f'demo-knowledge-{i+1}'
        db.add(Record(id=kid, kind='knowledge', data={
            'id': kid, 'title': f'模拟{category}接待流程', 'category': category,
            'content': '【仅供模拟演示】请先登记事项经过、发生地点和时间、希望解决的问题及现有材料。工作人员核对完整性后说明后续流程。此样本不包含法律援助资格条件，不作为真实办理依据。',
            'source_url': f'https://example.invalid/demo/guide/{i+1}', 'version': 'demo-2026.11-v1',
            'locator': '模拟流程样本 第1段', 'region': '全国', 'status': 'approved',
            'is_demo': True, 'reviewer': 'demo-seed', 'review_note': '技术测试样本，不代表真实业务审核',
            'updated_at': now(), 'created_at': now(),
        }))
        pid = f'demo-person-{i+1}'
        db.add(Record(id=pid, kind='personnel', data={
            'id': pid, 'name': ['模拟工作人员甲', '模拟工作人员乙', '模拟工作人员丙'][i],
            'qualification': '模拟资格（未核验，不可用于正式指派）', 'domains': [category],
            'regions': ['全国'], 'active': True, 'available': True, 'is_demo': True, 'updated_at': now(),
        }))
    db.commit()
