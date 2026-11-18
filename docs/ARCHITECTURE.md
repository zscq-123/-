# 架构与接口约定

## 运行与权限

群众触屏以 `/` 为入口，工作人员工作台和接待、电话联调位于 `/staff`。两端均通过 Next.js `/api/backend/*` 服务端代理访问 FastAPI `/api/*`。后端端口 8000，前端 3000。代理读 `BACKEND_URL`，不注入管理员身份。SQLAlchemy 默认本地 SQLite，支持 `DATABASE_URL`。

创建会话返回随机 `session_token`，群众后续发送 `X-Session-Token`。触屏只在页面内存中保留凭证和草稿。返回首页、完成后 30 秒或 3 分钟无操作时，清除本屏状态。后台 `/api/auth/login` 返回令牌，使用 `Authorization: Bearer ...`。角色由服务端账号确定。演示账号只用于本地。

## 状态机

`collecting → awaiting_confirmation → awaiting_review → work_order_created → closed`

活动阶段可进入 `handed_off`。用户确认摘要后才能建常规工单；人工接管建单需工作人员复核。已关闭及已建单禁止继续编排。字段修改使旧确认失效。高风险、无来源、无候选、超限、解析失败进入人工队列。

## 数据结构

Session: `id,channel(text|voice|phone_simulator),status,consent,created_at,messages[{role,content}],fields{category,location,event_date,request,materials},summary,summary_version,confirmed_version,citations[],evidence[],candidates[],runs[],risks[],handoff_reason,work_order_id`。

Citation: `id,title,source_url,version,locator,region,updated_at,content`。
AgentRun: `id,agent,version,input_summary,output,citations,tools,risks,next_step,duration_ms,cost,status,created_at`。
所有智能体输出经过 Pydantic 校验；知识与名录种子均为模拟样本。

## HTTP 契约

下列路径均以 `/api` 为前缀，错误使用 `detail` 字段。除登录、创建和健康检查外均需会话或后台鉴权。

| 方法路径 | 请求 | 返回 |
| --- | --- | --- |
| GET /health | 无 | status,mode,version |
| POST /auth/login | username,password | access_token,role,username |
| POST /sessions | channel,consent:true | Session + session_token |
| GET /sessions | 后台，可选 status | Session[] |
| GET /sessions/{id} | 授权头 | Session |
| POST /sessions/{id}/messages | content | Session |
| POST /sessions/{id}/transcribe | 音频请求体，最多 2 MiB，需当前会话令牌 | 可编辑的转写草稿 text |
| PATCH /sessions/{id}/fields | category,location,event_date,request,materials 可选 | Session |
| POST /orchestrator/run | session_id，allow_external_model（可选，默认 false，仅群众会话令牌可设为 true） | Session |
| POST /sessions/{id}/confirm | summary_version | Session |
| POST /sessions/{id}/handoff | reason | Session |
| POST /sessions/{id}/phone-events | event: consent,transcript,interrupt,disconnect,asr_failure；content 可选 | Session |
| POST /evidence/analyze | session_id,filename,content,authorized:true（仅文本） | Session |
| POST /matching/candidates | session_id | candidates[] |
| POST /work-orders | session_id,assignee_id 可选,review_note | WorkOrder |
| GET /work-orders | 后台 | WorkOrder[] |
| PATCH /work-orders/{id} | status: open,in_progress,closed；note | WorkOrder |
| GET /knowledge | 后台 | Knowledge[] |
| POST /knowledge | title,content,source_url,version,locator,region,category | Knowledge（draft） |
| PATCH /knowledge/{id} | status: approved,disabled；review_note | Knowledge |
| POST /knowledge/search | session_id,query,region 可选 | Citation[] |
| GET /personnel | 后台 | Personnel[] |
| POST /personnel | name,qualification,domains[],regions[],available,active | Personnel |
| PATCH /personnel/{id} | available,active 可选 | Personnel |
| GET /audit/events | 后台，可选 session_id | AuditEvent[] |
| GET /metrics | 后台 | sessions,work_orders,handoffs,agent_runs,total_cost,permission_denials |

staff 审核建单和咨询；reviewer 审核知识；admin 维护名录及以上操作；auditor 只读脱敏审计与指标。变更写审计，正文与身份数据不进入审计详情。

## 验收边界

规则、智能体、知识来源随代码版本。真实知识审核、电话双向音频、人工接管及用户研究不能以自动化测试替代。生产需独立认证、TLS、机构隔离、对象存储、录音策略与保留审批。

## 现场端视觉资源

首页采用法治红，铜色天平主图使用内置 ImageGen 制作，资源位于 `apps/web/public/justice-scales.webp`。最终编辑提示词：保留右侧平衡的铜制天平和左侧留白，将深蓝场景改为深朱红漆面与深红石材，桌面为低饱和暖灰，保留自然光与超宽构图，不添加文字、旗帜或机构标识。
