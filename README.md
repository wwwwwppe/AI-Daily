# AI 日报 (AI Daily Newsletter)

自动抓取每日科技与 AI 资讯，并通过邮件发送给公司全体员工。

---

## 功能特性

| 功能 | 说明 |
|------|------|
| 📰 RSS 新闻抓取 | 从 MIT Technology Review、TechCrunch、Wired、VentureBeat 等多个主流科技媒体抓取最新文章（含原文链接） |
| 💬 AI 大V 推文 | 通过 Twitter / X API v2 抓取 Sam Altman、Yann LeCun、Andrej Karpathy 等 AI 领域大V 的最新动态 |
| 📧 HTML 邮件 | 渲染精美的响应式 HTML 邮件，每条内容均附带原文跳转链接 |
| ⚙️ 灵活配置 | 通过 `.env` 环境变量和 `config/` 目录管理收件人、新闻源与 API 密钥 |
| 🔄 自动调度 | 通过 GitHub Actions 每工作日早 8 点（UTC+8）自动运行，支持手动触发 |
| 🛡️ 容错设计 | 任何单个数据源失败不影响整体运行；无 Twitter Token 时仍可正常发送纯新闻版 |

---

## 目录结构

```
AI-Daily/
├── main.py                          # 主入口脚本
├── requirements.txt                 # Python 依赖
├── .env.example                     # 环境变量示例（复制为 .env 后填写）
├── config/
│   ├── sources.yaml                 # 新闻源与 Twitter 账号配置
│   └── recipients.txt               # 收件人列表（每行一个邮箱，可选）
├── src/
│   ├── config.py                    # 统一配置加载
│   ├── composer.py                  # 邮件 HTML 渲染
│   ├── email_sender.py              # 邮件发送（SMTP / SendGrid）
│   └── fetchers/
│       ├── news_fetcher.py          # RSS / Atom 新闻抓取
│       └── twitter_fetcher.py       # Twitter / X API 推文抓取
├── templates/
│   └── email.html                   # Jinja2 邮件模板
├── tests/                           # 单元测试
│   ├── test_composer.py
│   ├── test_email_sender.py
│   └── test_news_fetcher.py
└── .github/
    └── workflows/
        └── daily_newsletter.yml     # GitHub Actions 调度工作流
```

---

## 快速上手

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 然后编辑 .env，填写邮件服务器信息和收件人列表
```

> ⚠️ `.env` 仅用于本地运行，已被 `.gitignore` 忽略，请不要提交到仓库。

#### 必填项

| 变量 | 说明 |
|------|------|
| `EMAIL_BACKEND` | `smtp` 或 `sendgrid` |
| `EMAIL_FROM_ADDRESS` | 发件人邮箱地址 |
| `EMAIL_RECIPIENTS` | 收件人邮箱（逗号分隔），或在 `config/recipients.txt` 中配置 |
| `REPORT_WINDOW_MODE` | 抓取窗口模式：`anchored`（锚点）或 `rolling`（滚动24小时，推荐） |
| `REPORT_WINDOW_HOUR` | 日报抓取时间窗口的截止小时（默认 `8`，窗口为“昨天该小时到今天该小时”） |
| `REPORT_WINDOW_TZ_OFFSET` | 抓取窗口使用的时区偏移（默认 `8`，即 UTC+8） |
| `ENABLE_ENGLISH_TRANSLATION` | 是否为纯英文内容追加中文翻译行（默认 `true`） |
| `TRANSLATE_API_URL` | 翻译接口地址（默认 Google Translate 公共接口） |

#### SMTP 配置（选 `EMAIL_BACKEND=smtp` 时）

| 变量 | 说明 |
|------|------|
| `SMTP_HOST` | SMTP 服务器地址，如 `smtp.qq.com` |
| `SMTP_PORT` | 端口号，SSL 通常为 `465`，STARTTLS 通常为 `587` |
| `SMTP_USE_SSL` | `true`（SSL）或 `false`（STARTTLS） |
| `SMTP_USERNAME` | 邮箱账号 |
| `SMTP_PASSWORD` | 邮箱密码或授权码 |

#### SendGrid 配置（选 `EMAIL_BACKEND=sendgrid` 时）

| 变量 | 说明 |
|------|------|
| `SENDGRID_API_KEY` | SendGrid API 密钥 |

#### Twitter / X（可选）

| 变量 | 说明 |
|------|------|
| `TWITTER_BEARER_TOKEN` | Twitter API v2 Bearer Token。不填则跳过推文抓取，仍可正常发送新闻版日报 |

#### DeepSeek（可选，仅 `--mode my-news` 需要）

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key |
| `DEEPSEEK_API_URL` | 模型接口地址（默认 DeepSeek；GLM 可用 `https://open.bigmodel.cn/api/anthropic`） |
| `DEEPSEEK_MODEL` | 使用的模型名称（默认 `deepseek-chat`） |
| `DEEPSEEK_TIMEOUT` | 请求超时秒数（默认 `60`） |
| `MY_NEWS_MAX_TOKENS` | my-news 最大输出 tokens（默认 `0` 自动；GLM Anthropic 自动按大配额） |
| `MY_NEWS_REQUIRED_MARKER` | my-news 结果必须包含的标记（默认 `- 导读 -`） |
| `MY_NEWS_MAX_WAIT_SECONDS` | 缺少标记时的等待重试上限秒数（默认 `600`） |
| `MY_NEWS_RETRY_INTERVAL_SECONDS` | 缺少标记时的重试间隔秒数（默认 `20`） |
| `DEVELOPER_ALERT_RECIPIENTS` | 超时后开发者告警邮件收件人（逗号分隔） |

### 3. 配置收件人

方式一：在 `.env` 中设置

```
EMAIL_RECIPIENTS=alice@company.com,bob@company.com
```

方式二：编辑 `config/recipients.txt`，每行一个邮箱：

```
alice@company.com
bob@company.com
```

### 4. 运行

```bash
# 正常运行（抓取内容并发送邮件）
python main.py

# 生成 my-news 样式日报并发送邮件（调用 DeepSeek API，Markdown 落盘到 daily-news/）
python main.py --mode my-news

# 仅生成 my-news（建议 08:00 定时）
python main.py --mode my-news --my-news-action generate

# 仅发送已生成 my-news（建议 09:00 定时，默认发送当天最新一份）
python main.py --mode my-news --my-news-action send

# 指定某个已生成文件发送（用于人工修订后重发）
python main.py --mode my-news --my-news-action send --my-news-file daily-news/202603230830_daily_news.md

# 仅预览 my-news 邮件 HTML（不发送）
python main.py --mode my-news --output my_news_preview.html

# 预览模式（将渲染的 HTML 保存为文件，不发送邮件）
python main.py --output preview.html

# 干跑模式（将渲染的 HTML 打印到标准输出）
python main.py --dry-run
```

`--mode my-news` 会尝试为每条资讯自动抓取代表图并下载到 `daily-news/images/`，
同时将对应的 `![图片描述](images/...)` 引用写回生成的 Markdown 内容中，并默认发送邮件。
SMTP 发送时会以内嵌图片（CID）方式附带本地图片，`--output` 预览时使用本地文件路径展示图片。
如果使用 `--my-news-action generate`，只会生成并落盘，不会发送邮件；
`--my-news-action send` 会读取当天（北京时间）最新生成的 `daily-news/*_daily_news.md` 进行发送。

---

## 自定义新闻源

编辑 `config/sources.yaml` 以添加/删除 RSS 源或 Twitter 账号：

```yaml
rss_sources:
  - name: 我的新闻源
    url: https://example.com/rss
    max_items: 5      # 每次最多抓取条数

twitter_accounts:
  - username: some_ai_influencer
    max_tweets: 3
```

---

## 推荐订阅源

`config/sources.yaml` 中已内置以下精选推荐，可按需增删。

### 📰 RSS 新闻源

#### 国际主流科技媒体

| 名称 | 说明 |
|------|------|
| [MIT Technology Review](https://www.technologyreview.com/feed/) | MIT 技术评论，权威科技与 AI 深度报道 |
| [TechCrunch AI](https://techcrunch.com/category/artificial-intelligence/feed/) | 创业与 AI 产品资讯 |
| [Wired](https://www.wired.com/feed/rss) | 科技文化综合报道 |
| [The Verge AI](https://www.theverge.com/ai-artificial-intelligence/rss/index.xml) | 消费科技与 AI 产品动态 |
| [VentureBeat AI](https://venturebeat.com/category/ai/feed/) | AI 行业与企业应用资讯 |
| [Hacker News (AI)](https://hnrss.org/newest?q=AI+OR+LLM+OR+machine+learning&points=50) | 开发者社区热门 AI 讨论 |
| [InfoQ AI](https://feed.infoq.com/) | 面向开发者的 AI 工程实践 |

#### 顶级 AI 实验室 / 公司博客

| 名称 | 说明 |
|------|------|
| [Google AI Blog](https://blog.google/technology/ai/rss/) | Google AI 研究与产品公告 |
| [OpenAI Blog](https://openai.com/blog/rss.xml) | ChatGPT、GPT-4 等模型官方动态 |
| [Anthropic Blog](https://www.anthropic.com/news/rss.xml) | Claude 系列模型及安全研究 |
| [Meta AI Blog](https://ai.meta.com/blog/rss/) | LLaMA、PyTorch 等开源进展 |
| [Microsoft Research](https://www.microsoft.com/en-us/research/feed/) | 微软研究院学术成果 |
| [NVIDIA AI Blog](https://blogs.nvidia.com/blog/category/artificial-intelligence/feed/) | GPU、推理加速与 AI 基础设施 |
| [AWS Machine Learning Blog](https://aws.amazon.com/blogs/machine-learning/feed/) | AWS 云端 AI 服务与实践 |
| [Hugging Face Blog](https://huggingface.co/blog/feed.xml) | 开源模型、数据集与工具生态 |
| [DeepMind Blog](https://www.deepmind.com/blog/rss.xml) | 强化学习、AlphaFold 等前沿研究 |

#### AI 研究 / 论文

| 名称 | 说明 |
|------|------|
| [arXiv CS.AI](https://arxiv.org/rss/cs.AI) | 最新 AI 学术预印本论文 |
| [Papers With Code](https://paperswithcode.com/news/rss) | 附代码的 SOTA 论文追踪 |

#### 知名 AI 新闻通讯

| 名称 | 说明 |
|------|------|
| [The Batch (DeepLearning.AI)](https://read.deeplearning.ai/the-batch/rss/) | Andrew Ng 主编，每周 AI 精选 |
| [Import AI (Jack Clark)](https://jack-clark.net/feed/) | Anthropic 联创撰写，研究向周报 |

#### 中文 AI 媒体

| 名称 | 说明 |
|------|------|
| [机器之心](https://www.jiqizhixin.com/rss) | 国内领先 AI 专业媒体，覆盖研究与产业 |
| [量子位](https://www.qbitai.com/feed) | AI 与科技创业报道，风格活泼 |
| [36氪（AI频道）](https://36kr.com/feed) | 国内科技创业与 AI 产品资讯 |

> **微信公众号推荐**（无 RSS，需手动关注）：机器之心、量子位、新智元、AI科技评论、AINLP、深度学习自然语言处理

---

### 💬 Twitter / X 推荐关注

#### AI 公司创始人 / CEO

| 账号 | 说明 |
|------|------|
| [@sama](https://x.com/sama) | Sam Altman，OpenAI CEO |
| [@GregBrockman](https://x.com/GregBrockman) | Greg Brockman，OpenAI 联合创始人 |
| [@demishassabis](https://x.com/demishassabis) | Demis Hassabis，Google DeepMind CEO |
| [@emostaque](https://x.com/emostaque) | Emad Mostaque，Stability AI 创始人 |

#### 顶尖 AI 研究员

| 账号 | 说明 |
|------|------|
| [@ylecun](https://x.com/ylecun) | Yann LeCun，Meta AI 首席科学家，图灵奖得主 |
| [@karpathy](https://x.com/karpathy) | Andrej Karpathy，前 OpenAI / Tesla，深度学习教育者 |
| [@AndrewYNg](https://x.com/AndrewYNg) | Andrew Ng，DeepLearning.AI 创始人，AI 布道者 |
| [@fchollet](https://x.com/fchollet) | François Chollet，Keras 作者，Google 研究员 |
| [@goodfellow_ian](https://x.com/goodfellow_ian) | Ian Goodfellow，GAN 发明者 |
| [@jeffdean](https://x.com/jeffdean) | Jeff Dean，Google 首席科学家 |
| [@DrJimFan](https://x.com/DrJimFan) | Jim Fan，NVIDIA AI 研究员 |
| [@hardmaru](https://x.com/hardmaru) | David Ha，前 Google Brain |

#### AI 资讯聚合 / 评论

| 账号 | 说明 |
|------|------|
| [@ai__pub](https://x.com/ai__pub) | AI 研究论文聚合推送 |
| [@GaryMarcus](https://x.com/GaryMarcus) | Gary Marcus，AI 批评与理性分析 |
| [@rohanparekh__](https://x.com/rohanparekh__) | Rohan Parekh，AI 产品与研究观察 |

---

## GitHub Actions 自动调度

在仓库的 **Settings → Secrets and variables → Actions** 中添加以下 Secret，工作流将在每个工作日 UTC 00:00（北京时间 08:00）自动运行：

| Secret 名称 | 对应 .env 变量 |
|-------------|---------------|
| `EMAIL_BACKEND` | `EMAIL_BACKEND` |
| `SMTP_HOST` | `SMTP_HOST` |
| `SMTP_PORT` | `SMTP_PORT` |
| `SMTP_USE_SSL` | `SMTP_USE_SSL` |
| `SMTP_USERNAME` | `SMTP_USERNAME` |
| `SMTP_PASSWORD` | `SMTP_PASSWORD` |
| `SENDGRID_API_KEY` | `SENDGRID_API_KEY` |
| `EMAIL_FROM_NAME` | `EMAIL_FROM_NAME` |
| `EMAIL_FROM_ADDRESS` | `EMAIL_FROM_ADDRESS` |
| `EMAIL_RECIPIENTS` | `EMAIL_RECIPIENTS` |
| `TWITTER_BEARER_TOKEN` | `TWITTER_BEARER_TOKEN` |

> ✅ Public 仓库也可以安全使用 Secrets：无需提交 `.env`，并且 Secret 值不会公开显示在仓库代码中。
> 建议仅在 GitHub Actions Secrets 中维护生产配置。

也可在 Actions 页面手动触发工作流（支持预览模式和输出 HTML 文件）。

### 关于 `.exe` 产物

项目支持 PyInstaller 打包，运行时会优先读取 `.exe` 同目录下的 `.env`。  
`.exe` 属于构建产物，不建议提交到仓库；提交二进制文件不会改变 Agent 的运行逻辑，但会增加仓库体积并影响协作体验。

### GitHub 上直接打包（Windows x64 `.exe` / Ubuntu x64 `.deb`）

仓库已提供工作流：`.github/workflows/package_release.yml`。  
在 **Actions → 📦 Package Builds → Run workflow** 可直接触发，完成后在该次运行的 Artifacts 中下载：

- `ai-daily-windows-x64-exe`：`dist/ai-daily.exe`
- `ai-daily-ubuntu-x64-deb`：`ai-daily_<version>_amd64.deb`

Linux `.deb` 安装示例：

```bash
sudo dpkg -i ai-daily_<version>_amd64.deb
```

---

## 运行测试

```bash
pip install pytest
python -m pytest tests/ -v
```

---

## 邮件预览

以下为生成的 HTML 邮件示例（使用 `--output preview.html` 命令输出）：

- **顶部 Header**：AI 日报品牌标识 + 今日日期
- **📰 今日科技 & AI 资讯**：每条包含来源标签、标题（可点击跳转原文）、摘要、"阅读原文"按钮
- **💬 AI 大V 观点**：每条包含作者、@用户名、推文正文、"查看原推"跳转链接
- **底部 Footer**：免责声明 + 退订说明
