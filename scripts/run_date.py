"""Run an exact Beijing submission-date preview, without sending mail."""
import argparse,json,sys,time
from datetime import date,datetime,time as daytime,timedelta,timezone
from zoneinfo import ZoneInfo
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import requests,feedparser
from dotenv import load_dotenv
from hydra import compose,initialize_config_dir
from omegaconf import OmegaConf
from openai import OpenAI
from zotero_arxiv_daily.protocol import Paper
from zotero_arxiv_daily.deep_review import enrich,analyze
from zotero_arxiv_daily.digest_state import matches_research,save_preview
from zotero_arxiv_daily.construct_email import render_email

def run(target):
 day=date.fromisoformat(target);start=datetime.combine(day,daytime(),ZoneInfo('Asia/Shanghai')).astimezone(timezone.utc);end=start+timedelta(days=1)
 load_dotenv(ROOT/'.env')
 with initialize_config_dir(config_dir=str(ROOT/'config'),version_base=None):cfg=compose(config_name='robotics')
 categories=list(cfg.source.arxiv.category)
 query='('+' OR '.join('cat:'+c for c in categories)+') AND submittedDate:['+start.strftime('%Y%m%d%H%M')+' TO '+(end-timedelta(minutes=1)).strftime('%Y%m%d%H%M')+']'
 entries=[];offset=0
 while True:
  response=requests.get('https://export.arxiv.org/api/query',params={'search_query':query,'start':offset,'max_results':200,'sortBy':'submittedDate','sortOrder':'descending'},timeout=60);response.raise_for_status()
  feed=feedparser.parse(response.content)
  if 'opensearch_totalresults' not in feed.feed:raise ValueError('Invalid arXiv API response')
  total=int(feed.feed.opensearch_totalresults)
  if total and not feed.entries:raise ValueError('Incomplete arXiv pagination')
  entries.extend(feed.entries);offset+=len(feed.entries)
  if offset>=total:break
  time.sleep(3)
 papers=[];failures=[];candidates=[]
 for e in entries:
  published=datetime.fromisoformat(e.published.replace('Z','+00:00'))
  if start<=published<end and matches_research(e.title+' '+e.summary,cfg.research):
   candidates.append(Paper(source='arxiv',title=e.title,authors=[a.name for a in e.authors],abstract=e.summary,url=e.id.replace('http:','https:'),published=e.published,pdf_url=e.id.replace('http:','https:').replace('/abs/','/pdf/')))
 if candidates:
  llm=OmegaConf.to_container(cfg.llm,resolve=True);client=OpenAI(api_key=llm['api']['key'],base_url=llm['api']['base_url'],timeout=180,max_retries=0)
  for p in candidates:
   try:enrich(p,cfg.analysis);analyze(p,client,llm,cfg.analysis);papers.append(p)
   except Exception as exc:failures.append({'url':p.url,'error_type':type(exc).__name__})
 body=render_email(papers,interactive=True)
 heading=f'<div style="max-width:860px;margin:0 auto 24px;color:#243247"><h1>机器人研究日报 · {day}</h1><p>北京时间首次提交日期：{day} 00:00–23:59。方向：灵巧手抓取与操作、机器人自进化（RSI）。</p><p>检索 {total} 条；匹配 {len(candidates)} 篇；解析完成 {len(papers)} 篇；失败 {len(failures)} 篇。</p></div>'
 if not papers:body=body.replace('No Papers Today. Take a Rest!', '该日期暂无符合条件的公开论文。' if not candidates else '匹配论文解析失败，请查看运行记录。')
 pos=body.index('>',body.index('<body'))+1;body=body[:pos]+heading+body[pos:]
 folder=save_preview(ROOT/'outputs/digests',papers,render_email(papers),failures)
 (folder/'digest.html').write_text(body,encoding='utf-8')
 meta={'date':str(day),'timezone':'Asia/Shanghai','basis':'first submission','query':query,'scanned':total,'matched':len(candidates),'completed':len(papers),'failed':len(failures)}
 (folder/'retrieval.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(meta,ensure_ascii=False))
 if failures:raise RuntimeError('Some analyses failed')
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--date',required=True);run(parser.parse_args().date)
