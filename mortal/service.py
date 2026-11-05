"""直接分析用户给出的牌谱；不经过牌谱屋，也不需要其 Bearer token。"""
import asyncio
import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

from bs4 import BeautifulSoup
from .browser import MortalBrowser
from .reports import AnalysisError


@dataclass(frozen=True)
class Record:
    log_id: str
    url: str
    source: str


def parse_record(text: str) -> Record:
    links = re.findall(r'https?://[^\s<>"\u3000]+', text)
    records = []
    for raw in links:
        raw = raw.rstrip('，。；！）)]')
        try:
            u = urlsplit(raw)
            if u.username or u.password or u.port not in (None, 443) or u.scheme != 'https':
                continue
            q = parse_qs(u.query)
            if u.hostname in {'game.maj-soul.com', 'mahjongsoul.game.yo-star.com', 'game.mahjongsoul.com'}:
                values = q.get('paipu', [])
                if len(values) != 1 or not re.fullmatch(r'[A-Za-z0-9-]{8,128}(?:_a\d+)?', values[0]):
                    continue
                log_id = re.sub(r'_a\d+$', '', values[0])
                records.append(Record(log_id, f'https://{u.hostname}/1/?' + urlencode({'paipu': values[0]}), '雀魂'))
            elif u.hostname == 'tenhou.net':
                values = q.get('log', [])
                if len(values) != 1 or not re.fullmatch(r'\d{10}gm-[A-Za-z0-9-]{8,100}', values[0]):
                    continue
                records.append(Record(values[0], 'https://tenhou.net/0/?' + urlencode({'log': values[0]}), '天凤'))
        except ValueError:
            continue
    records = list(dict.fromkeys(records))
    if len(records) != 1:
        raise ValueError('请一次发送一个有效的 HTTPS 雀魂或天凤牌谱链接。')
    return records[0]


def player_name(html: str, seat: int) -> str:
    soup = BeautifulSoup(html, 'html.parser')
    # Classic 报告的牌谱播放器内含 Tenhou 格式 JSON（包括四名玩家）。
    for frame in soup.select('iframe[src]'):
        source = urlsplit(frame['src'])
        if source.hostname != 'tenhou.net' or not source.fragment.startswith('json='):
            continue
        try:
            data = json.loads(unquote(source.fragment[5:]))
            names = data.get('name', [])
            if isinstance(names, list) and len(names) == 4 and isinstance(names[seat], str):
                name = names[seat].strip().replace('\n', ' ').replace('\r', ' ')
                if name:
                    return name[:80]
        except (ValueError, AttributeError, IndexError):
            continue
    for dt in soup.select('dt'):
        if dt.get_text(' ', strip=True).casefold() in {'玩家名称', '玩家名', 'player name', 'プレイヤー名'}:
            dd = dt.find_next_sibling('dd')
            if dd:
                return dd.get_text(' ', strip=True)[:80].replace('\n', ' ')
    return ('东家', '南家', '西家', '北家')[seat]


def format_result(result: dict, name: str) -> str:
    text = (f"{name}: Rating: {result['rating']:.2f} 一致率: "
            f"{result['agreement']:.1f} ({result['total_matches']}/{result['total_reviewed']})")
    url = result.get('report_url', '')
    u = urlsplit(url)
    if u.scheme == 'https' and u.netloc == 'mjai.ekyu.moe' and u.path.startswith(('/report/', '/review/', '/killerducky/')):
        text += f'\n报告：\n{url}'
    else:
        text += '\n报告：网站未提供可验证的独立报告链接。'
    return text


class RatingService:
    """同一进程只运行一组浏览器任务；队列上限防止群消息耗尽资源。"""
    def __init__(self, browser_factory=MortalBrowser, max_pending=3):
        self.lock = asyncio.Lock()
        self.pending = 0
        self.browser_factory = browser_factory
        self.max_pending = max(1, min(20, max_pending))
        self.last_submit = 0

    async def analyze(self, record: Record, seats=(0, 1, 2, 3)) -> str:
        if self.pending >= self.max_pending:
            return '分析队列已满，请稍后重试。'
        self.pending += 1
        lines = ['牌谱分析结果', '引擎: mortal']
        try:
            async with self.lock:
                async with self.browser_factory() as browser:
                    browser.last_submit = self.last_submit
                    for seat in seats:
                        game = {'uuid': record.log_id, 'game_id': record.log_id,
                                'record_url': record.url, 'seat': seat, 'masked': False, 'mode_id': None}
                        try:
                            result, html = await browser.analyze(game)
                        except AnalysisError as exc:
                            # 不对同一挑战/限流继续发起另外三个请求。
                            lines.append(f'{("东家", "南家", "西家", "北家")[seat]}未完成：{exc}')
                            lines.append('后续座位已停止；以上成功结果保留。')
                            break
                        finally:
                            self.last_submit = getattr(browser, 'last_submit', self.last_submit)
                        lines.append(f"模型: {result.get('model_tag', '未知')}")
                        lines.append(format_result(result, player_name(html, seat)))
        except AnalysisError as exc:
            lines.append(f'分析未完成：{exc}')
        finally:
            self.pending -= 1
        return '\n'.join(lines)
