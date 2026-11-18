export async function api<T>(path: string, options: {method?: string; body?: unknown; token?: string; sessionToken?: string} = {}): Promise<T> {
  const headers: Record<string, string> = {'Content-Type': 'application/json'};
  if (options.token) headers.Authorization = `Bearer ${options.token}`;
  if (options.sessionToken) headers['X-Session-Token'] = options.sessionToken;
  const response = await fetch(`/api/backend${path}`, {method: options.method || 'GET', headers, body: options.body === undefined ? undefined : JSON.stringify(options.body), cache: 'no-store'});
  const result = await response.json().catch(() => ({detail: '服务返回了无法识别的结果'}));
  if (!response.ok) {
    const detail = result.detail;
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((e: {msg?: string}) => e.msg || '输入有误').join('；') : '操作失败，请重试');
  }
  return result as T;
}
