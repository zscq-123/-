'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

export type SpeechPhase = 'idle' | 'starting' | 'listening' | 'processing';
export type Transcribe = (audio: Blob, signal: AbortSignal) => Promise<string>;

type Recording = {
  stream?: MediaStream;
  recorder?: MediaRecorder;
  timer?: number;
  controller: AbortController;
  stopping: boolean;
};

const formats = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus'];
const maxBytes = 2 * 1024 * 1024;
const expectedSeconds = 35;

function release(recording: Recording) {
  window.clearTimeout(recording.timer);
  recording.controller.abort();
  if (recording.recorder) {
    recording.recorder.ondataavailable = null;
    recording.recorder.onstop = null;
    recording.recorder.onerror = null;
    if (recording.recorder.state !== 'inactive') recording.recorder.stop();
  }
  recording.stream?.getTracks().forEach(track => track.stop());
}

function permissionMessage(cause: unknown) {
  if (cause instanceof DOMException && ['NotAllowedError', 'SecurityError'].includes(cause.name)) {
    return '麦克风权限未开启。请在浏览器中允许麦克风，或改用文字。';
  }
  return '无法打开麦克风。请检查麦克风连接，或改用文字。';
}

export function useRecordedSpeech(transcribe: Transcribe) {
  const active = useRef<Recording | null>(null);
  const [phase, setPhase] = useState<SpeechPhase>('idle');
  const [error, setError] = useState('');

  const clear = useCallback(() => {
    const recording = active.current;
    active.current = null;
    if (recording) release(recording);
  }, []);

  useEffect(() => clear, [clear]);

  const cancel = useCallback(() => {
    clear();
    setPhase('idle');
    setError('');
  }, [clear]);

  function finish(recording: Recording, message = '') {
    if (recording !== active.current) return;
    clear();
    setPhase('idle');
    setError(message);
  }

  function stop() {
    const recording = active.current;
    if (!recording || recording.stopping) return;
    if (!recording.recorder) {
      cancel();
      return;
    }
    recording.stopping = true;
    window.clearTimeout(recording.timer);
    setPhase('processing');
    recording.timer = window.setTimeout(() => finish(recording, '语音处理超时，请重试或改用文字。'), 38_000);
    if (recording.recorder.state === 'recording') recording.recorder.stop();
    else finish(recording, '这段录音已中断，请重新录制。');
  }

  async function start(onText: (text: string) => void) {
    if (active.current) return;
    setError('');
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setError('当前浏览器无法录音，请用支持麦克风的浏览器打开本机地址，或改用文字。');
      return;
    }
    const recording: Recording = { controller: new AbortController(), stopping: false };
    active.current = recording;
    setPhase('starting');
    recording.timer = window.setTimeout(() => finish(recording, '麦克风未在限定时间内开启，请重试。'), 15_000);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({audio: true});
      if (active.current !== recording) {
        stream.getTracks().forEach(track => track.stop());
        return;
      }
      recording.stream = stream;
      const mimeType = formats.find(type => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 48_000 });
      recording.recorder = recorder;
      const chunks: Blob[] = [];
      let size = 0;
      recorder.ondataavailable = event => {
        if (recording !== active.current || !event.data.size) return;
        size += event.data.size;
        if (size > maxBytes) finish(recording, '录音太长，请分成几段说。');
        else chunks.push(event.data);
      };
      recorder.onerror = () => finish(recording, '麦克风录音中断，请重试或改用文字。');
      recorder.onstop = async () => {
        if (recording !== active.current) return;
        stream.getTracks().forEach(track => track.stop());
        if (!recording.stopping || !size) {
          finish(recording, '没有录到声音，请检查麦克风并重试。');
          return;
        }
        try {
          const audio = new Blob(chunks, {type: recorder.mimeType || chunks[0].type});
          const text = await transcribe(audio, recording.controller.signal);
          if (active.current !== recording) return;
          onText(text);
          finish(recording);
        } catch (cause) {
          finish(recording, cause instanceof Error ? cause.message : '转写未完成，请重试或改用文字。');
        }
      };
      recorder.start(250);
      setPhase('listening');
      window.clearTimeout(recording.timer);
      recording.timer = window.setTimeout(stop, expectedSeconds * 1000);
    } catch (cause) {
      finish(recording, permissionMessage(cause));
    }
  }

  return { phase, error, start, stop, cancel };
}
