"""严格解析 mjai-reviewer 原始 JSON / HTML，不猜测不存在的 Rating。"""
import math
import json
import re
from html.parser import HTMLParser

from bs4 import BeautifulSoup
from urllib.parse import parse_qs, urlsplit


class AnalysisError(Exception):
    pass


class ReportError(AnalysisError):
    """服务器明确返回的终止错误，不应重试解析直到超时。"""


class _MetadataParser(HTMLParser):
    """dt/dd 的结束标签可省略；不能依赖 html.parser 的兄弟节点树。"""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fields = {}
        self.kind = None
        self.parts = []
        self.label = None

    def finish_field(self):
        text = ' '.join(part.strip() for part in self.parts if part.strip())
        if self.kind == 'dt':
            self.label = text.casefold()
        elif self.kind == 'dd' and self.label is not None:
            self.fields[self.label] = text
            self.label = None
        self.kind = None
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('dt', 'dd'):
            self.finish_field()
            self.kind = tag
        elif tag == 'dl':
            self.finish_field()
            self.label = None

    def handle_endtag(self, tag):
        if tag == self.kind:
            self.finish_field()
        elif tag == 'dl':
            self.finish_field()
            self.label = None

    def handle_data(self, data):
        if self.kind:
            self.parts.append(data)


def extract_metadata(html):
    parser = _MetadataParser()
    parser.feed(html)
    parser.close()
    parser.finish_field()
    return parser.fields


def response_summary(content):
    """只报告结构和已知字段名，不包含正文、字段值、URL 或密钥。"""
    labels = []
    kind = 'HTML'
    if content.lstrip().startswith(('{', '[')):
        kind = 'JSON'
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                labels = [key for key in ('engine', 'player_id', 'log_id', 'review', 'error', 'status') if key in data]
        except ValueError:
            kind = '无效 JSON'
        extra = ''
    else:
        soup = BeautifulSoup(content, 'html.parser')
        keys = set(extract_metadata(content))
        for label, aliases in (
            ('引擎', {'ai 引擎', 'ai engine', 'engine', 'ai', 'ai 엔진'}),
            ('座位', {'玩家 id', 'player id', 'プレイヤーid', '작사 id'}),
            ('Rating', {'rating'}),
            ('一致率', {'ai 一致率', 'matches/total', 'ai一致率', 'ai 일치율'}),
            ('牌谱ID', {'牌谱 id', 'log id', 'ログid', '로그 id'}),
        ):
            if keys & aliases:
                labels.append(label)
        extra = (f"；iframe={len(soup.select('iframe'))}；script={len(soup.select('script'))}"
                 f"；检讨表单={'有' if soup.select_one('form[name=reviewForm]') else '无'}")
    return f"响应摘要：{kind}，正文 {len(content.encode('utf-8'))} 字节；已知字段={','.join(labels) or '无'}{extra}"


def parse_report_payload(content, expected_seat=None):
    if content.lstrip().startswith(('{', '[')):
        try:
            data = json.loads(content)
        except ValueError as exc:
            raise ReportError('网站返回的报告 JSON 无法解析。') from exc
        if not isinstance(data, dict):
            raise ReportError('网站返回的报告 JSON 结构不正确。')
        try:
            return parse_json_report(data, expected_seat)
        except AnalysisError as exc:
            raise ReportError(str(exc)) from exc
    soup = BeautifulSoup(content, 'html.parser')
    heading = soup.title.get_text(' ', strip=True) if soup.title else ''
    h1 = soup.find('h1')
    if h1:
        heading += ' ' + h1.get_text(' ', strip=True)
    text = soup.get_text(' ', strip=True).casefold()
    if re.search(r'error|错误|出错|failed', heading, re.I):
        if any(word in text for word in ('captcha', 'turnstile', '验证码', '验证失败')):
            raise ReportError('Mortal 返回验证失败页面，本次验证结果未被网站接受。')
        raise ReportError('Mortal 返回错误页面，没有生成分析报告。')
    if soup.select_one('form[name="reviewForm"]'):
        raise ReportError('提交后网站重新返回检讨表单，本次提交未被接受。')
    try:
        return parse_html_report(content, expected_seat)
    except AnalysisError as exc:
        if '尚未取得 Mortal 报告' not in str(exc):
            raise ReportError(str(exc)) from exc
        raise


def log_matches(expected_uuid, log_id):
    if not expected_uuid or not isinstance(log_id, str):
        return False
    candidate = log_id.strip()
    if candidate.startswith("https://"):
        url = urlsplit(candidate)
        query = parse_qs(url.query)
        candidate = query.get("log" if url.hostname == "tenhou.net" else "paipu", [""])[0]
    candidate = re.sub(r"_a\d+$", "", candidate)
    return candidate == expected_uuid


def percent(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
        raise AnalysisError("分析结果数值必须在 0–100 之间。")
    return float(value)


def parse_json_report(data, expected_seat=None):
    if str(data.get("engine", "")).lower() != "mortal":
        raise AnalysisError("此报告不是 Mortal 分析结果。")
    if expected_seat is not None and data.get("player_id") != expected_seat:
        raise AnalysisError("报告分析的玩家座位与目标用户不符。")
    r = data.get("review", {})
    total, matches = r.get("total_reviewed"), r.get("total_matches")
    if type(total) is not int or type(matches) is not int or total <= 0 or not 0 <= matches <= total:
        raise AnalysisError("报告中的决策总数或一致决策数无效。")
    raw_rating = r.get("rating")
    if isinstance(raw_rating, bool) or not isinstance(raw_rating, (int, float)) or not math.isfinite(raw_rating) or not 0 <= raw_rating <= 1:
        raise AnalysisError("mjai-reviewer JSON 中的 rating 必须为 0–1。")
    rating = percent(raw_rating * 100)
    entries = [e for k in r.get("kyokus", []) for e in k.get("entries", [])]
    # “恶手”采用实际动作的 softmax 概率，而非 Q 损失或一致率补集。
    probabilities = []
    for entry in entries:
        details, idx = entry.get("details", []), entry.get("actual_index")
        if type(idx) is int and 0 <= idx < len(details):
            p = details[idx].get("prob")
            if isinstance(p, (int, float)) and math.isfinite(p) and 0 <= p <= 1:
                probabilities.append(p)
    bad10 = sum(p < .10 for p in probabilities) / total * 100 if len(probabilities) == total else None
    bad5 = sum(p < .05 for p in probabilities) / total * 100 if len(probabilities) == total else None
    return {"rating": rating, "agreement": matches / total * 100, "total_reviewed": total, "total_matches": matches, "bad10": bad10, "bad5": bad5, "model_tag": str(r.get("model_tag", "未知")), "player_id": data.get("player_id"), "log_id": data.get("log_id"), "origin": "mjai-reviewer JSON"}


def parse_html_report(html, expected_seat=None):
    fields = extract_metadata(html)
    engine = next((v for k, v in fields.items() if k in ("ai 引擎", "ai engine", "engine", "aiエンジン", "ai", "ai 엔진")), "")
    if engine.casefold() != "mortal":
        raise AnalysisError("尚未取得 Mortal 报告，或网页格式已变化。")
    seat_text = next((v for k, v in fields.items() if k in ("玩家 id", "player id", "プレイヤー id", "プレイヤーid", "작사 id")), "")
    if not seat_text.isdigit() or (expected_seat is not None and int(seat_text) != expected_seat):
        raise AnalysisError("Mortal 报告座位无法验证或与目标用户不符。")
    if "rating" not in fields:
        raise AnalysisError("Mortal 报告未公开 Rating。请启用显示 Rating，或使用本地 mjai-reviewer JSON；不能用一致率代替 Rating。")
    try:
        rating = percent(float(fields["rating"].replace("%", "")))
    except ValueError as exc:
        raise AnalysisError("无法解析报告 Rating。") from exc
    match_text = next((v for k, v in fields.items() if k in ("ai 一致率", "ai match rate", "match rate", "ai一致率", "matches/total", "ai 일치율")), "")
    match = re.search(r"(\d+)\s*/\s*(\d+)", match_text)
    if not match or int(match[2]) <= 0 or int(match[1]) > int(match[2]):
        raise AnalysisError("无法解析报告一致决策数。")
    return {"rating": rating, "agreement": int(match[1]) / int(match[2]) * 100, "total_matches": int(match[1]), "total_reviewed": int(match[2]), "bad10": None, "bad5": None, "model_tag": fields.get("model tag", "未知"), "player_id": int(seat_text), "log_id": next((v for k, v in fields.items() if k in ("牌谱 id", "log id", "ログid", "로그 id")), None), "origin": "Mortal 网站 HTML"}
