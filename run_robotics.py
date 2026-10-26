"""Personal entry point: validates configuration, previews by default."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path

from dotenv import load_dotenv
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf

ROOT = Path(__file__).resolve().parent


def validate_config(config, send=False):
    required = ['llm.api.key', 'llm.api.base_url', 'llm.generation_kwargs.model']
    if config.zotero.enabled:
        required += ['zotero.user_id', 'zotero.api_key']
    if send:
        required += ['email.sender', 'email.receiver', 'email.sender_password', 'email.smtp_server']
    missing = [key for key in required if not OmegaConf.select(config, key)]
    if missing:
        raise ValueError('请在本地 .env 填写配置：' + ', '.join(missing))
    limit = config.executor.max_paper_num
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
        raise ValueError('max_paper_num 应为正整数或 null（不限篇数）')
    if config.email.security not in {'ssl', 'starttls'}:
        raise ValueError('SMTP_SECURITY 必须为 ssl 或 starttls')


def demo():
    from zotero_arxiv_daily.protocol import Paper
    from zotero_arxiv_daily.deep_review import SECTIONS
    from zotero_arxiv_daily.construct_email import render_email
    from zotero_arxiv_daily.digest_state import save_preview
    paper = Paper(source='demo', title='演示排版：灵巧手抓取与手内操作（非真实论文）',
                  authors=['虚构示例，仅验证邮件布局'], abstract='这是合成示例，不代表研究结果。',
                  url='https://arxiv.org', source_level='abstract',
                  published=datetime.now(timezone.utc).isoformat(),
                  tldr='演示五项结构与证据标注；未调用模型、未检索真实论文。')
    examples = {
        'problem': '示例：多指手在接触变化和物体姿态不确定时，难以稳定完成抓取与重定向。',
        'challenges': '示例：高自由度控制、接触动力学、遮挡、触觉噪声以及仿真到真机的差异。',
        'method': '示例：融合视觉与触觉，以分层策略完成预抓取、接触调整和手内操作。',
        'details': '真实报告将在此填写观测、动作空间、网络模块、奖励/损失、训练与部署流程。',
        'experiments': '真实报告将在此填写手型号、任务、物体、基线、指标、真机/仿真结果和消融。此处没有实验数值。',
    }
    paper.analysis = {key: dict(summary=examples[key], evidence='', location='', evidence_verified=False) for key in SECTIONS}
    folder = save_preview(ROOT / 'outputs' / 'demo', [paper], render_email([paper]), [])
    print(f'仅演示，不发送邮件：{folder / "digest.html"}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send', action='store_true')
    parser.add_argument('--check', action='store_true', help='Only validate required configuration; no network calls')
    parser.add_argument('--demo', action='store_true', help='Generate a clearly labelled synthetic preview')
    parser.add_argument('overrides', nargs='*', help='Hydra overrides, e.g. zotero.include_path=[Dexterous/**]')
    args = parser.parse_args()
    os.chdir(ROOT)
    os.environ.setdefault('PYTHONUTF8', '1')
    load_dotenv(ROOT / '.env')
    if args.demo:
        if args.send:
            parser.error('--demo cannot be combined with --send')
        demo()
        return
    with initialize_config_dir(config_dir=str(ROOT / 'config'), version_base=None):
        cfg = compose(config_name='robotics')
    if (ROOT / 'config' / 'private.yaml').exists():
        cfg = OmegaConf.merge(cfg, OmegaConf.load(ROOT / 'config' / 'private.yaml'))
    cfg = OmegaConf.merge(cfg, OmegaConf.from_dotlist(args.overrides))
    cfg.executor.dry_run = not args.send
    try:
        validate_config(cfg, send=args.send)
    except ValueError as exc:
        parser.exit(2, str(exc) + '\n')
    if args.check:
        print('必填配置检查通过（未验证服务连接，未发送邮件）。')
        return
    from zotero_arxiv_daily.executor import Executor
    Executor(cfg).run()


if __name__ == '__main__':
    main()
