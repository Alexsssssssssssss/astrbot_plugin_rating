"""复现旧接收器遗漏的真实浏览器交付形式，不访问外部服务。"""
import json
import pytest

from mortal.browser import MortalBrowser
from mortal.reports import AnalysisError
from test_browser import OFFICIAL_FORM


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setenv('MORTAL_INTERVAL', '0')
    monkeypatch.setenv('MORTAL_TIMEOUT', '8')


@pytest.mark.parametrize('status', [400, 403, 429, 500])
async def test_post_http_errors_stop_immediately(game, status):
    import time
    async with MortalBrowser() as browser:
        async def handle(route):
            if route.request.method == 'POST':
                await route.fulfill(status=status, content_type='text/html', body='Rejected')
            else:
                await route.fulfill(content_type='text/html', body=OFFICIAL_FORM.replace(' disabled', ''))
        await browser.context.route('https://mjai.ekyu.moe/**', handle)
        started = time.monotonic()
        with pytest.raises(AnalysisError, match=f'HTTP {status}'):
            await browser.analyze(game)
        assert time.monotonic() - started < 8


@pytest.mark.parametrize('delivery', ['json', 'download', 'killerducky', 'fetch'])
async def test_json_report_delivery(game, report, delivery):
    async with MortalBrowser() as browser:
        async def handle(route):
            path = route.request.url.split('?', 1)[0]
            if path.endswith('/review'):
                if delivery == 'json':
                    await route.fulfill(content_type='application/json', body=json.dumps(report))
                elif delivery == 'download':
                    await route.fulfill(content_type='application/json',
                        headers={'Content-Disposition': 'attachment; filename="report.json"'}, body=json.dumps(report))
                elif delivery == 'killerducky':
                    await route.fulfill(content_type='text/html', body='''<script>
                    location.href='/killerducky/?data=/report/test.json';</script>''')
                else:
                    await route.fulfill(content_type='text/html', body="<script>fetch('/report/test.json')</script>")
            elif '/report/' in path:
                await route.fulfill(content_type='application/json', body=json.dumps(report))
            elif '/killerducky/' in path:
                await route.fulfill(content_type='text/html', body="<script>fetch('/report/test.json')</script>")
            else:
                await route.fulfill(content_type='text/html', body=OFFICIAL_FORM.replace(' disabled', ''))
        await browser.context.route('https://mjai.ekyu.moe/**', handle)
        result, _ = await browser.analyze(game)
        assert result['rating'] == 90.25 and result['log_id'] == game['uuid']
        assert result['player_id'] == game['seat']


async def test_server_error_page_is_not_waited_until_timeout(game):
    async with MortalBrowser() as browser:
        async def handle(route):
            html = ('<title>Error</title><p>Invalid captcha</p>' if route.request.method == 'POST'
                    else OFFICIAL_FORM.replace(' disabled', ''))
            await route.fulfill(content_type='text/html', body=html)
        await browser.context.route('https://mjai.ekyu.moe/**', handle)
        with pytest.raises(AnalysisError, match='验证失败'):
            await browser.analyze(game)


async def test_failed_post_network_request_is_not_hidden(game):
    async with MortalBrowser() as browser:
        async def handle(route):
            if route.request.method == 'POST':
                await route.abort('connectionreset')
            else:
                await route.fulfill(content_type='text/html', body=OFFICIAL_FORM.replace(' disabled', ''))
        await browser.context.route('https://mjai.ekyu.moe/**', handle)
        with pytest.raises(AnalysisError, match='ERR_CONNECTION_RESET'):
            await browser.analyze(game)


async def test_no_post_after_click_is_reported(game):
    async with MortalBrowser() as browser:
        await browser.context.route('https://mjai.ekyu.moe/**', lambda route: route.fulfill(
            content_type='text/html', body=OFFICIAL_FORM.replace(' disabled', '').replace(
                'method="post"', 'method="post" onsubmit="return false"')))
        with pytest.raises(AnalysisError, match='没有观察到匹配的 POST'):
            await browser.analyze(game)


async def test_unrelated_json_without_log_id_is_never_adopted(game, report, monkeypatch):
    monkeypatch.setenv('MORTAL_TIMEOUT', '3')
    report.pop('log_id')
    async with MortalBrowser() as browser:
        async def handle(route):
            if route.request.method == 'POST':
                await route.fulfill(content_type='text/html', body="<script>fetch('/report/example.json')</script>")
            elif '/report/' in route.request.url:
                await route.fulfill(content_type='application/json', body=json.dumps(report))
            else:
                await route.fulfill(content_type='text/html', body=OFFICIAL_FORM.replace(' disabled', ''))
        await browser.context.route('https://mjai.ekyu.moe/**', handle)
        with pytest.raises(AnalysisError, match='超时'):
            await browser.analyze(game)


@pytest.mark.parametrize('include_id', [True, False])
async def test_rendered_report_does_not_wait_for_response_body_end(game, html_report, monkeypatch, include_id):
    import asyncio
    from playwright.async_api import Response
    original = Response.text
    stopped = []
    async def text(self):
        if self.url.endswith('/review'):
            try:
                await asyncio.Event().wait()
            finally:
                stopped.append(True)
        return await original(self)
    monkeypatch.setattr(Response, 'text', text)
    if not include_id:
        html_report = html_report.replace('<dt>牌谱 ID</dt><dd>test-game-001</dd>', '')
    async with MortalBrowser() as browser:
        async def handle(route):
            content = html_report if route.request.method == 'POST' else OFFICIAL_FORM.replace(' disabled', '')
            await route.fulfill(content_type='text/html', body=content)
        await browser.context.route('https://mjai.ekyu.moe/**', handle)
        result, _ = await asyncio.wait_for(browser.analyze(game), timeout=12)
        assert result['rating'] == 90.25 and result['log_id'] == game['uuid']
    assert stopped
