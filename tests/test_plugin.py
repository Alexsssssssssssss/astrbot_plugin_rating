"""AstrBot 消息接口使用替身；真实 QQ 连接需要 NapCat 联调。"""
import asyncio
import importlib
import sys
import types
from pathlib import Path

import pytest


@pytest.fixture
def plugin(monkeypatch):
    event_api = types.ModuleType('astrbot.api.event')
    event_api.AstrMessageEvent = object
    event_api.filter = types.SimpleNamespace(
        command=lambda name: lambda handler: handler,
        regex=lambda pattern: lambda handler: handler)
    star_api = types.ModuleType('astrbot.api.star')
    class Star:
        def __init__(self, context): pass
    star_api.Context = object
    star_api.Star = Star
    star_api.register = lambda *args: lambda cls: cls
    api = types.ModuleType('astrbot.api')
    api.AstrBotConfig = dict
    api.logger = types.SimpleNamespace(info=lambda *args: None, error=lambda *args: None)
    components = types.ModuleType('astrbot.api.message_components')
    components.At = lambda **kwargs: ('at', kwargs['qq'])
    components.Plain = lambda **kwargs: ('plain', kwargs['text'])
    for name, value in [('astrbot', types.ModuleType('astrbot')), ('astrbot.api', api),
                        ('astrbot.api.event', event_api), ('astrbot.api.star', star_api),
                        ('astrbot.api.message_components', components)]:
        monkeypatch.setitem(sys.modules, name, value)
    package = types.ModuleType('_plugin_test')
    package.__path__ = [str(Path(__file__).resolve().parents[1])]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    module = importlib.import_module('_plugin_test.main')
    return module.MyPlugin(None, {})


class Event:
    message_str = '/rating https://game.maj-soul.com/1/?paipu=260101-abcdef12'
    def get_sender_id(self): return '123'
    def get_group_id(self): return ''
    def plain_result(self, text): return text
    def chain_result(self, chain): return chain


async def test_command_reply_cooldown_and_validation(plugin, monkeypatch):
    async def analyze(record):
        assert record.source == '雀魂'
        return '测试分析结果'
    monkeypatch.setattr(plugin.service, 'analyze', analyze)
    replies = [r async for r in plugin.rating(Event())]
    assert len(replies) == 2 and replies[-1] == '测试分析结果'
    assert not plugin.tasks
    assert '60 秒' in [r async for r in plugin.rating(Event())][0]
    event = Event(); event.message_str = '/rating'
    assert '有效' in [r async for r in plugin.rating(event)][0]


async def test_disabled_detection_and_internal_errors(plugin, monkeypatch):
    plugin.config['auto_detect'] = False
    assert [r async for r in plugin.record_link(Event())] == []
    async def fail(record): raise RuntimeError('secret-in-browser-exception')
    monkeypatch.setattr(plugin.service, 'analyze', fail)
    replies = [r async for r in plugin.rating(Event())]
    assert '内部错误' in replies[-1] and 'secret' not in replies[-1]


async def test_group_mentions_requester(plugin, monkeypatch):
    async def analyze(record): return '结果'
    monkeypatch.setattr(plugin.service, 'analyze', analyze)
    event = Event()
    event.get_group_id = lambda: '456'
    replies = [r async for r in plugin.rating(event)]
    assert replies[-1] == [('at', '123'), ('plain', '\n结果')]


def test_captcha_configuration(plugin, monkeypatch):
    monkeypatch.delenv('TWOCAPTCHA_API_KEY', raising=False)
    assert plugin._make_browser().captcha_solver is None
    plugin.config['captcha_provider'] = '2captcha'
    with pytest.raises(Exception, match='API Key'):
        plugin._make_browser()
    plugin.config['twocaptcha_api_key'] = 'test-config-key'
    plugin.config['twocaptcha_max_tasks'] = 2
    browser = plugin._make_browser()
    assert browser.captcha_solver.max_tasks == 2
    monkeypatch.setenv('TWOCAPTCHA_API_KEY', 'test-env-key')
    assert plugin._make_browser().captcha_solver._api_key == 'test-env-key'


async def test_terminate_cancels_active_analysis(plugin, monkeypatch):
    started = asyncio.Event()
    cleaned = asyncio.Event()
    async def analyze(record):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()
    monkeypatch.setattr(plugin.service, 'analyze', analyze)
    generator = plugin.rating(Event())
    await anext(generator)
    await started.wait()
    await plugin.terminate()
    assert cleaned.is_set() and not plugin.tasks and plugin.closed
    await generator.aclose()
