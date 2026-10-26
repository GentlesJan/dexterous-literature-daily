"""Selection, local previews and sent-only delivery history."""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
import base64
import json
import os
from pathlib import Path
import re
from .deep_review import arxiv_id


def paper_key(paper):
    if paper.source == 'arxiv':
        return 'arxiv:' + re.sub(r'v\d+$', '', arxiv_id(paper.url))
    return paper.source + ':' + paper.url


def matches_research(text, research):
    text = re.sub(r"[‐‑–—]", "-", text.lower())
    def contains(term):
        term = str(term).lower()
        return bool(re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', text))
    keywords = research.get('keywords', [])
    rsi = research.get('rsi', {})
    if not keywords and not rsi:
        return True
    dexterous = any(str(word).lower() in text for word in keywords)
    self_improvement = (any(contains(word) for word in rsi.get('context', []))
                        and any(contains(word) for word in rsi.get('keywords', [])))
    return dexterous or self_improvement


def select_candidates(papers, research, seen):
    result, keys = [], set(seen)
    max_age = research.get('max_age_days')
    cutoff = datetime.now(timezone.utc) - timedelta(days=float(max_age or 4))
    for paper in papers:
        key = paper_key(paper)
        if key in keys:
            continue
        text = (paper.title + ' ' + paper.abstract).lower().replace('–', '-').replace('‑', '-')
        if not matches_research(text, research):
            continue
        if max_age:
            try:
                published = datetime.fromisoformat(paper.published.replace('Z', '+00:00'))
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                if published < cutoff or published > datetime.now(timezone.utc) + timedelta(days=1):
                    continue
            except (ValueError, AttributeError):
                continue  # Unknown dates cannot be advertised as new papers.
        keys.add(key)
        result.append(paper)
    return result


def load_sent(path):
    if not path or not Path(path).exists():
        return set()
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError('Invalid sent history; refusing to silently reset it')
    return set(value)


def mark_sent(path, papers):
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    state = load_sent(path) | {paper_key(p) for p in papers}
    temp = target.with_suffix('.tmp')
    temp.write_text(json.dumps(sorted(state)), encoding='utf-8')
    temp.replace(target)


@contextmanager
def run_lock(state_path):
    if not state_path:
        yield
        return
    lock = Path(str(state_path) + '.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(f'Another run is active, or a stale lock remains: {lock}')
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def save_preview(root, papers, html, failures):
    if not root:
        return None
    folder = Path(root) / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S-%fZ')
    folder.mkdir(parents=True, exist_ok=False)
    from .construct_email import render_email
    (folder / 'digest.html').write_text(render_email(papers, interactive=True), encoding='utf-8')
    (folder / 'email.html').write_text(html, encoding='utf-8')
    records = []
    for index, paper in enumerate(papers):
        record = asdict(paper)
        # Keep exact extracted source for checking the generated claims.
        source_file = f'paper-{index + 1}-source.txt'
        (folder / source_file).write_text(paper.full_text or paper.abstract, encoding='utf-8')
        record.pop('full_text', None)
        record['source_file'] = source_file
        for num, figure in enumerate(record['figures']):
            if data := figure.pop('image_base64', None):
                image_file = f'paper-{index + 1}-figure-{num + 1}.png'
                (folder / image_file).write_bytes(base64.b64decode(data))
                figure['image_file'] = image_file
        records.append(record)
    (folder / 'papers.json').write_text(json.dumps({'papers': records, 'failures': failures},
                                                 ensure_ascii=False, indent=2), encoding='utf-8')
    return folder
