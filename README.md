# Doraskill

**跨境电商舆情日报生成工作流的开源沉淀** —— 从"每日检索计划"到"合规日报排版"的一整套可复用执行标准，诞生于真实的生产环境（跨境电商平台竞品与行业政策舆情监测，累计支撑 85+ 篇日报输出）。

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## 这是什么

做舆情监测的人都知道：日报难的不是"写"，而是**稳定复现一套高标准**——今天记得查数据报告、明天就漏了；这条新闻该收、那条是软文不该收，标准稍一模糊，质量就波动。

Doraskill 把一套经过 **10 个版本迭代** 的舆情日报 SOP 开源出来，让它从"个人经验"变成"可复用、可执行、可被校验的标准"。仓库以 `skill-Dora.md`（SOP v10.0，唯一执行依据）为核心，配套一整套可运行的工程组件：检索配置 → 计划生成 → 批量预检 → 结构化录入 → 一键渲染（含 CI 与定时提醒）。

它适合：

- **跨境电商业内做竞品/舆情监测的同学** —— 直接借鉴信源梯队、过滤规则与执行 SOP；
- **想做"AI 驱动工作流"个人作品的人** —— 观察一个真实业务问题如何被拆解成规则、配置与脚本。

## 核心资产

| 文件 | 说明 |
| --- | --- |
| `skill-Dora.md` | **SOP v10.0（唯一执行依据）**：核心原则、三大板块、信源梯队与信源池、五大检索维度、九家友商关键词矩阵、过滤规则细化对照表、时间窗口分层、每日 9 步 SOP、标题/摘要/排版硬规则、质量校验四步法与盲区自查清单、版本演进记录 |
| `config/competitors.json` | 机器可读检索配置：五大维度关键词 + 九家友商矩阵 + 行业政策/自身监测关键词（与 SOP §4.1/§4.2 一一对应） |
| `scripts/generate_search_plan.py` | 检索计划生成器：读取配置，为指定日期生成"照做即可"的当日检索计划（纯标准库，离线可跑） |
| `examples/briefing-sample.html` | 日报排版示例（SOP §8.2 视觉规范：760px 居中 / 分享标题格式 / 三档情感 badge），条目为虚构模拟数据 |
| `config/briefing-entry.schema.json` | 日报条目录入字段契约（JSON Schema）：与 SOP 各硬规则逐条对应的字段定义 |
| `examples/entries.sample.json` | 结构化条目示例（生成器输入，与 briefing-sample.html 同源 6 条） |
| `examples/entries.template.csv` | Excel/WPS 手工录入模板（UTF-8 BOM，直接打开不乱码） |
| `scripts/csv_to_entries.py` | CSV 模板 → JSON 转换器（含字段校验与平台对齐检查） |
| `scripts/render_briefing.py` | HTML 日报生成器：条目 → 合规排版，内置字段/时间窗口/过滤规则自动校验 |
| `scripts/check_sources.py` | 信源链接批量可访问性预检（404/403/超时/DNS/跳首页），支持并发 |
| `examples/urls.sample.txt` | 链接预检演示清单 |
| `.github/workflows/` | CI 冒烟测试（push 自动验证工具链）+ 工作日 09:00 检索计划提醒 Issue |

## 仓库结构

```
Doraskill/
├── skill-Dora.md                  # SOP v10.0 · 唯一执行依据（人类可读 + AI 可执行）
├── config/
│   ├── competitors.json           # 五大维度关键词 + 九家友商检索矩阵
│   └── briefing-entry.schema.json # 日报条目录入字段契约（JSON Schema）
├── scripts/
│   ├── generate_search_plan.py    # 生成当日检索计划（纯标准库，无依赖）
│   ├── csv_to_entries.py          # CSV 录入模板 → JSON 转换器
│   ├── render_briefing.py         # 条目 → SOP §8.2 合规排版 HTML（内置过滤规则校验）
│   └── check_sources.py           # 信源链接批量预检（404/403/超时/跳首页）
├── examples/
│   ├── briefing-sample.html       # 日报排版示例（模拟数据，仅供结构参考）
│   ├── entries.sample.json        # 结构化条目示例（生成器输入）
│   ├── entries.template.csv       # Excel/WPS 手工录入模板
│   └── urls.sample.txt            # 链接预检演示清单
├── .github/workflows/
│   ├── ci.yml                     # push/PR 冒烟测试（三脚本链路自动验证）
│   └── daily-briefing-reminder.yml# 工作日 09:00 自动开检索计划提醒 Issue
├── README.md
└── LICENSE                        # MIT
```

## 快速开始

只需 Python 3.9+，无任何第三方依赖。

### ① 生成当日检索计划

```bash
python scripts/generate_search_plan.py --date 2026-09-08
```

输出示例（节选）：

```markdown
# 舆情日报检索计划 · 2026-09-08

## 第一轮：九家友商并行检索（9 次搜索）

### 1. Temu
- 推荐 query：`Temu 2026-09-08 半托管 GMV`
- 主关键词：Temu 半托管 / Temu 全托管 / Temu 本地卖家 / Temu 招商
- 数据向关键词：Temu GMV / Temu 下载量 / Temu MAU / Temu 份额
- 信源优先：亿邦 ebrungo、出海网、AMZ123、PRNewswire

## 第二轮：维度补检（4 类）      # 业绩财报 / 数据报告 / 物流产品 / 政策监管
## 第三轮：行业与政策、敦煌网自身
## 维度覆盖核查（生成前逐项打勾）
```

也可以输出到文件，供团队共享：

```bash
python scripts/generate_search_plan.py --date 2026-09-08 --out plan.md
```

### ② 照计划检索 → 核验 → 过滤

按 `skill-Dora.md` **第七部分（每日 9 步 SOP）** 执行：

1. 并行检索九家友商（每家 = 主词 + 数据词，不能只搜战略词）
2. 维度补检：业绩财报 / 数据报告 / 物流产品 / 政策监管（注意各维度的 ✅ 纳入 / ❌ 排除）
3. 行业与政策、敦煌网自身
4. 对每个候选链接 WebFetch 核验：标题一字不差 · 发布日期 · 摘要取自原文 · 情感标签 · 信源合规
5. 逐条过过滤规则（**第五部分**：XX号自媒体 / 合集周报 / 仓储细节 / 低权重站等一律排除）

### ③ 结构化录入条目

每个通过核验的候选条目，按 `config/briefing-entry.schema.json` 的字段契约录入（标题与原文一字不差 / 来源只写媒体名 / 三档情感 / 时间窗口……）。两种方式任选：

- **JSON（规范输入，渲染器直接消费）**：参考 `examples/entries.sample.json`；
- **CSV（Excel/WPS 手工录入）**：按 `examples/entries.template.csv` 填列，再转换：

```bash
python scripts/csv_to_entries.py examples/entries.template.csv --out entries.json
```

可选：WebFetch 逐条核验前，可先用预检脚本批量筛掉 404/403/超时/跳首页的链接（对应 SOP 核心原则 8 / §5.1#7/#9）：

```bash
python scripts/check_sources.py --urls candidate-links.txt
python scripts/check_sources.py --entries examples/entries.sample.json --out precheck.md
```

### ④ 一键渲染合规 HTML

```bash
python scripts/render_briefing.py --entries entries.json --out 日报-2026-09-08.html
```

生成器自动完成：字段/时间窗口校验 → 可确定性过滤规则自动拦截（XX号自媒体、合集/周报/早报字眼、非详情页链接、低权重站等，SOP §5.1）→ 按 §2.1 固定板块顺序排版（空板块整体省略）→ 输出 SOP §8.2 锁定样式（760px 居中 / 主标题「【WorkBuddy】敦煌网舆情日报_YYYY年M月D日」分享格式 / 板块标题「一、自身监测」「二、友商动态」「三、行业与政策」+ 4px 红竖线 / 三档情感圆角 badge，无底部说明区）。

> ✅ 生成器内置语义过滤层（`render_briefing.py`）：§5.2 财报/物流域按 SOP 细化对照表自动判定——**命中排除侧信号（纯股价炒作/仓储运营细节）且无纳入侧要素 → 自动拦截（exit 1）**；纳入/排除信号并存或归类不确定 → warn（`--strict` 升级为 error）；`note` 注明"用户指定"的条目按 §10.1 豁免自动拦截（error 降级 warn）。词表与判定见脚本顶部常量与 `semantic_checks()`。

### ⑤ 质量校验

生成前过一遍 **第九部分盲区自查清单**（是否查了 ebrungo 快讯栏 / AMZ123 等第三方数据源 / 央视网物流产品；数据报告是否放宽近 2-3 日；财报是否区分"业绩快讯 vs 股价炒作"……）。

## 时间窗口速记

| 内容类型 | 收录窗口 |
| --- | --- |
| 友商战略动作 / 业绩快讯 | 当日 |
| 第三方数据报告 | 近 2-3 日（唯一例外，按 `published_date` 字段记录真实发布日期） |
| 平台级物流产品 / 行业政策 | 当日 + 近 1-2 日 |

## Roadmap

- [x] SOP v10.0 开源（信源梯队 / 过滤规则 / 时间窗口 / 质量校验）
- [x] 九家友商检索矩阵机器可读化（`config/competitors.json`）
- [x] 检索计划生成器（`scripts/generate_search_plan.py`）
- [x] 日报排版示例（`examples/briefing-sample.html`）
- [x] 日报条目结构化录入模板（`config/briefing-entry.schema.json` + `examples/entries.template.csv` + `scripts/csv_to_entries.py`）
- [x] HTML 日报生成器（`scripts/render_briefing.py`：条目 → 合规排版，内置字段/时间窗口/过滤规则自动校验）
- [x] 信源可访问性批量预检脚本（`scripts/check_sources.py`，防 404/403/超时/跳首页）
- [x] 友商动态更新提醒（GitHub Actions：工作日 09:00 自动开检索计划 Issue + 盲区自查清单）
- [ ] 检索结果半自动整理器：把搜索引擎/API 返回的候选结果转成待核验条目清单（接上条提醒的最后一公里）

## 许可

[MIT](LICENSE)。规则内容沉淀自真实生产实践，欢迎借鉴；如需引入企业内部使用或二次发布，请保留来源署名。
