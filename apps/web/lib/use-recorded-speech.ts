'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

export type SpeechPhase = 'idle' | 'starting' | 'listening' | 'processing';
export type Transcribe = (audio: Blob, signal: AbortSignal, preview?: boolean) => Promise<string>;

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
const fastPreviewIntervalMs = 500;
const whisperPreviewIntervalMs = 2400;

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

export function useRecordedSpeech(transcribe: Transcribe, fastPreview: boolean) {
  const active = useRef<Recording | null>(null);
  const [phase, setPhase] = useState<SpeechPhase>('idle');
  const [error, setError] = useState('');
  const [previewText, setPreviewText] = useState('');

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
    setPreviewText('');
  }, [clear]);

  function finish(recording: Recording, message = '') {
    if (recording !== active.current) return;
    clear();
    setPhase('idle');
    setError(message);
    setPreviewText('');
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
    setPreviewText('');
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
      const previewIntervalMs = fastPreview ? fastPreviewIntervalMs : whisperPreviewIntervalMs;
      let nextPreviewAt = performance.now() + previewIntervalMs;
      let latestPreview = '';
      let previewRequest: Promise<void> | undefined;
      const audioSnapshot = () => new Blob(chunks, {type: recorder.mimeType || chunks[0].type});

      async function updatePreview(audio: Blob) {
        try {
          const text = await transcribe(audio, recording.controller.signal, true);
          if (active.current === recording && text.trim()) {
            if (text !== latestPreview) {
              latestPreview = text;
              if (!recording.stopping) setPreviewText(text);
            }
          }
        } catch {
          // Silence and incomplete containers can fail during capture. A failed
          // preview must leave recording and the final transcription available.
        } finally {
          previewRequest = undefined;
        }
      }

      recorder.ondataavailable = event => {
        if (recording !== active.current || !event.data.size) return;
        size += event.data.size;
        if (size > maxBytes) {
          finish(recording, '录音太长，请分成几段说。');
          return;
        }
        chunks.push(event.data);
        const now = performance.now();
        if (!recording.stopping && !previewRequest && now >= nextPreviewAt) {
          nextPreviewAt = now + previewIntervalMs;
          // Keep the container's initialization bytes with subsequent audio.
          previewRequest = updatePreview(audioSnapshot());
        }
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
          // The local worker handles one job at a time. Finish any preview
          // already in flight before sending the definitive recording.
          await previewRequest;
          if (active.current !== recording) return;
          const text = await transcribe(audioSnapshot(), recording.controller.signal);
          if (active.current !== recording) return;
          onText(text);
          finish(recording);
        } catch (cause) {
          if (active.current !== recording) return;
          if (latestPreview) {
            onText(latestPreview);
            finish(recording, '完整转写未完成，已保留实时字幕。请核对并补充末段文字。');
          } else {
            finish(recording, cause instanceof Error ? cause.message : '转写未完成，请重试或改用文字。');
          }
        }
      };
      recorder.start(fastPreview ? 160 : 250);
      setPhase('listening');
      window.clearTimeout(recording.timer);
      recording.timer = window.setTimeout(stop, expectedSeconds * 1000);
    } catch (cause) {
      finish(recording, permissionMessage(cause));
    }
  }

  return { phase, error, start, stop, cancel, previewText };
}
