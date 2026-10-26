# 灵巧手文献日报改造版

基于 [TideDra/zotero-arxiv-daily](https://github.com/TideDra/zotero-arxiv-daily)，起点提交 `edc68632c9a861559ea376dfd34c3ab0b1e4f34a`。保留上游 AGPL-3.0 许可证。

## 功能

获取 arXiv 最新 RSS 公告，按灵巧手主题、日期和发送历史过滤，再按研究兴趣描述排序。用户目前没有 Zotero，因此默认不连接 Zotero；以后可以切换为文献库推荐。对筛选后的全部论文下载全文并调用模型，默认不限篇数（`max_paper_num: null`）。

五项中文分析：现有问题、难点、方法、方法细节、实验。实验提示包含手型号、物体与任务、仿真/真机、指标、基线、结果和消融。每项保留原文短引文；程序验证引文出现在输入中，不能保证引文充分支持全部总结，也不验证模型标注的章节名。

全文优先使用 HTML（保留表格），失败时提取 PDF，再失败则标明仅摘要。长文保留首/中/尾片段并明确标注截断。teaser/pipeline 优先提取 HTML 候选原图；PDF 回退按图注扫描前 10 页，渲染最多 2 张候选整页，**不是精确裁图**。图注关键词匹配可能出错。PDF 图页在邮件中以 CID 内嵌，HTML 图通过远程链接加载。

本地保存 HTML、JSON 和提取原文。默认预览，显式 `--send` 才发送；仅 SMTP 接受后的论文写入发送历史，版本号合并去重。

## 本机运行

已安装 Python 3.13 和 `.venv` 依赖。运行时在忽略的 `.python-runtime` 目录。

```powershell
# 合成排版演示，不访问模型、不发邮件
.\.venv\Scripts\python.exe run_robotics.py --demo
# 配置检查，不验证服务连接
.\.venv\Scripts\python.exe run_robotics.py --check
# 实际检索、解析并生成预览
.\.venv\Scripts\python.exe run_robotics.py
# 检查发信配置，或执行实际发送
.\.venv\Scripts\python.exe run_robotics.py --check --send
.\.venv\Scripts\python.exe run_robotics.py --send
```

新机器用 `uv sync --group dev`，然后 `uv run run_robotics.py`。本机若 uv 找不到隔离运行时，设置 `$env:UV_PYTHON_INSTALL_DIR = Join-Path (Get-Location) '.python-runtime'`，或直接用上述 `.venv` Python。

## 配置

参考 `.env.example` 填写本地 `.env`，不要覆盖已填写的文件。本机已保存指定收件邮箱，尚未配置模型和发件服务。不要把密钥发到聊天或提交到仓库。

| 变量 | 说明 |
| --- | --- |
| `OPENAI_API_BASE` | 模型服务兼容 API 根地址，如供应商的 `/v1` 地址 |
| `OPENAI_API_KEY` | 该服务密钥；本地兼容服务用其要求的占位值 |
| `LLM_MODEL` | 实际模型名，尚未替用户选定或开通服务 |
| `SENDER`、`SENDER_PASSWORD` | 发件邮箱、SMTP 授权码 |
| `RECEIVER` | 收件邮箱 |
| `SMTP_HOST`、`SMTP_PORT`、`SMTP_SECURITY` | 发件服务器；ssl 或 starttls，不自动降级为明文 |

模型输入预算默认 24k token，输出上限 6k，还需给系统提示留空间；按所选模型容量调整。默认 `analysis.output_format=json_object`，支持严格 schema 的服务可改 `json_schema`，其他兼容服务可选 `prompt`。程序仍执行 JSON 字段及证据验证。保留上游 `chat_completion` / `response` 接口。

```powershell
.\.venv\Scripts\python.exe run_robotics.py analysis.max_input_tokens=12000 analysis.output_format=prompt
```

将来使用 Zotero 时设 `ZOTERO_ENABLED=true`，填写 `ZOTERO_ID` 和只读 `ZOTERO_KEY`；可在忽略的 `config/private.yaml` 设置实际 collection 路径：

```yaml
zotero:
  include_path: ["Dexterous Hands/**"]
```

只使用有摘要的收藏论文；不填路径会使用整个文献库。命令行覆盖优先于 private.yaml。

## 每日北京时间 10:00

`.github/workflows/robotics.yml` 已准备 UTC 02:00 调度。GitHub 可能延迟启动，解析也需要时间，因此不保证整点送达。

目前只在本地改造，**未推送到用户 GitHub、未注册 Windows 定时任务、未启用自动发信**。旧的每日调度已移除，避免重复发送。

部署步骤：

1. 将修改后的代码推送到自己的仓库默认分支，保留许可证及来源。
2. Actions Secrets：`OPENAI_API_KEY`、`OPENAI_API_BASE`、`SENDER`、`SENDER_PASSWORD`、`RECEIVER`；使用 Zotero 时再加 `ZOTERO_ID`/`ZOTERO_KEY`。
3. Actions Variables：`LLM_MODEL`、`SMTP_HOST`、`SMTP_PORT`、`SMTP_SECURITY`、`ZOTERO_ENABLED=false`。
4. 手动运行 **Dexterous hand literature digest**，保持 `send=false`，从 Artifacts 下载预览。
5. 完成邮件联调后设变量 `ROBOTICS_ENABLED=true` 启用每日运行，设为 `false` 停用。

Actions 使用 cache 保存发送历史，缓存丢失可能重发；更强的持久性需服务器本地文件或外部数据库。费用取决于 Actions 和模型服务，不承诺免费。

## 边界

- RSS 仅覆盖当前公告批次，`max_age_days=4` 是时间过滤，**不是四天补抓**；停机和 RSS 更新后重试仍可能漏掉论文。当前日期来自 RSS 公告，不保证是首次提交日。
- 文本 PDF 最多提取 100 页，不做扫描 PDF OCR，多栏阅读顺序可能影响解析。
- 未进行真实模型调用或邮件投递联调；合成演示不是真实论文分析。
- SMTP 已接受、状态尚未落盘时崩溃可能导致重发，不能保证恰好一次投递。强制终止遗留锁时，确认无运行进程后再删除 `outputs/sent.json.lock`。
- 本地 embedding 模型首次使用需要下载；依赖模型下载的慢测试默认跳过。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

新增测试覆盖证据验证、摘要回退、HTML 表格/图像、PDF 图页、截断、日期/主题/版本去重、进程锁、预览与发送状态，以及两种 API 的结构化参数。

接口参考：[OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)。


检索方向新增机器人自进化（RSI）：采用“机器人/具身上下文 AND 自我改进、持续学习、在线适应或自主经验采集”等关键词组合，与灵巧手方向取并集。增加 cs.AI 分类。关键词筛选为召回规则，可能包含相关基础方法，不能证明论文实现了递归自我改进。每日仍不限制篇数。
