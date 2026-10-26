from loguru import logger
from pyzotero import zotero
from omegaconf import DictConfig, ListConfig
from .utils import glob_match
from .retriever import get_retriever_cls
from .protocol import CorpusPaper
import random
from datetime import datetime
from .reranker import get_reranker_cls
from .construct_email import render_email
from .utils import send_email
from openai import OpenAI
from tqdm import tqdm
from .deep_review import analyze, enrich
from .digest_state import load_sent, mark_sent, select_candidates, save_preview, run_lock


def normalize_path_patterns(patterns: list[str] | ListConfig | None, config_key: str) -> list[str] | None:
    if patterns is None:
        return None

    if not isinstance(patterns, (list, ListConfig)):
        raise TypeError(
            f"config.zotero.{config_key} must be a list of glob patterns or null, "
            'for example ["2026/survey/**"]. Single strings are not supported.'
        )

    if any(not isinstance(pattern, str) for pattern in patterns):
        raise TypeError(f"config.zotero.{config_key} must contain only glob pattern strings.")

    return list(patterns)


class Executor:
    def __init__(self, config:DictConfig):
        self.config = config
        self.include_path_patterns = normalize_path_patterns(config.zotero.include_path, "include_path")
        self.ignore_path_patterns = normalize_path_patterns(config.zotero.ignore_path, "ignore_path")
        self.retrievers = {
            source: get_retriever_cls(source)(config) for source in config.executor.source
        }
        self.reranker = get_reranker_cls(config.executor.reranker)(config)
        self.openai_client = OpenAI(api_key=config.llm.api.key, base_url=config.llm.api.base_url)
    def fetch_zotero_corpus(self) -> list[CorpusPaper]:
        logger.info("Fetching zotero corpus")
        zot = zotero.Zotero(self.config.zotero.user_id, 'user', self.config.zotero.api_key)
        collections = zot.everything(zot.collections())
        collections = {c['key']:c for c in collections}
        corpus = zot.everything(zot.items(itemType='conferencePaper || journalArticle || preprint'))
        corpus = [c for c in corpus if c['data']['abstractNote'] != '']
        def get_collection_path(col_key:str) -> str:
            if p := collections[col_key]['data']['parentCollection']:
                return get_collection_path(p) + '/' + collections[col_key]['data']['name']
            else:
                return collections[col_key]['data']['name']
        for c in corpus:
            paths = [get_collection_path(col) for col in c['data']['collections']]
            c['paths'] = paths
        logger.info(f"Fetched {len(corpus)} zotero papers")
        return [CorpusPaper(
            title=c['data']['title'],
            abstract=c['data']['abstractNote'],
            added_date=datetime.strptime(c['data']['dateAdded'], '%Y-%m-%dT%H:%M:%SZ'),
            paths=c['paths']
        ) for c in corpus]
    
    def filter_corpus(self, corpus:list[CorpusPaper]) -> list[CorpusPaper]:
        if self.include_path_patterns:
            logger.info(f"Selecting zotero papers matching include_path: {self.include_path_patterns}")
            corpus = [
                c for c in corpus
                if any(
                    glob_match(path, pattern)
                    for path in c.paths
                    for pattern in self.include_path_patterns
                )
            ]
        if self.ignore_path_patterns:
            logger.info(f"Excluding zotero papers matching ignore_path: {self.ignore_path_patterns}")
            corpus = [
                c for c in corpus
                if not any(
                    glob_match(path, pattern)
                    for path in c.paths
                    for pattern in self.ignore_path_patterns
                )
            ]
        if self.include_path_patterns or self.ignore_path_patterns:
            samples = random.sample(corpus, min(5, len(corpus)))
            samples = '\n'.join([c.title + ' - ' + '\n'.join(c.paths) for c in samples])
            logger.info(f"Selected {len(corpus)} zotero papers:\n{samples}\n...")
        return corpus

    
    def run(self):
        with run_lock(self.config.executor.get('state_file')):
            self._run()

    def _run(self):
        if self.config.zotero.get('enabled', True):
            corpus = self.filter_corpus(self.fetch_zotero_corpus())
        else:
            profile = self.config.get('research', {}).get('profile', '')
            if not profile:
                raise ValueError('A research.profile is required when Zotero is disabled')
            corpus = [CorpusPaper(title='Research interest profile', abstract=profile,
                                  added_date=datetime.now(), paths=[])]
        if len(corpus) == 0:
            raise ValueError('No Zotero papers with abstracts found in the selected collections')
        all_papers = []
        for source, retriever in self.retrievers.items():
            logger.info(f"Retrieving {source} papers...")
            papers = retriever.retrieve_papers()
            if len(papers) == 0:
                logger.info(f"No {source} papers found")
                continue
            logger.info(f"Retrieved {len(papers)} {source} papers")
            all_papers.extend(papers)
        logger.info(f"Total {len(all_papers)} papers retrieved from all sources")
        state_file = self.config.executor.get('state_file')
        if self.config.get('research') or state_file:
            all_papers = select_candidates(all_papers, self.config.get('research', {}), load_sent(state_file))
            logger.info('After topic, date and sent-history filtering: {}', len(all_papers))
        failures = []
        deep = self.config.get('analysis', {}).get('enabled', False)
        reranked_papers = []
        if len(all_papers) > 0:
            logger.info("Reranking papers...")
            reranked_papers = self.reranker.rerank(all_papers, corpus)
            reranked_papers = reranked_papers[:self.config.executor.max_paper_num]
            logger.info("Generating TLDR and affiliations...")
            for p in tqdm(reranked_papers):
                if deep:
                    try:
                        enrich(p, self.config.analysis)
                        analyze(p, self.openai_client, self.config.llm, self.config.analysis)
                    except Exception as exc:
                        logger.error('Review failed for {} ({})', p.url, type(exc).__name__)
                        failures.append({'url': p.url, 'error_type': type(exc).__name__})
                        continue
                else:
                    p.generate_tldr(self.openai_client, self.config.llm)
                    p.generate_affiliations(self.openai_client, self.config.llm)
            if deep:
                failed_urls = {f['url'] for f in failures}
                reranked_papers = [p for p in reranked_papers if p.url not in failed_urls]
        elif not self.config.executor.send_empty:
            logger.info("No new papers found. No email will be sent.")
            return
        email_content = render_email(reranked_papers)
        folder = save_preview(self.config.executor.get('output_dir'), reranked_papers, email_content, failures)
        if folder:
            logger.info('Preview and JSON saved to {}', folder)
        if self.config.executor.get('dry_run', False):
            logger.info('Preview only: no email sent and no sent history changed')
            if failures:
                raise RuntimeError('Some reviews failed; see papers.json')
            return
        if not reranked_papers and failures:
            raise RuntimeError('All selected reviews failed; no email sent')
        logger.info("Sending email...")
        send_email(self.config, email_content)
        mark_sent(state_file, reranked_papers)
        logger.info("Email sent successfully")
        if failures:
            raise RuntimeError('Partial delivery: failed papers were not marked sent; see papers.json')
