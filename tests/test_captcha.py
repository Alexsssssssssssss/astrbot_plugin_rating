import json

import httpx
import pytest

from mortal import captcha
from mortal.reports import AnalysisError


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv('TWOCAPTCHA_API_KEY', 'test-secret-not-real')
    async def pause(seconds, cancelled):
        if cancelled():
            raise AnalysisError('任务已取消。')
    monkeypatch.setattr(captcha, '_pause', pause)


def test_missing_key():
    with pytest.raises(AnalysisError, match='API Key'):
        captcha.TurnstileSolver('')


async def test_create_once_then_poll(configured):
    seen = []
    def handle(request):
        assert request.url.host == 'api.2captcha.com'
        body = json.loads(request.content)
        seen.append((request.url.path, body))
        if request.url.path == '/createTask':
            assert body['task'] == {'type': 'TurnstileTaskProxyless',
                'websiteURL': 'https://mjai.ekyu.moe/zh-cn.html',
                'websiteKey': 'public-key', 'action': 'review', 'data': 'data'}
            return httpx.Response(200, json={'errorId': 0, 'taskId': 7})
        assert body['taskId'] == 7
        if len(seen) == 2:
            return httpx.Response(200, json={'errorId': 0, 'status': 'processing'})
        return httpx.Response(200, json={'errorId': 0, 'status': 'ready',
                                        'solution': {'token': 'test-result'}})
    token = await captcha.solve({'url': 'https://mjai.ekyu.moe/zh-cn.html',
        'sitekey': 'public-key', 'action': 'review', 'data': 'data'},
        api_key='test-secret-not-real', transport=httpx.MockTransport(handle))
    assert token == 'test-result'
    assert [path for path, _ in seen].count('/createTask') == 1


async def test_provider_error_does_not_disclose_secret(configured):
    def handle(request):
        return httpx.Response(200, json={'errorId': 1,
            'errorCode': 'ERROR_ZERO_BALANCE', 'errorDescription': 'test-secret-not-real'})
    with pytest.raises(AnalysisError) as exc:
        await captcha.solve({'url': 'https://mjai.ekyu.moe', 'sitekey': 'public'},
                            api_key='test-secret-not-real', transport=httpx.MockTransport(handle))
    assert 'ERROR_ZERO_BALANCE' in str(exc.value)
    assert 'test-secret-not-real' not in str(exc.value)


async def test_network_error_never_recreates_paid_task(configured):
    calls = []
    def handle(request):
        calls.append(request.url.path)
        raise httpx.ReadTimeout('test-secret-not-real', request=request)
    with pytest.raises(AnalysisError) as exc:
        await captcha.solve({'url': 'https://mjai.ekyu.moe', 'sitekey': 'public'},
                            api_key='test-secret-not-real', transport=httpx.MockTransport(handle))
    assert calls == ['/createTask']
    assert 'test-secret-not-real' not in str(exc.value)


async def test_cancel_before_creating_task(configured):
    def handle(request):
        pytest.fail('No paid request should be made')
    with pytest.raises(AnalysisError, match='取消'):
        await captcha.solve({'url': 'https://mjai.ekyu.moe', 'sitekey': 'public'},
                            cancelled=lambda: True, api_key='test-secret-not-real', transport=httpx.MockTransport(handle))


async def test_ready_without_token_is_rejected(configured):
    def handle(request):
        if request.url.path == '/createTask':
            return httpx.Response(200, json={'errorId': 0, 'taskId': 7})
        return httpx.Response(200, json={'errorId': 0, 'status': 'ready', 'solution': {}})
    with pytest.raises(AnalysisError, match='有效验证结果'):
        await captcha.solve({'url': 'https://mjai.ekyu.moe', 'sitekey': 'public'},
                            api_key='test-secret-not-real', transport=httpx.MockTransport(handle))


async def test_paid_task_budget(monkeypatch):
    seen = []
    async def solve(parameters, cancelled, **kwargs):
        seen.append(parameters)
        return 'token'
    monkeypatch.setattr(captcha, 'solve', solve)
    solver = captcha.TurnstileSolver('test-key', max_tasks=1)
    assert await solver.solve({}) == 'token'
    with pytest.raises(AnalysisError, match='上限'):
        await solver.solve({})
    assert len(seen) == 1


@pytest.mark.parametrize('kind, expected', [
    ('connect_timeout', '连接 api.2captcha.com 超时'),
    ('read_timeout', '响应超时'),
    ('proxy', '代理连接失败'),
    ('connect', '无法连接'),
    ('http', 'HTTP 403'),
    ('html', '非 JSON'),
    ('tls', 'TLS 证书校验失败'),
])
async def test_safe_request_diagnostics(configured, kind, expected):
    import ssl
    calls = []
    def handle(request):
        calls.append(request.url.path)
        if kind == 'http':
            return httpx.Response(403, text='secret-test-key')
        if kind == 'html':
            return httpx.Response(200, text='<html>secret-test-key</html>')
        if kind == 'tls':
            raise httpx.ConnectError('secret-test-key', request=request) from ssl.SSLCertVerificationError('secret-test-key')
        error = {'connect_timeout': httpx.ConnectTimeout, 'read_timeout': httpx.ReadTimeout,
                 'proxy': httpx.ProxyError, 'connect': httpx.ConnectError}[kind]
        raise error('secret-test-key', request=request)
    with pytest.raises(AnalysisError) as exc:
        await captcha.solve({'url': 'https://mjai.ekyu.moe', 'sitekey': 'public'},
            api_key='secret-test-key', transport=httpx.MockTransport(handle))
    assert expected in str(exc.value)
    assert '创建任务失败' in str(exc.value)
    assert 'secret-test-key' not in str(exc.value)
    assert calls == ['/createTask']


async def test_polling_failure_distinguished_from_creation(configured):
    calls = []
    def handle(request):
        calls.append(request.url.path)
        if request.url.path == '/createTask':
            return httpx.Response(200, json={'taskId': 42})
        raise httpx.ReadTimeout('secret', request=request)
    with pytest.raises(AnalysisError, match='查询结果失败'):
        await captcha.solve({'url': 'https://mjai.ekyu.moe', 'sitekey': 'public'},
            api_key='secret', transport=httpx.MockTransport(handle))
    assert calls == ['/createTask', '/getTaskResult']


def test_proxy_config_validation():
    solver = captcha.TurnstileSolver('key', proxy='http://127.0.0.1:7890', request_timeout=60)
    assert solver.proxy == 'http://127.0.0.1:7890' and solver.request_timeout == 60
    with pytest.raises(AnalysisError, match='代理格式错误'):
        captcha.TurnstileSolver('key', proxy='not-a-proxy')
