import copy
import pytest
from mortal.reports import AnalysisError, parse_json_report, parse_html_report, log_matches


def test_json_scale_and_actual_probabilities(report):
    r = parse_json_report(report, 1)
    assert r['rating'] == pytest.approx(90.25)
    assert r['agreement'] == pytest.approx(200/3)
    assert r['bad10'] == pytest.approx(100/3)
    assert r['bad5'] == pytest.approx(100/3)


def test_html_same_metrics(html_report):
    r = parse_html_report(html_report, 1)
    assert r['rating'] == 90.25 and r['total_matches'] == 2
    assert r['bad10'] is None and r['player_id'] == 1


def test_missing_rating_is_not_inferred(html_report):
    with pytest.raises(AnalysisError, match='未公开 Rating'):
        parse_html_report(html_report.replace('<dt>rating</dt><dd>90.25</dd>', ''), 1)


@pytest.mark.parametrize('value', [None, True, -1, 1.1, float('nan'), float('inf')])
def test_rejects_invalid_rating(report, value):
    report['review']['rating'] = value
    with pytest.raises(AnalysisError): parse_json_report(report, 1)


def test_wrong_actor_and_zero_decisions(report, html_report):
    with pytest.raises(AnalysisError): parse_json_report(report, 2)
    with pytest.raises(AnalysisError): parse_html_report(html_report, 2)
    report['review']['total_reviewed'] = 0
    with pytest.raises(AnalysisError): parse_json_report(report, 1)


def test_log_identity_exact():
    assert log_matches('uuid', 'https://game.maj-soul.com/1/?paipu=uuid_a123')
    assert log_matches('uuid', 'uuid')
    assert not log_matches('uuid', 'uuid-other')
    assert not log_matches('uuid', None)


def test_raw_json_and_english_report(report, html_report):
    import json
    from mortal.reports import parse_report_payload
    assert parse_report_payload(json.dumps(report), 1)['rating'] == 90.25
    html = html_report.replace('AI 引擎', 'AI engine').replace('玩家 ID', 'player id').replace('牌谱 ID', 'log id').replace('AI 一致率', 'matches/total')
    assert parse_report_payload(html, 1)['total_matches'] == 2


def test_error_pages_are_terminal():
    from mortal.reports import parse_report_payload, ReportError
    with pytest.raises(ReportError, match='验证失败'):
        parse_report_payload('<title>Error</title><p>Invalid Turnstile token</p>', 1)
    with pytest.raises(ReportError, match='未被接受'):
        parse_report_payload('<form name="reviewForm"></form>', 1)
