"""AstrBot + OneBot v11/NapCat 牌谱 Rating 插件。"""
import asyncio
import os
import time

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Plain
from astrbot.api.star import Context, Star, register

from .mortal.service import RatingService, parse_record
from .mortal.browser import MortalBrowser
from .mortal.captcha import TurnstileSolver
from .mortal.reports import AnalysisError


@register("astrbot_plugin_rating", "Alexsssssssssssss", "雀魂/天凤 Mortal Rating 查询", "1.2.1")
class MyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.service = RatingService(browser_factory=self._make_browser,
                                     max_pending=int(config.get("max_pending", 3)))
        self.last_query = {}
        self.tasks = set()
        self.closed = False
        self.user_tasks = {}

    def _make_browser(self):
        provider = self.config.get("captcha_provider", "manual")
        if provider == "manual":
            return MortalBrowser()
        if provider != "2captcha":
            raise AnalysisError("captcha_provider 必须为 manual 或 2captcha。")
        key = os.getenv("TWOCAPTCHA_API_KEY") or self.config.get("twocaptcha_api_key", "")
        return MortalBrowser(captcha_solver=TurnstileSolver(
            key, timeout=self.config.get("twocaptcha_timeout", 180),
            max_tasks=self.config.get("twocaptcha_max_tasks", 4),
            proxy=self.config.get("twocaptcha_proxy", ''),
            request_timeout=self.config.get("twocaptcha_request_timeout", 30)))

    async def initialize(self):
        logger.info("Rating 插件已加载；使用 /rating 牌谱链接，默认分析四个座位。")

    async def _query(self, event):
        if self.closed:
            yield event.plain_result("插件正在卸载，请稍后重试。")
            return
        try:
            record = parse_record(event.message_str)
        except ValueError as exc:
            yield event.plain_result(str(exc))
            return
        cooldown = max(0, int(self.config.get("cooldown_seconds", 60)))
        now = time.monotonic()
        self.last_query = {k: v for k, v in self.last_query.items() if now - v < cooldown}
        user = str(event.get_sender_id())
        if user in self.user_tasks and not self.user_tasks[user].done():
            yield event.plain_result('你已有查询正在进行，发送 /rating_cancel 可取消。')
            return
        if user in self.last_query:
            yield event.plain_result(f"每位用户每 {cooldown} 秒可提交一次，请稍后再试。")
            return
        if self.service.pending >= self.service.max_pending:
            yield event.plain_result("分析队列已满，请稍后重试。")
            return
        self.last_query[user] = now
        updates = asyncio.Queue()
        started = time.monotonic()
        state = {'stage': '等待进入分析队列'}
        def progress(message):
            state['stage'] = message.split('\n', 1)[0]
            updates.put_nowait(message)
        task = asyncio.create_task(self.service.analyze(
            record, progress=progress,
            total_timeout=max(30, int(self.config.get('analysis_timeout', 900))),
            seat_timeout=max(10, int(self.config.get('seat_timeout', 360)))))
        task.add_done_callback(lambda finished: updates.put_nowait(None))
        self.tasks.add(task)
        self.user_tasks[user] = task
        try:
            yield event.plain_result("已收到牌谱，将串行分析四个座位并发送进度；发送 /rating_cancel 可取消。")
            try:
                interval = max(10, min(120, int(self.config.get('progress_interval', 30))))
                while True:
                    try:
                        message = await asyncio.wait_for(updates.get(), timeout=interval)
                    except TimeoutError:
                        elapsed = int(time.monotonic() - started)
                        yield event.plain_result(f"分析进度：{state['stage']}，已用时 {elapsed} 秒。")
                        continue
                    if message is None:
                        break
                    yield event.plain_result('分析进度：' + message)
                result = await task
            except asyncio.CancelledError:
                if self.closed or asyncio.current_task().cancelling():
                    raise
                result = '查询已取消；已创建的 2Captcha 任务仍可能计费。'
            except Exception:
                # Playwright 原始异常可能含完整请求参数，不转发给群聊。
                logger.error("Rating 分析发生内部错误，请检查浏览器安装和服务配置。")
                result = "分析服务发生内部错误，请管理员检查浏览器和依赖配置。"
            if event.get_group_id():
                yield event.chain_result([At(qq=event.get_sender_id()), Plain(text='\n' + result)])
            else:
                yield event.plain_result(result)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self.tasks.discard(task)
            if self.user_tasks.get(user) is task:
                del self.user_tasks[user]

    @filter.command("rating_cancel")
    async def rating_cancel(self, event: AstrMessageEvent):
        """取消自己当前的查询。"""
        task = self.user_tasks.get(str(event.get_sender_id()))
        if task is None or task.done():
            yield event.plain_result('你没有正在进行的查询。')
            return
        task.cancel()
        yield event.plain_result('已请求取消查询，正在清理浏览器；已创建的验证任务仍可能计费。')

    @filter.command("rating")
    async def rating(self, event: AstrMessageEvent):
        """发送 /rating 雀魂或天凤牌谱链接，查询桌上四人的 Rating。"""
        async for result in self._query(event):
            yield result

    @filter.regex(r"^https://(?:game\.maj-soul\.com|mahjongsoul\.game\.yo-star\.com|game\.mahjongsoul\.com|tenhou\.net)/")
    async def record_link(self, event: AstrMessageEvent):
        """识别直接发送的牌谱链接；可在插件设置中关闭。"""
        if self.config.get("auto_detect", True):
            async for result in self._query(event):
                yield result

    async def terminate(self):
        self.closed = True
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
        self.user_tasks.clear()
