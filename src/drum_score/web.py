"""HTTP adapter. Conversion runs exclusively in the separate worker."""
from pathlib import Path
import asyncio
from .arguments import PublicParser
import ipaddress
import os
import re
from time import monotonic

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from .jobs import JobError, Jobs


class Submission(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: str = Field(max_length=2048)


class BodyLimit:
    """Bound bytes before JSON parsing, including chunked requests."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] != 'POST':
            return await self.app(scope, receive, send)
        body = bytearray()
        deadline = monotonic() + 10
        try:
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError
                event = await asyncio.wait_for(receive(), timeout=remaining)
                if monotonic() >= deadline:
                    raise TimeoutError
                if event['type'] == 'http.disconnect':
                    return
                chunk = event.get('body', b'')
                if len(body) + len(chunk) > 8192:
                    return await JSONResponse({'error': {'code': 'request_too_large', 'message': '请求超过8KiB限制。'}}, status_code=413)(scope, receive, send)
                body.extend(chunk)
                if not event.get('more_body', False):
                    break
        except TimeoutError:
            return await JSONResponse({'error': {'code': 'request_timeout', 'message': '请求接收超时。'}}, status_code=408)(scope, receive, send)
        sent = False
        async def bounded_receive():
            nonlocal sent
            if sent:
                return await receive()
            sent = True
            return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
        await self.app(scope, bounded_receive, send)


class ArtifactResources:
    """Own opened files even if cancellation precedes the response iterator."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        streams = scope.setdefault('drum_score.open_files', [])
        try:
            await self.app(scope, receive, send)
        finally:
            for stream in streams:
                stream.close()


def create_app(data_root, *, trusted_proxies=(), retention_seconds=86400, **storage):
    jobs = Jobs(data_root, retention_seconds=retention_seconds, **storage)
    proxies = frozenset(ipaddress.ip_address(value) for value in trusted_proxies)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(BodyLimit)
    app.add_middleware(ArtifactResources)

    @app.middleware('http')
    async def security(request, call_next):
        response = await call_next(request)
        response.headers.update({'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
            'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"})
        return response

    @app.exception_handler(JobError)
    async def job_error(request, error):
        return JSONResponse({'error': {'code': error.code, 'message': error.message}}, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        return JSONResponse({'error': {'code': 'invalid_request', 'message': '请仅提交公开 HTTPS B站 BV 链接。'}}, status_code=422)

    def peer(request):
        try:
            address = ipaddress.ip_address(request.client.host)
            if address in proxies and 'x-forwarded-for' in request.headers:
                chain = request.headers['x-forwarded-for'].split(',')
                if len(chain) > 16:
                    raise ValueError
                addresses = [ipaddress.ip_address(value.strip()) for value in chain]
                for value in reversed(addresses):
                    if address not in proxies:
                        break
                    address = value
            return str(address)
        except (ValueError, AttributeError):
            raise JobError('invalid_peer', '无法确认请求网络地址。', 400) from None

    def capability(request):
        value = request.headers.get('authorization', '')
        return value[7:] if re.fullmatch(r'Bearer [A-Za-z0-9_-]{1,128}', value) else ''

    @app.post('/api/tasks', status_code=201)
    def submit(body: Submission, request: Request):
        return jobs.enqueue(body.url, peer(request))

    @app.get('/api/tasks/{task}')
    def status(task: str, request: Request):
        return jobs.view(task, capability(request))

    @app.post('/api/tasks/{task}/cancel')
    def cancel(task: str, request: Request):
        return jobs.cancel(task, capability(request))

    @app.post('/api/tasks/{task}/retry')
    def retry(task: str, request: Request):
        jobs.view(task, capability(request))
        return jobs.retry(task, capability(request), peer(request))

    def artifact(task, request, page=None):
        descriptor, size = jobs.open_artifact(task, capability(request), page)
        stream = os.fdopen(descriptor, 'rb')
        request.scope['drum_score.open_files'].append(stream)
        def chunks():
            try:
                while chunk := stream.read(64 * 1024):
                    yield chunk
            finally:
                stream.close()
        headers = {'Content-Length': str(size)}
        if page is None:
            headers['Content-Disposition'] = 'attachment; filename="drum-score.pdf"'
        return StreamingResponse(chunks(), media_type='application/pdf' if page is None else 'image/png',
            headers=headers)

    @app.get('/api/tasks/{task}/pdf')
    def pdf(task: str, request: Request):
        return artifact(task, request)

    @app.get('/api/tasks/{task}/pages/{page}')
    def preview(task: str, page: str, request: Request):
        jobs.view(task, capability(request))
        if not page.isascii() or not page.isdecimal() or len(page) > 6:
            raise JobError('not_found', '页面不存在。', 404)
        return artifact(task, request, int(page))

    assets = Path(__file__).with_name('static')

    @app.get('/favicon.ico', status_code=204)
    def favicon():
        return Response(status_code=204)

    @app.get('/')
    @app.get('/task/{task}')
    def page():
        return Response((assets / 'index.html').read_bytes(), media_type='text/html')

    @app.get('/assets/{name}')
    def asset(name: str):
        types = {'app.js': 'text/javascript', 'style.css': 'text/css'}
        if name not in types:
            raise JobError('not_found', '资源不存在。', 404)
        return Response((assets / name).read_bytes(), media_type=types[name])

    return app


def main(argv=None):
    import uvicorn
    parser = PublicParser(prog='drum-score-web', description='匿名鼓谱网站 HTTP 服务，另行启动 worker。')
    parser.add_argument('--data-root', required=True)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--trusted-proxy', action='append', default=[], help='明确核实的代理 IP，可重复；不接受通配符')
    from .service_limits import add_storage_arguments, storage_options
    add_storage_arguments(parser)
    args = parser.parse_args(argv)
    try:
        app = create_app(args.data_root, trusted_proxies=args.trusted_proxy, **storage_options(args))
    except (OSError, ValueError, JobError):
        parser.error('数据目录或可信代理配置无效。')
    # Never let Uvicorn rewrite ASGI peer identity before our explicit proxy policy.
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=False, access_log=False,
        log_level='warning', limit_concurrency=64, timeout_keep_alive=5)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
