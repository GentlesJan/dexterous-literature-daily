"""Build public HTML only; send a short notification after Pages deployment."""
import argparse,json,os,sys,re
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from html import escape
from urllib.parse import urlparse
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from zotero_arxiv_daily.protocol import Paper
from zotero_arxiv_daily.construct_email import quick_read
from zotero_arxiv_daily.digest_state import mark_sent
SITE=ROOT/'site'
RUN=ROOT/'outputs/site-run.json'

def build(seed=None):
 SITE.mkdir(exist_ok=True);RUN.parent.mkdir(exist_ok=True)
 folders=sorted((ROOT/'outputs/digests').glob('*/papers.json'))
 source=Path(seed) if seed else (folders[-1].parent if folders else None)
 date=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
 records=[];entry=None
 if source:
  records=json.loads((source/'papers.json').read_text(encoding='utf-8'))['papers']
  if records:
   slug='2026-10-20_25' if seed else date
   name=f'{slug}.html'
   document=(source/'digest.html').read_text(encoding='utf-8')
   if 'file:///' in document or re.search(r'\bsk-[A-Za-z0-9_-]{20,}',document):raise ValueError('Local URL or possible secret in public HTML')
   (SITE/name).write_text(document,encoding='utf-8')
   entry={'date':slug,'file':name,'count':len(records)}
 index_path=SITE/'archive.json'
 entries=json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else []
 if entry:entries=[entry]+[x for x in entries if x['file']!=entry['file']]
 entries.sort(key=lambda x:x['date'],reverse=True)
 index_path.write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')
 cards=''.join(f'<a class="card" href="{escape(x["file"],quote=True)}"><strong>{escape(x["date"])}</strong><span>{x["count"]} 篇论文 · 查看卡片 →</span></a>' for x in entries)
 page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>机器人研究日报</title><style>body{max-width:860px;margin:48px auto;padding:0 20px;background:#f1f5f9;color:#243247;font:15px/1.8 'Segoe UI','Microsoft YaHei',sans-serif}h1{font-size:28px}.card{display:flex;justify-content:space-between;gap:16px;margin:16px 0;padding:24px;background:white;border:1px solid #dbe3ed;border-radius:12px;text-decoration:none;color:inherit}.card span{color:#52657c}a:focus-visible{outline:3px solid #60a5fa}</style><h1>机器人研究日报</h1><p>灵巧手抓取与操作 / 机器人自进化（RSI） · 按日期浏览，点击论文卡片展开全文解析。</p>'''+cards+'<p style="color:#64748b;font-size:12px">基于 zotero-arxiv-daily（AGPL-3.0）改造。AI 解析请结合论文核实。</p></html>'
 (SITE/'index.html').write_text(page,encoding='utf-8');(SITE/'.nojekyll').touch()
 RUN.write_text(json.dumps({'date':date,'entry':entry,'papers':records},ensure_ascii=False),encoding='utf-8')
 print('Website built:',len(entries),'editions;',len(records),'papers this run')

def notify():
 from dotenv import load_dotenv
 from hydra import compose,initialize_config_dir
 from zotero_arxiv_daily.utils import send_email
 load_dotenv(ROOT/'.env')
 base=os.environ['SITE_URL'].rstrip('/')
 if urlparse(base).scheme!='https':raise ValueError('Expected HTTPS site')
 run=json.loads(RUN.read_text(encoding='utf-8'))
 link=base+'/'+run['entry']['file'] if run['entry'] else base+'/'
 body=f'<div style="max-width:760px;margin:auto;font-family:Arial,sans-serif;color:#243247"><h1>机器人研究日报 · {run["date"]}</h1><p>'+ (f'本期 {len(run["papers"])} 篇。点击网页查看可折叠卡片、详细解析与原图。' if run['papers'] else (f'网站已上线，本期 {run["entry"]["count"]} 篇论文，点击查看可折叠卡片。' if run['entry'] else '本次未检索到可生成的新论文，点击查看历史日报。'))+f'</p><p><a href="{escape(link,quote=True)}" style="color:#2563eb;font-size:18px">打开完整交互日报 →</a></p>'
 papers=[]
 for r in run['papers']:
  r=dict(r);r.pop('source_file',None);p=Paper(**r);papers.append(p)
  body+=f'<h2 style="font-size:18px">{escape(p.title)}</h2>'+(quick_read(p) if p.analysis else escape(p.abstract))+f'<p><a href="{escape(link,quote=True)}">查看完整解析 →</a></p>'
 body+='</div>'
 with initialize_config_dir(config_dir=str(ROOT/'config'),version_base=None):cfg=compose(config_name='robotics')
 send_email(cfg,body)
 if papers:mark_sent(SITE/'sent.json',papers)
 print('Notification accepted by SMTP')
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--seed');parser.add_argument('--notify',action='store_true');args=parser.parse_args()
 notify() if args.notify else build(args.seed)
