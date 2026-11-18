from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Login(Strict):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=128)

class NewSession(Strict):
    channel: Literal['text', 'voice', 'phone_simulator'] = 'text'
    consent: Literal[True]

class Message(Strict):
    content: str = Field(min_length=1, max_length=4000)
    @field_validator('content')
    @classmethod
    def nonempty(cls, value):
        if not value.strip(): raise ValueError('内容不能为空')
        return value.strip()

class Fields(Strict):
    category: Literal['劳动争议', '婚姻家庭', '交通事故', '其他', ''] | None = None
    location: str | None = Field(default=None, max_length=120)
    event_date: str | None = Field(default=None, max_length=80)
    request: str | None = Field(default=None, max_length=1000)
    materials: list[str] | None = Field(default=None, max_length=30)
    @field_validator('materials')
    @classmethod
    def short_materials(cls, value):
        if value and any(len(x) > 120 for x in value): raise ValueError('材料名称过长')
        return value

class Run(Strict):
    session_id: str = Field(max_length=64)

class OrchestrationRun(Run):
    allow_external_model: StrictBool = False

class Confirm(Strict):
    summary_version: int = Field(ge=1)

class Handoff(Strict):
    reason: str = Field(default='用户要求人工', min_length=1, max_length=300)

class PhoneEvent(Strict):
    event: Literal['consent', 'transcript', 'interrupt', 'disconnect', 'asr_failure']
    content: str = Field(default='', max_length=4000)

class Evidence(Strict):
    session_id: str = Field(max_length=64)
    filename: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=50000)
    authorized: Literal[True]

class Search(Run):
    query: str = Field(min_length=1, max_length=1000)
    region: str = Field(default='', max_length=120)

class WorkOrderNew(Run):
    assignee_id: str | None = Field(default=None, max_length=64)
    review_note: str = Field(min_length=2, max_length=1000)

class WorkOrderPatch(Strict):
    status: Literal['open', 'in_progress', 'closed']
    note: str = Field(min_length=2, max_length=1000)

class KnowledgeNew(Strict):
    title: str = Field(min_length=2, max_length=200)
    content: str = Field(min_length=10, max_length=10000)
    source_url: str = Field(min_length=5, max_length=1000)
    version: str = Field(min_length=1, max_length=80)
    locator: str = Field(min_length=1, max_length=200)
    region: str = Field(min_length=1, max_length=120)
    category: Literal['劳动争议', '婚姻家庭', '交通事故', '其他']
    @field_validator('source_url')
    @classmethod
    def safe_url(cls, value):
        if not value.startswith(('https://', 'http://')): raise ValueError('来源必须是 HTTP(S) 地址')
        return value

class KnowledgePatch(Strict):
    status: Literal['approved', 'disabled']
    review_note: str = Field(min_length=2, max_length=1000)

class PersonnelNew(Strict):
    name: str = Field(min_length=1, max_length=80)
    qualification: str = Field(min_length=1, max_length=200)
    domains: list[str] = Field(min_length=1, max_length=20)
    regions: list[str] = Field(min_length=1, max_length=20)
    available: bool = True
    active: bool = True

class PersonnelPatch(Strict):
    available: bool | None = None
    active: bool | None = None

class AgentRun(Strict):
    id: str
    agent: str
    version: str
    input_summary: dict[str, Any]
    output: dict[str, Any]
    citations: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    risks: list[str]
    next_step: str
    duration_ms: float = Field(ge=0)
    cost: float = Field(ge=0)
    status: Literal['success', 'handoff']
    created_at: str
