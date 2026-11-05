import asyncio
import pytest
from mortal import service as core
from urllib.parse import quote

@pytest.mark.parametrize('url,source,log_id', [
    ('https://game.maj-soul.com/1/?paipu=260101-abcdef12_a123', '雀魂', '260101-abcdef12'),
    ('https://tenhou.net/0/?log=2026010100gm-00a9-0000-abcdef12&tw=2', '天凤', '2026010100gm-00a9-0000-abcdef12'),
])
def test_record_links(url, source, log_id):
    record = core.parse_record('rating ' + url)
    assert record.source == source and record.log_id == log_id
    assert 'tw=' not in record.url


@pytest.mark.parametrize('text', [
    'https://tenhou.net.evil.test/0/?log=2026010100gm-00a9-0000-abcdef12',
    'https://user:secret@tenhou.net/0/?log=2026010100gm-00a9-0000-abcdef12',
    'https://game.maj-soul.com/1/?paipu=a&paipu=b',
    'https://127.0.0.1/?paipu=260101-abcdef12',
    'rating',
    'https://game.maj-soul.com/1/?paipu=260101-abcdef12 https://game.maj-soul.com/1/?paipu=260101-deadbeef',
])
def test_rejects_ambiguous_or_untrusted_links(text):
    with pytest.raises(ValueError):
        core.parse_record(text)


async def test_all_seats_and_output():
    calls = []
    class Browser:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def analyze(self, game):
            calls.append(game['seat'])
            return dict(rating=74.35, agreement=48/74*100, total_matches=48,
                        total_reviewed=74, model_tag='TEST',
                        report_url='https://mjai.ekyu.moe/report/test.html'), '<html></html>'
    service = core.RatingService(Browser)
    record = core.parse_record('https://tenhou.net/0/?log=2026010100gm-00a9-0000-abcdef12')
    result = await service.analyze(record)
    assert calls == [0, 1, 2, 3]
    assert 'Rating: 74.35 一致率: 64.9 (48/74)' in result
    assert '北家' in result and '/report/test.html' in result
    assert service.pending == 0


async def test_failure_preserves_results_and_stops():
    class Browser:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def analyze(self, game):
            if game['seat']:
                raise core.AnalysisError('Cloudflare 人机验证')
            return dict(rating=75, agreement=50, total_matches=1, total_reviewed=2), ''
    service = core.RatingService(Browser)
    record = core.parse_record('https://game.maj-soul.com/1/?paipu=260101-abcdef12')
    result = await service.analyze(record)
    assert 'Rating: 75.00' in result and 'Cloudflare' in result
    assert '西家' not in result and service.pending == 0


def test_tenhou_identity_and_report_links():
    from mortal import reports
    log = '2026010100gm-00a9-0000-abcdef12'
    assert reports.log_matches(log, f'https://tenhou.net/0/?log={log}&tw=1')
    assert not reports.log_matches(log, log + 'bad')
    text = core.format_result(dict(rating=50, agreement=50, total_matches=1,
        total_reviewed=2, report_url='https://evil.test/report/x'), '东家')
    assert 'evil.test' not in text


def test_names_from_classic_report():
    import json
    data = quote(json.dumps({'name': ['小明', '小红', '小蓝', '小绿']}))
    html = f'<iframe src="https://tenhou.net/5/#json={data}"></iframe>'
    assert core.player_name(html, 2) == '小蓝'
    assert core.player_name('<html></html>', 2) == '西家'


async def test_queue_limit_serialization_and_cancellation():
    entered = asyncio.Event()
    release = asyncio.Event()
    exited = asyncio.Event()
    class Browser:
        async def __aenter__(self):
            entered.set()
            return self
        async def __aexit__(self, *args): exited.set()
        async def analyze(self, game):
            await release.wait()
            return dict(rating=50, agreement=50, total_matches=1, total_reviewed=2), ''
    service = core.RatingService(Browser, max_pending=1)
    record = core.parse_record('https://game.maj-soul.com/1/?paipu=260101-abcdef12')
    task = asyncio.create_task(service.analyze(record))
    await entered.wait()
    assert '队列已满' in await service.analyze(record)
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert service.pending == 0 and exited.is_set()
