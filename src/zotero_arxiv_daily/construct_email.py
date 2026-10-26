from .protocol import Paper
import math
import re
from html import escape
from urllib.parse import urlparse
from .deep_review import SECTIONS


def safe_url(value):
    value = str(value or '')
    return escape(value, quote=True) if urlparse(value).scheme in {'http', 'https'} else '#'


def highlighted(text):
    # Escape before adding our own markup; never render model HTML.
    return re.sub(r"(?<![A-Za-z])\d+(?:\.\d+)?(?:%|秒|条|步|维|自由度| Hz)?",
                  lambda m: '<strong style="color:#0f766e;background:#e6f5f1;padding:0 3px">' + m.group() + '</strong>',
                  escape(text))


def sentences(text):
    return [v.strip() for v in re.split(r'(?<=[。！？])', text) if v.strip()]


def emphasis(text):
    return '<strong style="color:#243247;background-color:#fee2e2;font-weight:600;padding:1px 3px;border-radius:3px;box-decoration-break:clone;-webkit-box-decoration-break:clone">' + highlighted(text) + '</strong>'


def quick_read(paper):
    parts = ['<div style="padding:4px 0 12px;margin-bottom:8px"><div style="font-size:16px;color:#142b49;font-weight:700;padding:0 0 12px;border-bottom:1px solid #e2e8f0">重点速读</div><table role="presentation" style="width:100%;border-collapse:collapse;table-layout:fixed">']
    for key, label in [('problem', '研究背景'), ('method', '核心方法'), ('experiments', '实验看点')]:
        chunks = sentences(paper.analysis[key]['summary'])
        if key == 'experiments':
            chunks = [v for v in chunks if any(w in v for w in ['→', '提升', '提高', '成功率', '优于'])] or chunks
        text = chunks[0] if chunks else ''
        # Keep a complete thought and its motivation, rather than cutting at a colon.
        if key == 'problem' and len(text) < 65 and len(chunks) > 1:
            text += chunks[1]
        parts.append(f'<tr><td style="width:84px;vertical-align:middle;text-align:center;padding:14px 16px 14px 0;border-bottom:1px solid #edf1f5;font-size:14px;font-weight:600;color:#2563eb;line-height:1.85">{label}</td><td style="vertical-align:top;padding:14px 0;border-bottom:1px solid #edf1f5;font-size:13px;font-weight:600;color:#52657c;line-height:1.85;overflow-wrap:anywhere">{escape(text)}</td></tr>')
    parts.append('</table></div>')
    return ''.join(parts)


def figure_section(figure):
    if figure.get('section') in SECTIONS:
        return figure['section']
    text = (figure.get('kind', '') + ' ' + figure.get('caption', '')).lower()
    if any(w in text for w in ['result', 'rollout', 'ablation', 'experiment', '结果', '任务执行']):
        return 'experiments'
    if any(w in text for w in ['pipeline', 'framework', 'architecture', 'workflow', 'hardware', 'mapping', '方法', '控制映射']):
        return 'method'
    return 'problem'


def figure_html(figure):
    source = safe_url(figure['source_url'])
    image = ('data:image/png;base64,' + figure['image_base64']) if figure.get('image_base64') else safe_url(figure.get('url'))
    label = 'PDF 候选整页，非精确裁图' if figure['extraction'] == 'pdf_page' else '论文原图'
    return f'<div style="margin:24px 0"><h3 style="font-size:16px">{escape(figure["kind"])} · {label}</h3><a href="{source}"><img loading="lazy" src="{image}" alt="{escape(figure["kind"])}" style="max-width:100%;height:auto;border:1px solid #e2e8f0"></a><p style="font-size:12px;color:#64748b">{escape(figure["caption"])}</p></div>'


def review_html(paper):
    if paper.analysis is None:
        return ''
    labels = {'html': 'HTML 全文', 'pdf': 'PDF 提取文本', 'abstract': '仅摘要', 'upstream_text': '上游提取文本'}
    parts = ['<div style="padding:24px;background:white;color:#243247;font-size:15px;line-height:1.9">']
    parts.append(f'<p style="font-size:12px;color:#64748b">分析依据：{labels.get(paper.source_level, "未确认")} · <a href="{safe_url(paper.url)}">论文原文</a></p>')
    if paper.published:
        parts.append(f'<p style="font-size:12px;color:#64748b">arXiv 提交时间：{escape(paper.published)}</p>')
    if paper.analysis_truncated:
        parts.append('<p><strong>长文输入已截断，分析可能遗漏未输入的内容。</strong></p>')
    if paper.source_note:
        parts.append(f'<p>{escape(paper.source_note)}</p>')
    for num, (key, label) in enumerate(SECTIONS.items(), 1):
        item = paper.analysis[key]
        parts.append(f'<h2 style="font-size:20px;border-bottom:1px solid #e2e8f0;padding:24px 0 12px;margin:0 0 14px"><span style="color:#2563eb;font-size:14px">0{num}</span>　{label}</h2><ul style="padding-left:22px;margin:0">')
        for index, sentence in enumerate(sentences(item['summary'])):
            key_sentence = (index == 0 and key in {'problem', 'method'}) or (
                key == 'experiments' and any(word in sentence for word in ['→', '提升', '提高', '优于']))
            content = emphasis(sentence) if key_sentence else highlighted(sentence)
            parts.append(f'<li style="padding:5px 0">{content}</li>')
        parts.append('</ul>')
        if item.get('evidence_verified'):
            parts.append(f'<div style="background:#f8fafc;border-left:2px solid #cbd5e1;padding:12px 16px;margin:16px 0 24px;font-size:12px;color:#64748b"><strong>原文证据</strong><p style="margin:6px 0">{escape(item["evidence"])}</p>模型标注位置：{escape(item["location"])}；引文已在输入中定位，结论仍需核实。</div>')
        for figure in paper.figures:
            if figure_section(figure) == key:
                parts.append(figure_html(figure))
        if key in {'problem', 'method', 'experiments'} and not any(figure_section(f) == key for f in paper.figures):
            role = {'problem':'概览 / teaser', 'method':'方法 / pipeline', 'experiments':'实验结果'}[key]
            parts.append(f'<p style="font-size:12px;color:#94a3b8">未找到独立的{role}原图；请查看原文。若一图兼具概览和方法作用，仅在对应章节展示一次。</p>')
    if not paper.figures:
        parts.append('<p>未找到可用的 teaser/pipeline 候选原图。</p>')
    parts.append('<p style="font-size:12px;color:#94a3b8;margin-top:32px">重点摘自详细解析；数字高亮仅辅助阅读，不代表统计显著性。AI 解析请结合原文核实。</p></div>')
    return ''.join(parts)


framework = """
<!DOCTYPE HTML>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility; }
    h1,h2,h3 { font-weight:600; }
    table,td { font-family:inherit; }
    summary::-webkit-details-marker { display:none; }
    .opened { display:none; }
    details[open] > summary .opened { display:inline; }
    details[open] > summary .closed { display:none; }
    summary:focus-visible { outline:3px solid #60a5fa; outline-offset:-3px; }
    @media print { details > * { display:block !important; } }

    .star-wrapper {
      font-size: 1.3em; /* 调整星星大小 */
      line-height: 1; /* 确保垂直对齐 */
      display: inline-flex;
      align-items: center; /* 保持对齐 */
    }
    .half-star {
      display: inline-block;
      width: 0.5em; /* 半颗星的宽度 */
      overflow: hidden;
      white-space: nowrap;
      vertical-align: middle;
    }
    .full-star {
      vertical-align: middle;
    }
  </style>
</head>
<body style="margin:0;background:#f1f5f9;font-family:'Segoe UI','Microsoft YaHei UI','Microsoft YaHei','PingFang SC',sans-serif;padding:24px 12px">

<div style="max-width:860px;margin:0 auto">
    __CONTENT__
</div>

<br><br>
<div>
To unsubscribe, remove your email in your Github Action setting.
</div>

</body>
</html>
"""

def get_empty_html():
  block_template = """
  <table border="0" cellpadding="0" cellspacing="0" width="100%" style="font-family: Arial, sans-serif; border: 1px solid #ddd; border-radius: 8px; padding: 16px; background-color: #f9f9f9;">
  <tr>
    <td style="font-size: 20px; font-weight: bold; color: #333;">
        No Papers Today. Take a Rest!
    </td>
  </tr>
  </table>
  """
  return block_template

def get_block_html(title:str, authors:str, rate:str, tldr:str, pdf_url:str, affiliations:str=None):
    block_template = """
    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="font-family: Arial, sans-serif; border: 1px solid #ddd; border-radius: 8px; padding: 16px; background-color: #f9f9f9;">
    <tr>
        <td style="font-size: 20px; font-weight: bold; color: #333;">
            {title}
        </td>
    </tr>
    <tr>
        <td style="font-size: 14px; color: #666; padding: 8px 0;">
            {authors}
            <br>
            <i>{affiliations}</i>
        </td>
    </tr>
    <tr>
        <td style="font-size: 14px; color: #333; padding: 8px 0;">
            <strong>Relevance:</strong> {rate}
        </td>
    </tr>
    <tr>
        <td style="font-size: 14px; color: #333; padding: 8px 0;">
            <strong>TLDR:</strong> {tldr}
        </td>
    </tr>

    <tr>
        <td style="padding: 8px 0;">
            <a href="{pdf_url}" style="display: inline-block; text-decoration: none; font-size: 14px; font-weight: bold; color: #fff; background-color: #d9534f; padding: 8px 16px; border-radius: 4px;">PDF</a>
        </td>
    </tr>
</table>
"""
    return block_template.format(title=escape(str(title)), authors=escape(str(authors)),rate=escape(str(rate)),
                                 tldr=escape(str(tldr or '')), pdf_url=safe_url(pdf_url), affiliations=escape(str(affiliations or '')))

def get_stars(score:float):
    full_star = '<span class="full-star">⭐</span>'
    half_star = '<span class="half-star">⭐</span>'
    low = 6
    high = 8
    if score <= low:
        return ''
    elif score >= high:
        return full_star * 5
    else:
        interval = (high-low) / 10
        star_num = math.ceil((score-low) / interval)
        full_star_num = int(star_num/2)
        half_star_num = star_num - full_star_num * 2
        return '<div class="star-wrapper">'+full_star * full_star_num + half_star * half_star_num + '</div>'


COLLAPSE_CONTROL = '<div style="padding:16px 24px 24px;text-align:center;border-top:1px solid #e2e8f0"><button type="button" onclick="var card=this.closest(\'details\');card.open=false;card.scrollIntoView({block:\'start\',behavior:\'instant\'});card.querySelector(\'summary\').focus({preventScroll:true});" style="cursor:pointer;padding:8px 16px;border:0;border-radius:0;background:transparent;color:#64748b;font:inherit;font-size:13px;font-weight:500;letter-spacing:0.5px">⌃  收起本篇</button></div>'


def render_email(papers:list[Paper], interactive=False) -> str:
    parts = []
    if len(papers) == 0 :
        return framework.replace('__CONTENT__', get_empty_html())
    
    for p in papers:
        #rate = get_stars(p.score)
        rate = round(p.score, 1) if p.score is not None else 'Unknown'
        author_list = [a for a in p.authors]
        num_authors = len(author_list)
        if num_authors <= 5:
            authors = ', '.join(author_list)
        else:
            authors = ', '.join(author_list[:3] + ['...'] + author_list[-2:])
        if p.affiliations is not None:
            affiliations = p.affiliations[:5]
            affiliations = ', '.join(affiliations)
            if len(p.affiliations) > 5:
                affiliations += ', ...'
        else:
            affiliations = 'Unknown Affiliation'
        if p.analysis:
            header = f'<div style="background:#142b49;color:white;padding:14px 24px"><div style="font-size:12px;letter-spacing:2px;color:#93c5fd">机器人研究 · 文献精读</div><h1 style="font-size:22px;font-weight:600;letter-spacing:-0.3px;line-height:1.4;margin:7px 0">{escape(p.title)}</h1><p style="font-size:12px;color:#cbd5e1;margin:5px 0 0;line-height:1.4">{escape(authors)}</p></div>'
            glance = '<div style="padding:18px 24px 0;background:white;color:#243247;line-height:1.8">' + quick_read(p) + '</div>'
            body = f'<div style="padding:0 24px;background:white"><a href="{safe_url(p.pdf_url or p.url)}">阅读论文 PDF ↗</a></div>' + review_html(p)
            if interactive:
                parts.append('<details class="paper-card" style="margin:0 0 24px;border:1px solid #dbe3ed;border-radius:12px;overflow:hidden;background:white"><summary style="cursor:pointer;list-style:none">' + header + glance + '<div class="toggle" style="padding:0 24px 18px;color:#2563eb;font-size:13px"><span class="closed">展开 01–05 详细解析 ＋</span><span class="opened">收起详细解析 −</span></div></summary>' + body + COLLAPSE_CONTROL + '</details>')
            else:
                parts.append('<div style="margin-bottom:24px;border:1px solid #dbe3ed;border-radius:12px;overflow:hidden">' + header + glance + body + '</div>')
        else:
            parts.append(get_block_html(p.title, authors, rate, p.tldr, p.pdf_url, affiliations))

    content = ''.join(parts)
    return framework.replace('__CONTENT__', content)
