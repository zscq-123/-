export async function api<T>(path: string, options: {method?: string; body?: unknown; token?: string; sessionToken?: string; signal?: AbortSignal} = {}): Promise<T> {
  const audio = options.body instanceof Blob ? options.body : null;
  const headers: Record<string, string> = {'Content-Type': audio ? audio.type : 'application/json'};
  if (options.token) headers.Authorization = `Bearer ${options.token}`;
  if (options.sessionToken) headers['X-Session-Token'] = options.sessionToken;
  const response = await fetch(`/api/backend${path}`, {method: options.method || 'GET', headers,
    body: audio ?? (options.body === undefined ? undefined : JSON.stringify(options.body)), cache: 'no-store', signal: options.signal});
  const result = await response.json().catch(() => ({detail: '服务返回了无法识别的结果'}));
  if (!response.ok) {
    const detail = result.detail;
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((e: {msg?: string}) => e.msg || '输入有误').join('；') : '操作失败，请重试');
  }
  return result as T;
}

export async function transcribeAudio(sessionId: string, sessionToken: string, audio: Blob, signal: AbortSignal, preview = false) {
  const suffix = preview ? '?preview=true' : '';
  const result = await api<{ text: string }>(`/sessions/${sessionId}/transcribe${suffix}`, {
    method: 'POST', body: audio, sessionToken, signal,
  });
  return result.text;
}
