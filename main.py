"""AstrBot + OneBot v11/NapCat 牌谱 Rating 插件。"""
import asyncio
import time

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Plain
from astrbot.api.star import Context, Star, register

from .mortal.service import RatingService, parse_record


@register("astrbot_plugin_rating", "Alexsssssssssssss", "雀魂/天凤 Mortal Rating 查询", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.service = RatingService(max_pending=int(config.get("max_pending", 3)))
        self.last_query = {}
        self.tasks = set()
        self.closed = False

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
        if user in self.last_query:
            yield event.plain_result(f"每位用户每 {cooldown} 秒可提交一次，请稍后再试。")
            return
        if self.service.pending >= self.service.max_pending:
            yield event.plain_result("分析队列已满，请稍后重试。")
            return
        self.last_query[user] = now
        task = asyncio.create_task(self.service.analyze(record))
        self.tasks.add(task)
        try:
            yield event.plain_result("已收到牌谱，等待串行分析四个座位，可能需要数分钟。")
            try:
                result = await task
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
