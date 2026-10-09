# GPT Live English Teacher

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <strong>面向英语 Pre-A1 零基础学习者的 ChatGPT Project + GPT Live 个人 AI 外教。</strong>
</p>

本项目不开发独立应用或后端。它由可上传到 ChatGPT Project 的教学指令、课程 JSON、学习档案 schema，以及用于仓库校验的轻量 Python 脚本组成。

## 来源、署名与许可

- **上游原项目**：[`loiqy/GPT-Live-English-Coach`](https://github.com/loiqy/GPT-Live-English-Coach)（作者 Liqin Luo，v2.2.3，2026-07-11）。
  本项目基于它改造，保留其 GPT Live 语音课堂、即时纠错、Mastery Ladder 间隔复习、JSON 档案与导出工作流。
- **上游许可**：指令、文档、档案模板与图片采用 **CC BY 4.0**（`LICENSE`）；`tests/` 下的代码采用 **MIT**（`tests/LICENSE`）。本项目沿用同一许可划分。
- **课程结构参考**：[FreeLingo](https://github.com/artcc/freelingo) 的有序 CEFR 单元、前置关系与能力清单思路；本仓库的课程文本、证据规则与工作流为独立实现。
- **本仓库改造说明**：见 `CHANGELOG.md`。相较上游，本项目新增了 Pre-A1–B1 四级 32 单元课程、知识覆盖式完成标准、听说分维度证据、单元多课次机制、严格分级规则与确定性校验工具；**没有**引入网页、App、后端、数据库或第三方语音 API。

## 这一版解决什么

原项目已经具备 GPT Live 语音课堂、即时纠错、间隔复习和 JSON 档案导出流程，但默认任务偏向中高级学习者。v3.x 在保留这些机制的基础上增加：

- `PRE_A1 → A1 → A2 → B1` 四级、32 个有序单元、128 个知识点；
- 每单元明确知识前置、Can-Do 目标、语言范围和完成标准；
- 固定教学流程：**课程目标 → 示范 → 跟读 → 引导练习 → 独立表达 → 检验 → 复习**（作为教学闭环，不是必须逐条念出的台词）；
- Pre-A1 默认中文解释，并从约 20% 英语输入逐步提升；
- 档案记录当前位置、知识状态、听说/发音薄弱项和实际练习证据；
- 跟读与独立掌握严格分离；
- **单元完成 = 目标通过 + 该目标覆盖的每个知识点独立**，因此「上一单元已完成、下一单元却打不开」的死锁不再可能；
- **听力与口语分维度记录**：听懂不等于会说，会说也不等于能在不同语速下听懂；
- **单元可跨多节课**：Pre-A1 的字母、数字等按课次分段推进，每节课新内容有上限；某个课次没掌握时，下一节课回到**那个课次**补救，而不是重上整个单元；
- **严格分级（v3.1.1 加固）**：跳级必须同时有**一条合格的听力记录和一条合格的口语记录**，分别覆盖该等级的全部要求；一条综合记录不再能同时充当听说两项；
- **缺字段不再自动变有利（v3.1.1 修复）**：没写「题目是否见过」「是否提前看到文字」「听力测试等级」时，一律记为 `unknown`/`null`，不能算通过，也不能因此提高分级；
- **严格听力测试必须显式标注** `listening_check_grade: strict_unseen`，缺这个字段就不算严格通过；
- 无法确认是否看到文字时不得声称严格通过纯听力测试，只能降级为普通听力练习；
- 禁止根据语音转写文本给出精确发音评分；
- v2.1 档案无损迁移、非覆盖导出、确定性同步与自动化校验。

## 快速开始

### 1. 创建 ChatGPT Project

**Project Instructions**（把 `PROJECT_INSTRUCTIONS.md` 的正文整段复制进去）：定义教师身份、文件读取顺序、优先级、禁止事项和三个触发口令。它保证每次对话的底线，但**不能**让模型真的读到文件、不能执行 Python、也不能改变 GPT Live 的语音表现。

**Project Files**（长期保留，不需要每节课重复上传）：

- `English_Learning_Instructions.md`
- `curriculum/PRE_A1.json`
- `curriculum/A1.json`
- `curriculum/A2.json`
- `curriculum/B1.json`
- `schemas/learning-profile.schema.json`
- `tools/learning_data.py`（**可选**：只有在文本模式可以执行代码时才有用，见下）

**第一节课只需要上传上面的 6 个必选文件**；`PROJECT_INSTRUCTIONS.md` 复制到 Instructions，不必重复上传。学习者档案由第一节课结束后生成，之后每节课再上传。

### Python 工具到底怎么用（重要）

`tools/learning_data.py` 只是**仓库里的脚本**，它**不会自动连到 GPT Live**。它的作用是：

- **在 ChatGPT 文本模式的代码沙箱里运行**（前提是该对话能执行代码）。把 `tools/learning_data.py` 一起放进 Project Files，模型就能在文本模式里调用它做确定性校验、课前准备和课后导出。
- 也可以在你自己电脑上运行（需要装 Python），但**不是必须**——日常流程不需要你手动跑任何命令。

日常操作只需要三步：**进 Live 上课 → 课后说 `Class is over, export data.` → 下载新档案，下节课上传**。没有代码执行能力时，模型必须改用人工校验，并明确告诉你「确定性校验/导出没有执行」，而不是假装成功。

### 2. 第一节课

1. 在 Project 中新建对话。
2. 发送：`Start my first class.`
3. 按提示进入 GPT Live；零基础可以全程要求中文解释。
4. 回到文本模式，发送：`Test finished`。
5. 下载生成的 `English_Learning_Profile.json`。

分级从最低需求开始，不会直接要求零基础学习者讲个人故事或讨论抽象观点。若证据不足，AI 会保持 `provisional` 并安排一次简短的桥接检验，而不是直接跳级。

### 3. 普通课程

1. 在 Project 对话中上传最新的 profile JSON。
2. 发送：`Prepare for class`。模型会**按档案自己的 `updated_at` 和 `profile_revision` 判断哪个最新**，并告诉你它选了哪一个——不会只凭文件名猜。
3. 查看课前简报（单元、**课次**、今日目标、新内容上限、复习项、是否有知识缺口）。
4. 进入 GPT Live 上课。
5. 结束时回到文本模式，发送：`Class is over, export data.`
6. 下载新文件 `English_Learning_Profile_updated_YYYY-MM-DD.json`，下节课上传它。

### 4. 复习课 / 调整节奏

- 学习者随时可以说：`Slower`（放慢）、`Faster`（加快）、`Review only`（只复习）、`Pause`（暂停）。
- 加快仍受每课上限约束，且**不会**跳过检验；放慢会把每课新内容降到 1 项。
- 复习课只检索到期的表达与知识点，不引入新内容。

### 5. 课程中断

- 随时可以说 `Class is over`。未测项目记为 `UNTESTED`，不改变状态与复习日期。
- 下一节课 `Prepare for class` 会从同一课次继续。

源文件不会被覆盖；重名时自动使用 `_2`、`_3` 等后缀。


## 课程阶段

| 阶段 | 重点 | 中文支持 | 英语输入目标 |
|---|---|---|---:|
| Pre-A1 | 课堂求助、姓名、字母、数字、基本需求与生存对话 | 默认开启 | 20% → 45% |
| A1 | 个人信息、日常、地点、购物、过去与计划 | 遇阻或请求时 | 45% → 70% |
| A2 | 短叙事、比较、经历、建议、服务问题与观点 | 简短按需 | 70% → 85% |
| B1 | 连贯叙事、因果、证据、协商、语域与现实议题 | 仅关键概念 | 85% → 95% |

下一个单元只有在前置单元已完成或经未见综合分级检验明确记入 `placement_credited_unit_ids`，且前置知识达到 `independent` / `mastered` / `placement_credited` 后解锁。分级不能伪造普通课程完成记录，也不能用跟读代替分级证据。

由于「单元完成」本身就要求它覆盖的每个知识点独立，**「上一单元已完成但下一单元打不开」的状态不可能被写入档案**：如果还差某个前置知识，系统会明确列出缺失项，并安排一次补充教学 + 独立检验（不是死锁，也不是放宽标准）。

每个单元可跨多节课完成。Pre-A1 的字母、数字等已在课程文件中分成多个课次，每节课有明确的新内容上限。

## 掌握证据

知识状态依次为：

`not_started → introduced → supported → independent → mastered`

另有 `placement_credited` 表示分级时独立证明。

- 示范只能形成 `introduced`。
- 跟读和带答案提示的练习最多形成 `supported`。
- 新情境、无答案泄露的成功表达才可形成 `independent`。
- 至少两个**不同日期**的课次的独立成功，且包含后续检验或复习，才可形成 `mastered`。
- 单元完成 = 每个必达目标都有独立通过 **且** 这些目标覆盖的每个知识点都达到 `independent` 及以上。

每个知识点分 `listening` 与 `speaking` 两个维度独立记录，最终状态取**较弱**的那一维。因此「听懂了」不会自动变成「会说」。

发音只记录 GPT Live 中直接听到的定性可懂度现象。只有转写文本时必须标记 `not_assessed`；本版本不提供数字、百分比、音素或声学精确评分。

## 学习档案 v3.0

在原有 `scientific_assessment`、`active_repertoire` 和 `session_log` 基础上新增：

- `learning_track`：课程、版本、阶段和分级依据；
- `current_course_position`：当前单元、课次、阶段、解锁与完成单元；
- `knowledge_state`：每个知识点的状态、听说分维度状态及独立证据；
- `skill_weaknesses`：听力、口语和发音薄弱项；
- `practice_evidence`：任务、支持程度、结果、模态、`skill` 维度、题目是否未见、是否提前显示文字、听力测试等级和语音证据来源；
- `learner_preferences.pace`：学习节奏（normal / faster / slower / review_only / paused）；
- `migration_history`：旧档案迁移记录。

v2.1 档案会保留原字段、复习阶段、日期、会话和未知兼容扩展。旧 B2–C2 档案进入 `legacy_conversation` 模式；Pre-A1–B1 档案先做桥接检验，再定位具体单元。

## 仓库内容

```text
PROJECT_INSTRUCTIONS.md          # 复制到 ChatGPT Project Instructions
English_Learning_Instructions.md # 详细教学与数据规则
curriculum/
  PRE_A1.json                    # 含 lesson_segments（课次分段）
  A1.json
  A2.json
  B1.json
schemas/
  curriculum.schema.json
  learning-profile.schema.json
tools/
  learning_data.py               # validate / audit / init-profile / prepare / plan / export
tests/
  support.py                     # 听说两条合格证据的共用构造
  fixtures/
  test_curriculum.py
  test_memory_engine.py
  test_profile.py
  test_workflow.py               # 15 个验收场景
  test_v311_fixes.py             # v3.1.1 证据真实性回归
docs/
  manual_acceptance.zh-CN.md     # 真实 GPT Live 人工验收脚本
```

## 校验

无需安装第三方依赖：

```bash
python tools/learning_data.py validate
python tools/learning_data.py audit --json
python -m unittest discover -s tests -v
```

测试覆盖 JSON Schema 实际执行、课程顺序与引用、**完整前置依赖审计**、七阶段流程、跨级 placement 加固、未见听力证据与降级、**听说分维度证据**、单元多课次与节奏控制、v2.1 迁移、确定性复习队列、发音边界、导出回读、15 个端到端验收场景，以及 v3.1.1 的**证据真实性回归**（缺字段不乐观、单条记录不能充当听说两项、课次补救定位、最新档案按元数据选择、指令文档一致性）。

```bash
python tools/learning_data.py prepare --profile-dir /mnt/data --date YYYY-MM-DD   # 按元数据自动挑最新档案
```

## 限制（请如实告知使用者）

- 这是教学工作流，不是官方 CEFR、IELTS 或发音测评工具。
- GPT Live、文件工具和语音可用性可能随 ChatGPT 产品变化。
- **仓库中的 Python 脚本不会自动被 GPT Live 调用**：只有在文本模式具备代码执行能力时才会运行。没有代码执行时，必须手工校验并如实说明。日常使用不需要你自己跑命令。
- Project Instructions 无法强制模型读取文件，也无法验证文件是否真的被打开。
- 本仓库不存储音频，也不进行声学分析。
- B1 现实话题受网页搜索可用性影响；Pre-A1/A1 不依赖新闻讨论。
- 自动化测试只验证数据层；真实 GPT Live 行为需按 `docs/manual_acceptance.zh-CN.md` 人工验收。
- v3.1.1 收紧了规则：以前靠缺失字段「自动算通过」的旧档案，会在下次 `Prepare for class` 或导出时被**降级**（不合格的听力通过降为练习、无法验证的跳级撤回）。这是有意的，不是 bug。

## 版本与许可

- Instruction：**v3.1.1**
- Profile schema：**3.0**
- Curriculum：**1.1.0**（1.0.0 档案仍可校验）
- Instruction、课程、文档、schema 与示例档案采用 `LICENSE` 中的 CC BY 4.0（源自 `loiqy/GPT-Live-English-Coach`）。
- `tools/` 与 `tests/` 中的 Python 代码采用 `tests/LICENSE` 中的 MIT License（上游作者 Liqin Luo）。

