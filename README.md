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

#### 必填项

| 变量 | 说明 |
|------|------|
| `EMAIL_BACKEND` | `smtp` 或 `sendgrid` |
| `EMAIL_FROM_ADDRESS` | 发件人邮箱地址 |
| `EMAIL_RECIPIENTS` | 收件人邮箱（逗号分隔），或在 `config/recipients.txt` 中配置 |

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

# 预览模式（将渲染的 HTML 保存为文件，不发送邮件）
python main.py --output preview.html

# 干跑模式（将渲染的 HTML 打印到标准输出）
python main.py --dry-run
```

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

也可在 Actions 页面手动触发工作流（支持预览模式和输出 HTML 文件）。

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

