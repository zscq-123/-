import { NextRequest, NextResponse } from 'next/server';

const allowed = new Set(['health', 'auth', 'sessions', 'orchestrator', 'evidence', 'matching', 'work-orders', 'knowledge', 'personnel', 'audit', 'metrics']);
async function proxy(request: NextRequest, context: {params: Promise<{path: string[]}>}) {
  const { path } = await context.params;
  if (!path.length || !allowed.has(path[0]) || path.some(p => !/^[a-zA-Z0-9_-]+$/.test(p))) {
    return NextResponse.json({detail: '接口不存在'}, {status: 404});
  }
  const origin = new URL(process.env.BACKEND_URL || 'http://127.0.0.1:8000');
  const basePath = origin.pathname.replace(/\/$/, '');
  origin.pathname = `${basePath.endsWith('/api') ? basePath : `${basePath}/api`}/${path.join('/')}`;
  origin.search = request.nextUrl.search;
  const headers = new Headers();
  for (const key of ['content-type', 'authorization', 'x-session-token', 'x-request-id', 'idempotency-key']) {
    const value = request.headers.get(key);
    if (value) headers.set(key, value);
  }
  const hasBody = !['GET', 'HEAD'].includes(request.method);
  if (Number(request.headers.get('content-length') || 0) > 250000) {
    return NextResponse.json({detail: '请求内容过大'}, {status: 413});
  }
  try {
    const body = hasBody ? await request.text() : undefined;
    if (body && Buffer.byteLength(body, 'utf8') > 250000) return NextResponse.json({detail: '请求内容过大'}, {status: 413});
    const response = await fetch(origin, { method: request.method, headers, body, cache: 'no-store', signal: AbortSignal.timeout(20000), redirect: 'error' });
    return new Response(await response.arrayBuffer(), {status: response.status, headers: {
      'Content-Type': response.headers.get('content-type') || 'application/json', 'Cache-Control': 'no-store',
    }});
  } catch {
    return NextResponse.json({detail: '接待服务暂不可用，请稍后重试或联系工作人员。'}, {status: 503});
  }
}
export { proxy as GET, proxy as POST, proxy as PATCH };
