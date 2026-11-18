'use client';

import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowLeft, ArrowRight, BriefcaseBusiness, Car, Check, CircleHelp, ClipboardList, Headphones, HeartHandshake, Home, Mic, Scale, ShieldCheck, Square } from 'lucide-react';
import { api } from '@/lib/api';
import { speechStatus, useSpeechInput } from '@/lib/use-speech-input';
import type { Fields, Session } from '@/lib/types';
import styles from './kiosk.module.css';

type Step = 'home' | 'consent' | 'details' | 'review' | 'done' | 'exit';
type Route = 'self' | 'help';
type SessionAccess = { id: string; token: string };
const emptyFields: Fields = { category: '', location: '', event_date: '', request: '', materials: [] };
const categories = [
  { value: '劳动争议', hint: '工资、辞退、工伤', icon: BriefcaseBusiness },
  { value: '婚姻家庭', hint: '离婚、抚养、赡养', icon: HeartHandshake },
  { value: '交通事故', hint: '事故、赔偿', icon: Car },
  { value: '其他', label: '其他或不确定', hint: '交由工作人员核实', icon: CircleHelp },
];
const options = {
  location: ['本市', '外地', '还不确定'],
  event_date: ['今天', '近一周', '近一个月', '更早', '记不清'],
  request: ['了解可获得的帮助', '了解需要准备的材料', '请工作人员协助'],
};
const reviewRows = [
  ['category', '咨询事项'], ['location', '发生地点'], ['event_date', '发生时间'], ['request', '希望获得的帮助'],
] as const;
const idleMs = 180_000;
const doneMs = 30_000;

export default function Kiosk() {
  const [step, setStep] = useState<Step>('home');
  const [previousStep, setPreviousStep] = useState<Step>('home');
  const [route, setRoute] = useState<Route>('self');
  const [fields, setFields] = useState<Fields>(emptyFields);
  const [session, setSession] = useState<Session | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [voiceConsent, setVoiceConsent] = useState(false);
  const [modelProvider, setModelProvider] = useState<string | null>(null);
  const [modelConsent, setModelConsent] = useState(false);
  const { phase: voicePhase, error: voiceError, start: startSpeech, stop: stopSpeech, cancel: stopVoice } = useSpeechInput();
  const voiceActive = voicePhase !== 'idle';
  const [speechText, setSpeechText] = useState('');
  const [usedVoice, setUsedVoice] = useState(false);
  const access = useRef<SessionAccess | null>(null);
  const running = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);

  const reset = useCallback(() => {
    stopVoice();
    access.current = null;
    setStep('home');
    setPreviousStep('home');
    setRoute('self');
    setSession(null);
    setFields(emptyFields);
    setVoiceOpen(false);
    setVoiceConsent(false);
    setModelConsent(false);
    setSpeechText('');
    setUsedVoice(false);
    setError('');
  }, [stopVoice]);

  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }, [step]);

  useEffect(() => {
    if (step === 'home' || busy) return;
    if (step === 'done') {
      const timer = window.setTimeout(reset, doneMs);
      return () => window.clearTimeout(timer);
    }
    let timer: number;
    const schedule = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(reset, idleMs);
    };
    schedule();
    window.addEventListener('pointerdown', schedule);
    window.addEventListener('keydown', schedule);
    window.addEventListener('input', schedule);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener('pointerdown', schedule);
      window.removeEventListener('keydown', schedule);
      window.removeEventListener('input', schedule);
    };
  }, [step, busy, reset]);

  useEffect(() => {
    void api<{ model_provider?: string | null }>('/health')
      .then(health => setModelProvider(health.model_provider ?? null))
      .catch(() => setModelProvider(null));
  }, []);

  async function perform(task: () => Promise<void>) {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError('');
    try {
      await task();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '暂时无法提交，请前往人工服务台。');
    } finally {
      running.current = false;
      setBusy(false);
    }
  }

  async function getAccess(): Promise<SessionAccess> {
    if (access.current) return access.current;
    const created = await api<Session>('/sessions', {
      method: 'POST', body: { channel: usedVoice ? 'voice' : 'text', consent: true },
    });
    if (!created.session_token) throw new Error('接待服务暂不可用，请前往人工服务台。');
    access.current = { id: created.id, token: created.session_token };
    return access.current;
  }

  async function run(id: string, token: string, allowExternalModel = false) {
    return api<Session>('/orchestrator/run', {
      method: 'POST', body: { session_id: id, allow_external_model: allowExternalModel }, sessionToken: token,
    });
  }

  function finish(result: Session) {
    stopVoice();
    setSpeechText('');
    setFields(emptyFields);
    setSession(result);
    access.current = null;
    setStep('done');
  }

  async function requestHelp() {
    stopVoice();
    await perform(async () => {
      const { id, token } = await getAccess();
      if (step === 'details' && reviewRows.some(([key]) => fields[key])) {
        const saved = await api<Session>(`/sessions/${id}/fields`, {
          method: 'PATCH', body: fields, sessionToken: token,
        });
        if (saved.status === 'handed_off') {
          finish(saved);
          return;
        }
      }
      const result = await api<Session>(`/sessions/${id}/handoff`, {
        method: 'POST', body: { reason: '现场触屏用户请求工作人员协助' }, sessionToken: token,
      });
      finish(result);
    });
  }

  async function prepareReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (voiceActive || !complete || speechText.trim()) return;
    stopVoice();
    await perform(async () => {
      const { id, token } = await getAccess();
      const saved = await api<Session>(`/sessions/${id}/fields`, {
        method: 'PATCH', body: fields, sessionToken: token,
      });
      const result = saved.status === 'collecting' ? await run(id, token) : saved;
      if (result.status === 'handed_off') {
        finish(result);
      } else if (result.status === 'awaiting_confirmation') {
        setSession(result);
        setFields(result.fields);
        setStep('review');
      } else {
        setError('还有信息需要补充。请检查选项，或请工作人员帮助。');
      }
    });
  }

  async function confirm() {
    if (!session || !access.current) return;
    const { id, token } = access.current;
    await perform(async () => {
      try {
        const result = await api<Session>(`/sessions/${id}/confirm`, {
          method: 'POST', body: { summary_version: session.summary_version }, sessionToken: token,
        });
        finish(result);
      } catch (cause) {
        // If the request completed but its response was lost, show the saved result.
        const latest = await api<Session>(`/sessions/${id}`, { sessionToken: token }).catch(() => null);
        if (latest && ['awaiting_review', 'handed_off', 'work_order_created', 'closed'].includes(latest.status)) {
          finish(latest);
          return;
        }
        throw cause;
      }
    });
  }

  function startVoice() {
    if (!voiceConsent) return;
    startSpeech(text => {
      setUsedVoice(true);
      setSpeechText(previous => `${previous}${text}`.slice(0, 4000));
    });
  }

  function applySpeech() {
    const content = speechText.trim();
    if (!content || voiceActive) return;
    stopVoice();
    void perform(async () => {
      const { id, token } = await getAccess();
      const saved = await api<Session>(`/sessions/${id}/messages`, {
        method: 'POST', body: { content }, sessionToken: token,
      });
      setSpeechText('');
      setVoiceOpen(false);
      setModelConsent(false);
      const result = saved.status === 'collecting' ? await run(id, token, !!modelProvider && modelConsent) : saved;
      if (result.status === 'handed_off') {
        finish(result);
        return;
      }
      setFields(old => ({
        category: result.fields.category || old.category,
        location: result.fields.location || old.location,
        event_date: result.fields.event_date || old.event_date,
        request: result.fields.request || old.request,
        materials: result.fields.materials.length ? result.fields.materials : old.materials,
      }));
    });
  }

  function openConsent(target: Route) {
    setError('');
    setRoute(target);
    setStep('consent');
  }

  function leave() {
    if (step === 'consent' || step === 'done') return reset();
    stopVoice();
    setPreviousStep(step);
    setStep('exit');
    setError('');
  }

  const complete = reviewRows.every(([key]) => fields[key].trim());
  const handedOff = session?.status === 'handed_off';
  const title = {
    home: '法律援助现场接待',
    consent: '开始前，请了解',
    details: '请选择咨询信息',
    review: '请核对您的信息',
    done: handedOff ? '已登记人工协助' : '咨询登记已提交',
    exit: '结束本次操作？',
  }[step];

  return (
    <div className={styles.kiosk}>
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <div className={styles.brand}>
            <span className={styles.brandIcon}><Scale size={25} aria-hidden /></span>
            <div><strong>法律援助中心</strong><span>现场自助接待</span></div>
          </div>
          {step === 'home'
            ? <span className={styles.environment}>模拟演示</span>
            : step !== 'exit' && <button className={styles.homeButton} onClick={leave} disabled={busy}><Home size={20} aria-hidden />返回首页</button>}
        </div>
      </header>
      <main className={`${styles.main} ${step === 'home' ? styles.home : ''}`} aria-busy={busy}>
        <div className={`${styles.heading} ${step === 'home' ? styles.hero : ''}`}>
          {(step === 'details' || step === 'review') && <p className={styles.progress}>第 {step === 'details' ? '1' : '2'} 步，共 2 步</p>}
          {step === 'done' && <span className={styles.doneIcon}><Check size={34} aria-hidden /></span>}
          <h1 ref={heading} tabIndex={-1}>{title}</h1>
          {step === 'home' && <p>请选择您需要的服务。</p>}
          {step === 'details' && <p>点选最符合您情况的选项。选错了可以重选。</p>}
          {step === 'review' && <p>请确认这几项信息，工作人员会继续处理。</p>}
        </div>
        {error && <div className={styles.error} role="alert"><CircleHelp size={22} aria-hidden /><div>{error}<p>如需现场帮助，请前往人工服务台。</p></div></div>}
        {busy && <p role="status" className={styles.busy}>正在处理，请稍候…</p>}

        {step === 'home' && <div className={styles.services}>
          <button className={`${styles.service} ${styles.servicePrimary}`} onClick={() => openConsent('self')}>
            <span className={styles.serviceIcon}><ClipboardList size={32} aria-hidden /></span>
            <span className={styles.serviceCaption}><strong>开始咨询</strong><span>点选登记，提交给工作人员审核</span></span>
            <ArrowRight size={29} aria-hidden />
          </button>
          <button className={styles.service} onClick={() => openConsent('help')}>
            <span className={styles.serviceIcon}><Headphones size={32} aria-hidden /></span>
            <span className={styles.serviceCaption}><strong>请工作人员帮助</strong><span>直接登记人工协助</span></span>
            <ArrowRight size={25} aria-hidden />
          </button>
        </div>}

        {step === 'consent' && <section className={`${styles.panel} ${styles.narrow}`} aria-label="接待须知">
          <div className={styles.notice}>
            <ShieldCheck size={30} aria-hidden />
            <div>
              <p>这是模拟演示，请勿输入真实姓名、证件号、电话或案卷。</p>
              <p>同意后，您提交的信息将保存为演示记录，由工作人员接续。</p>
              <p>您可以直接前往人工服务台。</p>
            </div>
          </div>
          <div className={styles.actions}>
            <button className={styles.secondary} onClick={reset} disabled={busy}><ArrowLeft size={21} aria-hidden />返回</button>
            <button className={styles.primary} disabled={busy} onClick={() => route === 'help' ? void requestHelp() : setStep('details')}>
              {route === 'help' ? '同意并登记人工协助' : '同意并继续'}<ArrowRight size={21} aria-hidden />
            </button>
          </div>
        </section>}

        {step === 'details' && <form className={`${styles.panel} ${styles.details}`} onSubmit={prepareReview}>
          <div className={styles.voiceTools}>
            <button type="button" className={styles.secondary} aria-expanded={voiceOpen} disabled={busy} onClick={() => { stopVoice(); setVoiceOpen(open => !open); }}>
              <Mic size={21} aria-hidden />{voiceOpen ? '收起语音或文字说明' : speechText.trim() ? '查看待整理的说明' : '语音或文字说明（可选）'}
            </button>
            {voiceOpen && <div className={styles.voicePanel}>
              <label className={styles.consentCheck}>
                <input type="checkbox" checked={voiceConsent} disabled={busy} onChange={event => { setVoiceConsent(event.target.checked); if (!event.target.checked) stopVoice(); }} />
                <span>我同意使用浏览器语音服务。识别可能由浏览器服务商处理。</span>
              </label>
              <button type="button" className={styles.secondary} disabled={busy || !voiceConsent || voicePhase === 'processing'} onClick={voiceActive ? stopSpeech : startVoice}>
                {voiceActive ? <Square size={19} aria-hidden /> : <Mic size={19} aria-hidden />}
                {voicePhase === 'starting' ? '取消语音' : voicePhase === 'listening' ? '停止说话' : voicePhase === 'processing' ? '正在识别' : '开始说话'}
              </button>
              {voiceError ? <p className={styles.voiceError} role="alert">{voiceError}</p>
                : voicePhase !== 'idle' ? <p className={styles.voiceStatus} role="status">{speechStatus[voicePhase]}</p> : null}
              <label className={styles.textLabel}>咨询说明
                <textarea autoComplete="off" value={speechText} onChange={event => setSpeechText(event.target.value)} maxLength={4000} rows={3} placeholder="例如：我在烟台市，2026年11月1日遇到拖欠工资，希望了解如何登记。" />
              </label>
              {modelProvider && <label className={styles.consentCheck}>
                <input type="checkbox" checked={modelConsent} disabled={busy} onChange={event => setModelConsent(event.target.checked)} />
                <span>同意将本次咨询的文字说明发送给 {modelProvider === 'deepseek' ? 'DeepSeek' : '外部模型'}，帮助补全登记信息（可选）。</span>
              </label>}
              <button type="button" className={styles.primary} disabled={busy || voiceActive || !speechText.trim()} onClick={applySpeech}>整理这段说明</button>
              {speechText.trim() && <button type="button" className={styles.helpLink} disabled={busy} onClick={() => setSpeechText('')}>清除说明</button>}
            </div>}
          </div>
          <fieldset disabled={busy}>
            <legend>您想咨询什么？</legend>
            <div className={styles.categories}>
              {categories.map(item => <button type="button" key={item.value} className={styles.category} aria-pressed={fields.category === item.value} onClick={() => setFields(old => ({ ...old, category: item.value }))}>
                <item.icon size={25} aria-hidden />
                <span><strong>{item.label ?? item.value}</strong><small>{item.hint}</small></span>
                {fields.category === item.value && <Check size={19} aria-hidden />}
              </button>)}
            </div>
          </fieldset>
          <div className={styles.fieldsGrid}>
            <Choices label="事情发生在哪里？" items={options.location} value={fields.location} disabled={busy} onSelect={location => setFields(old => ({ ...old, location }))} />
            <Choices label="事情大约何时发生？" items={options.event_date} value={fields.event_date} disabled={busy} onSelect={event_date => setFields(old => ({ ...old, event_date }))} />
            <Choices label="您希望获得什么帮助？" items={options.request} value={fields.request} disabled={busy} onSelect={request => setFields(old => ({ ...old, request }))} wide />
          </div>
          <div className={styles.actions}>
            <button type="button" className={styles.secondary} disabled={busy} onClick={() => void requestHelp()}><Headphones size={21} aria-hidden />请工作人员帮助</button>
            <button className={styles.primary} disabled={!complete || busy || voiceActive || !!speechText.trim()}>下一步：核对信息<ArrowRight size={22} aria-hidden /></button>
          </div>
          {speechText.trim() && !voiceOpen && <p className={styles.nextHint}>请先整理或清除待处理的说明。</p>}
          {!speechText.trim() && !complete && <p className={styles.nextHint}>请选好事项、地点、时间和需要的帮助。</p>}
        </form>}

        {step === 'review' && session && <section className={`${styles.panel} ${styles.narrow}`} aria-label="咨询摘要">
          <dl className={styles.review}>
            {reviewRows.map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{session.fields[key]}</dd></div>)}
          </dl>
          {session.citations.length > 0 && <details className={styles.sources}>
            <summary>查看流程来源</summary>
            {session.citations.map(source => <div key={source.id}><strong>{source.title}</strong><p>{source.content}</p><p>{source.version} · {source.locator}</p></div>)}
          </details>}
          <div className={styles.actions}>
            <button className={styles.secondary} onClick={() => { setError(''); setStep('details'); }} disabled={busy}><ArrowLeft size={21} aria-hidden />返回修改</button>
            <button className={styles.primary} onClick={() => void confirm()} disabled={busy}><Check size={22} aria-hidden />确认并提交</button>
          </div>
          <button className={styles.helpLink} onClick={() => void requestHelp()} disabled={busy}><Headphones size={21} aria-hidden />请工作人员帮助</button>
        </section>}

        {step === 'done' && session && <section className={`${styles.panel} ${styles.narrow} ${styles.done}`} aria-label="登记结果">
          <p>请前往人工服务台，向工作人员出示咨询编号。</p>
          <div className={styles.ticket}><span>咨询编号</span><strong>{session.id.slice(0, 8).toUpperCase()}</strong></div>
          <button className={styles.primary} onClick={reset}>完成并返回首页<ArrowRight size={22} aria-hidden /></button>
          <p className={styles.smallPrint}>页面将在 30 秒后返回首页。</p>
        </section>}

        {step === 'exit' && <section className={`${styles.panel} ${styles.narrow}`} aria-label="结束操作确认">
          <p className={styles.exitNote}>返回首页后，本屏将清除当前咨询信息。</p>
          <div className={styles.actions}>
            <button className={styles.secondary} onClick={() => setStep(previousStep)}>继续操作</button>
            <button className={styles.primary} onClick={reset}>结束并返回首页</button>
          </div>
        </section>}
      </main>
      <footer className={styles.footer}><ShieldCheck size={18} aria-hidden />{step === 'home' ? '演示终端 · 请勿录入真实个人信息' : '3 分钟无操作将自动清屏'}</footer>
    </div>
  );
}

function Choices({ label, items, value, disabled, onSelect, wide = false }: {
  label: string; items: string[]; value: string; disabled: boolean;
  onSelect: (value: string) => void; wide?: boolean;
}) {
  const choices = value && !items.includes(value) ? [value, ...items] : items;
  return (
    <fieldset className={wide ? styles.wide : undefined} disabled={disabled}>
      <legend>{label}</legend>
      <div className={styles.choices}>
        {choices.map(item => <button type="button" key={item} className={styles.choice} aria-pressed={value === item} onClick={() => onSelect(item)}>
          {value === item && <Check size={19} aria-hidden />}{item}
        </button>)}
      </div>
    </fieldset>
  );
}
