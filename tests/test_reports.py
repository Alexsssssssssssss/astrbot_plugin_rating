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


def test_response_summary_never_contains_field_values():
    from mortal.reports import response_summary
    secret = 'secret-token-should-not-leak'
    html = f'<title>{secret}</title><dl><dt>rating</dt><dd>{secret}</dd></dl><script>{secret}</script>'
    summary = response_summary(html)
    assert secret not in summary and 'Rating' in summary and 'script=1' in summary
    assert secret not in response_summary('{"engine":"' + secret + '"}')


def test_actual_report_minified_metadata():
    from pathlib import Path
    from mortal.reports import parse_report_payload, response_summary
    html = (Path(__file__).parent / 'fixtures/mortal_minified_metadata.html').read_text()
    result = parse_report_payload(html, 0)
    assert result['rating'] == 92.419
    assert result['total_matches'] == 138 and result['total_reviewed'] == 162
    assert result['agreement'] == pytest.approx(138/162*100)
    assert result['log_id'] is None  # 不凭空补造未在页面内提供的 ID。
    assert '引擎,座位,Rating,一致率' in response_summary(html)
    with pytest.raises(AnalysisError, match='座位'):
        parse_report_payload(html, 1)


@pytest.mark.parametrize('end_tags', ['both', 'dt', 'dd'])
def test_optional_metadata_end_tags(html_report, end_tags):
    from mortal.reports import parse_html_report
    if end_tags in ('both', 'dt'): html_report = html_report.replace('</dt>', '')
    if end_tags in ('both', 'dd'): html_report = html_report.replace('</dd>', '')
    result = parse_html_report(html_report, 1)
    assert result['rating'] == 90.25 and result['log_id'] == 'test-game-001'
