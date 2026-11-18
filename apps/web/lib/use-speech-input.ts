'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRecordedSpeech, type Transcribe } from './use-recorded-speech';

type Phase = 'idle' | 'starting' | 'listening' | 'processing';
export type SpeechProvider = 'browser' | 'local_whisper';
type Recognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onaudiostart: (() => void) | null;
  onaudioend: (() => void) | null;
  onresult: ((event: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onnomatch: (() => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
};

type SpeechWindow = Window & {
  SpeechRecognition?: new () => Recognition;
  webkitSpeechRecognition?: new () => Recognition;
};

type Run = { mic: Recognition; phase: Exclude<Phase, 'idle'>; timer?: number; receivedText: boolean };

const noResult = '没有得到可用的转写，请重试或改用文字。';
const startupFailed = '无法开启麦克风，请检查浏览器权限或改用文字。';
const speechErrors: Record<string, string> = {
  'not-allowed': '麦克风权限未开启。请在浏览器中允许麦克风，或改用文字。',
  'service-not-allowed': '此浏览器无法使用语音识别服务，请改用文字。',
  'audio-capture': '浏览器无法从麦克风采集声音，请检查设备连接或改用文字。',
  'network': '语音识别服务连接失败，请重试或改用文字。',
  'no-speech': '没有听到说话，请靠近麦克风重试或改用文字。',
  'language-not-supported': '此浏览器的语音服务暂不支持普通话识别，请改用文字。',
};

export const speechStatus: Record<Exclude<Phase, 'idle'>, string> = {
  starting: '正在开启麦克风…',
  listening: '正在聆听，请说话。',
  processing: '正在识别，请稍候…',
};

function release(run: Run, abort: boolean) {
  window.clearTimeout(run.timer);
  const { mic } = run;
  mic.onaudiostart = null;
  mic.onaudioend = null;
  mic.onresult = null;
  mic.onnomatch = null;
  mic.onerror = null;
  mic.onend = null;
  if (abort) {
    try { mic.abort(); } catch { /* The browser may already have ended recognition. */ }
  }
}

function useBrowserSpeechInput() {
  const active = useRef<Run | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState('');

  const cancel = useCallback(() => {
    const run = active.current;
    active.current = null;
    if (run) release(run, true);
    setPhase('idle');
    setError('');
  }, []);

  useEffect(() => () => {
    const run = active.current;
    active.current = null;
    if (run) release(run, true);
  }, []);

  function finish(run: Run, message: string, abort = false) {
    if (active.current !== run) return;
    active.current = null;
    release(run, abort);
    setPhase('idle');
    setError(message);
  }

  function transition(run: Run, next: Run['phase']) {
    if (active.current !== run || (next === 'listening' && run.phase === 'processing')) return;
    run.phase = next;
    setPhase(next);
    window.clearTimeout(run.timer);
    const timeout = next === 'listening' ? 35_000 : 12_000;
    run.timer = window.setTimeout(() => {
      if (next === 'listening') stop();
      else finish(run, next === 'starting' ? startupFailed : noResult, true);
    }, timeout);
  }

  function start(onText: (transcript: string) => void) {
    if (active.current) return;
    setError('');
    if (!window.isSecureContext) {
      setError('语音需要通过 HTTPS 或本机地址打开。现在可以改用文字。');
      return;
    }
    const browser = window as SpeechWindow;
    const Speech = browser.SpeechRecognition ?? browser.webkitSpeechRecognition;
    if (!Speech) {
      setError('此浏览器不支持语音识别，请改用文字或点选。');
      return;
    }
    let mic: Recognition;
    try { mic = new Speech(); } catch {
      setError(startupFailed);
      return;
    }
    const run: Run = { mic, phase: 'starting', receivedText: false };
    active.current = run;
    mic.lang = 'zh-CN';
    mic.interimResults = false;
    mic.continuous = false;
    mic.onaudiostart = () => transition(run, 'listening');
    mic.onaudioend = () => transition(run, 'processing');
    mic.onresult = event => {
      if (active.current !== run) return;
      const text = Array.from(event.results).slice(event.resultIndex)
        .map(row => row[0]?.transcript ?? '').join('').trim();
      if (text) {
        run.receivedText = true;
        onText(text);
      }
    };
    mic.onnomatch = () => finish(run, noResult, true);
    mic.onerror = event => finish(run, speechErrors[event.error] ?? noResult, true);
    mic.onend = () => finish(run, run.receivedText ? '' : noResult);
    try {
      transition(run, 'starting');
      mic.start();
    } catch {
      finish(run, startupFailed, true);
    }
  }

  function stop() {
    const run = active.current;
    if (!run || run.phase === 'processing') return;
    if (run.phase === 'starting') {
      cancel();
      return;
    }
    try {
      transition(run, 'processing');
      run.mic.stop();
    } catch {
      finish(run, noResult, true);
    }
  }

  return { phase, error, start, stop, cancel, previewText: '' };
}

export function useSpeechInput(provider: SpeechProvider | null, transcribe: Transcribe) {
  const browser = useBrowserSpeechInput();
  const local = useRecordedSpeech(transcribe);
  return provider === 'local_whisper' ? local : browser;
}
