import base64
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest
from omegaconf import OmegaConf

from zotero_arxiv_daily import deep_review as review
from zotero_arxiv_daily.construct_email import render_email
from zotero_arxiv_daily.digest_state import load_sent, mark_sent, paper_key, select_candidates, run_lock
from zotero_arxiv_daily.protocol import Paper
from zotero_arxiv_daily.executor import Executor


def paper(identifier='2601.12345v1', **kwargs):
    return Paper(source='arxiv', title='Dexterous robot hand', authors=['A'],
                 abstract='We use tactile sensing.', url=f'https://arxiv.org/abs/{identifier}',
                 published=datetime.now(timezone.utc).isoformat(), **kwargs)


def response(quote='We use tactile sensing.'):
    return json.dumps({key: {'summary': '触觉反馈', 'evidence': quote, 'location': 'Abstract'} for key in review.SECTIONS})


def test_untraceable_claim_is_replaced():
    result = review.validate_review(response('Imagined result 98%'), 'Actual paper.')
    assert all(not v['evidence_verified'] for v in result.values())
    assert all('证据不足' in v['summary'] for v in result.values())


def test_valid_quote_and_missing_field():
    result = review.validate_review(response(), 'We use\n tactile sensing.')
    assert result['method']['evidence_verified']
    with pytest.raises(ValueError):
        review.validate_review('{}', 'text')


def test_parse_html_only_uses_original_candidates_and_includes_table():
    doc = '''<article><p>''' + 'Full paper text. ' * 30 + '''</p>
    <table><tr><td>Success 80%</td></tr></table>
    <figure id="F1"><img src="/html/2601.12345v1/x1.png"><figcaption>Figure 1: Overview of grasping.</figcaption></figure>
    <figure id="F2"><img src="https://arxiv.org/html/2601.12345v1/x2.png"><figcaption>Figure 2: Policy architecture.</figcaption></figure>
    <figure><img src="https://evil.example/x.png"><figcaption>Pipeline</figcaption></figure></article>'''
    text, figures = review.parse_html(doc, 'https://arxiv.org/html/2601.12345v1')
    assert 'Success 80%' in text
    assert {f['kind'] for f in figures} == {'teaser', 'pipeline'}
    assert len(figures) == 2


def test_enrich_abstract_fallback(monkeypatch):
    monkeypatch.setattr(review, 'download', lambda *a: (_ for _ in ()).throw(ValueError('no html')))
    monkeypatch.setattr('zotero_arxiv_daily.retriever.arxiv_retriever._run_with_hard_timeout', lambda *a, **k: None)
    p = paper()
    review.enrich(p, {})
    assert p.source_level == 'abstract'
    assert not p.full_text


def test_pdf_candidate_is_original_page(monkeypatch):
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((40, 60), 'Figure 1: Overview of robotic grasping pipeline.')
    page.draw_rect((40, 100, 400, 300), color=(0, 0, 1))
    data = doc.tobytes()
    doc.close()
    monkeypatch.setattr(review, 'download', lambda *a: data)
    text, figures, truncated = review._pdf_worker('https://arxiv.org/pdf/2601.12345', 2, 10)
    assert 'PDF page 1' in text
    assert figures[0]['extraction'] == 'pdf_page'
    assert base64.b64decode(figures[0]['image_base64']).startswith(b'\x89PNG')
    assert not truncated


def test_long_input_keeps_end_experiments():
    text, truncated = review.prepare_text('start ' + 'middle ' * 5000 + 'end-experiment-result', 1000)
    assert truncated and 'INPUT OMITTED' in text and 'end-experiment-result' in text


@pytest.mark.parametrize('api_mode', ['chat_completion', 'response'])
def test_analysis_request_and_validation(api_mode, monkeypatch):
    calls = []
    def request(client, params, messages):
        calls.append(params)
        return response()
    monkeypatch.setattr(review, '_request_llm', request)
    p = paper()
    review.analyze(p, None, {'api_mode': api_mode, 'generation_kwargs': {'model': 'test'}}, {'output_format': 'json_schema'})
    assert p.analysis['method']['evidence_verified']
    kwargs = calls[0]['generation_kwargs']
    assert ('text' in kwargs) if api_mode == 'response' else ('response_format' in kwargs)


def test_date_topic_and_version_dedup():
    first = paper()
    updated = paper('2601.12345v2')
    old = paper('2601.23456v1')
    old.published = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    irrelevant = paper('2601.34567v1')
    irrelevant.title = 'Language model'
    options = {'keywords': ['dexterous'], 'max_age_days': 4}
    assert select_candidates([first, updated, old, irrelevant], options, set()) == [first]
    assert select_candidates([updated], options, {paper_key(first)}) == []


def test_exclusive_lock_and_sent_state(tmp_path):
    path = tmp_path / 'sent.json'
    with run_lock(path):
        with pytest.raises(RuntimeError):
            with run_lock(path):
                pass
    mark_sent(path, [paper()])
    assert load_sent(path) == {'arxiv:2601.12345'}


def test_render_escapes_paper_and_analysis():
    p = paper()
    p.title = '<script>bad()</script>'
    p.source_level = 'abstract'
    p.analysis = review.validate_review(response(), p.abstract)
    p.analysis['details']['summary'] = '<img onerror="bad()">'
    rendered = render_email([p])
    assert '<script>' not in rendered and '<img onerror=' not in rendered
    assert '仅摘要' in rendered


@pytest.mark.parametrize('dry_run, smtp_fails', [(True, False), (False, True), (False, False)])
def test_delivery_history_only_after_success(tmp_path, monkeypatch, dry_run, smtp_fails):
    executor = Executor.__new__(Executor)
    executor.config = OmegaConf.create({
        'zotero': {'enabled': False},
        'research': {'profile': 'dexterous hands', 'keywords': ['dexterous'], 'max_age_days': 4},
        'executor': {'state_file': str(tmp_path / 'sent.json'), 'output_dir': str(tmp_path / 'digests'),
                     'dry_run': dry_run, 'max_paper_num': 1, 'send_empty': False},
        'analysis': {'enabled': True}, 'llm': {},
    })
    executor.retrievers = {'arxiv': SimpleNamespace(retrieve_papers=lambda: [paper()])}
    executor.reranker = SimpleNamespace(rerank=lambda p, c: p)
    executor.openai_client = None
    monkeypatch.setattr('zotero_arxiv_daily.executor.enrich', lambda *a: None)
    def analyze(p, *args):
        p.analysis = review.validate_review(response(), p.abstract)
    monkeypatch.setattr('zotero_arxiv_daily.executor.analyze', analyze)
    sends = []
    def send(*args):
        sends.append(True)
        if smtp_fails:
            raise OSError('SMTP unavailable')
    monkeypatch.setattr('zotero_arxiv_daily.executor.send_email', send)
    if smtp_fails:
        with pytest.raises(OSError):
            executor.run()
    else:
        executor.run()
    assert bool(sends) == (not dry_run)
    assert bool(load_sent(tmp_path / 'sent.json')) == (not dry_run and not smtp_fails)
    assert list((tmp_path / 'digests').glob('*/papers.json'))


def test_metadata_mode_does_not_download_fulltext(config, monkeypatch):
    from omegaconf import open_dict
    from zotero_arxiv_daily.retriever.arxiv_retriever import ArxivRetriever
    with open_dict(config):
        config.source.arxiv.metadata_only = True
    def unexpected(*args):
        pytest.fail('Downloaded full text before selection')
    for name in ('extract_text_from_tar', 'extract_text_from_html', 'extract_text_from_pdf'):
        monkeypatch.setattr('zotero_arxiv_daily.retriever.arxiv_retriever.' + name, unexpected)
    raw = SimpleNamespace(title='Title', authors=[], summary='abstract', pdf_url='https://arxiv.org/pdf/2601.12345',
                          entry_id='https://arxiv.org/abs/2601.12345', published=datetime.now(timezone.utc))
    assert ArxivRetriever(config).convert_to_paper(raw).full_text is None


def test_robotics_boolean_env_and_no_secret_logging(monkeypatch):
    from pathlib import Path
    from hydra import compose, initialize_config_dir
    from run_robotics import validate_config
    monkeypatch.setenv('ZOTERO_ENABLED', 'false')
    with initialize_config_dir(config_dir=str(Path(__file__).resolve().parents[1] / 'config'), version_base=None):
        cfg = compose(config_name='robotics')
    assert cfg.zotero.enabled is False
    with pytest.raises(ValueError, match='llm.api'):
        validate_config(cfg)


def test_inline_pdf_image_and_tls_failure(config, monkeypatch):
    import smtplib
    from email import message_from_string
    from omegaconf import open_dict
    from zotero_arxiv_daily.utils import send_email
    with open_dict(config):
        config.email.security = 'ssl'
    sent = []
    class SMTP:
        def __init__(self, *a, **kw):
            assert kw['context'].check_hostname
        def login(self, *args, **kwargs):
            assert kwargs['initial_response_ok'] is False
        def sendmail(self, sender, receiver, message):
            sent.append(message)
            return {}
        def quit(self):
            pass
    monkeypatch.setattr(smtplib, 'SMTP_SSL', SMTP)
    encoded = base64.b64encode(b'fake png test content').decode()
    send_email(config, f'<img src="data:image/png;base64,{encoded}">')
    message = message_from_string(sent[0])
    parts = list(message.walk())
    assert any(p.get_content_type() == 'image/png' and p['Content-ID'] for p in parts)
    html = next(p for p in parts if p.get_content_type() == 'text/html').get_payload(decode=True)
    assert b'cid:paper-figure-0@digest' in html
    monkeypatch.setattr(smtplib, 'SMTP_SSL', lambda *a, **k: (_ for _ in ()).throw(OSError('TLS unavailable')))
    monkeypatch.setattr(smtplib, 'SMTP', lambda *a, **k: pytest.fail('Unexpected insecure fallback'))
    with pytest.raises(OSError):
        send_email(config, 'test')


def test_rss_metadata_request_has_timeout(config, monkeypatch):
    from pathlib import Path
    from omegaconf import open_dict
    from zotero_arxiv_daily.retriever.arxiv_retriever import ArxivRetriever
    with open_dict(config):
        config.source.arxiv.metadata_only = True
    payload = (Path(__file__).parent / 'retriever' / 'arxiv_rss_example.xml').read_bytes()
    def get(url, **kwargs):
        assert kwargs['timeout'] == (10, 60)
        return SimpleNamespace(content=payload, raise_for_status=lambda: None)
    monkeypatch.setattr('zotero_arxiv_daily.retriever.arxiv_retriever.requests.get', get)
    result = ArxivRetriever(config).retrieve_papers()
    assert result and all(p.full_text is None for p in result)
