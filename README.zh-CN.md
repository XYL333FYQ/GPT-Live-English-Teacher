# GPT Live English Coach

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <strong>面向英语 Pre-A1 零基础学习者的 ChatGPT Project + GPT Live 个人 AI 外教。</strong>
</p>

本项目不开发独立应用或后端。它由可上传到 ChatGPT Project 的教学指令、课程 JSON、学习档案 schema，以及用于仓库校验的轻量 Python 脚本组成。

## 这一版解决什么

原项目已经具备 GPT Live 语音课堂、即时纠错、间隔复习和 JSON 档案导出流程，但默认任务偏向中高级学习者。v3.0 在保留这些机制的基础上增加：

- `PRE_A1 → A1 → A2 → B1` 四级、32 个有序单元；
- 每单元明确知识前置、Can-Do 目标、语言范围和完成标准；
- 固定教学流程：**课程目标 → 示范 → 跟读 → 引导练习 → 独立表达 → 检验 → 复习**；
- Pre-A1 默认中文解释，并从约 20% 英语输入逐步提升；
- 档案记录当前位置、知识状态、听说/发音薄弱项和实际练习证据；
- 跟读与独立掌握严格分离；
- 禁止根据语音转写文本给出精确发音评分；
- v2.1 档案无损迁移、非覆盖导出和自动化校验。

## 快速开始

### 1. 创建 ChatGPT Project

将这些静态文件加入同一个 Project：

- `English_Learning_Instructions.md`
- `curriculum/PRE_A1.json`
- `curriculum/A1.json`
- `curriculum/A2.json`
- `curriculum/B1.json`
- `schemas/learning-profile.schema.json`

课程文件长期保留在 Project 中，不需要每节课重复上传。

### 2. 第一节课

1. 在 Project 中新建对话。
2. 发送：`Start my first class.`
3. 按提示进入 GPT Live；零基础可以全程要求中文解释。
4. 回到文本模式，发送：`Test finished`。
5. 下载生成的 `English_Learning_Profile.json`。

分级从最低需求开始，不会直接要求零基础学习者讲个人故事或讨论抽象观点。

### 3. 后续课程

1. 在 Project 对话中上传最新的 profile JSON。
2. 发送：`Prepare for class`。
3. 确认课程目标后进入 GPT Live。
4. 结束时回到文本模式，发送：`Class is over, export data.`
5. 下载新文件 `English_Learning_Profile_updated_YYYY-MM-DD.json`。

源文件不会被覆盖；重名时自动使用 `_2`、`_3` 等后缀。

## 课程阶段

| 阶段 | 重点 | 中文支持 | 英语输入目标 |
|---|---|---|---:|
| Pre-A1 | 课堂求助、姓名、字母、数字、基本需求与生存对话 | 默认开启 | 20% → 45% |
| A1 | 个人信息、日常、地点、购物、过去与计划 | 遇阻或请求时 | 45% → 70% |
| A2 | 短叙事、比较、经历、建议、服务问题与观点 | 简短按需 | 70% → 85% |
| B1 | 连贯叙事、因果、证据、协商、语域与现实议题 | 仅关键概念 | 85% → 95% |

下一个单元只有在前置单元已完成或经未见综合分级检验明确记入 `placement_credited_unit_ids`，且前置知识达到 `independent` / `mastered` / `placement_credited` 后解锁。分级不能伪造普通课程完成记录，也不能用跟读代替分级证据。

课程结构借鉴 [FreeLingo](https://github.com/artcc/freelingo) 的有序 CEFR 单元、前置关系、能力清单和完整性测试思路；本仓库的课程文本、证据规则和 ChatGPT Live 工作流为独立实现，没有移植其后端、数据库、XP 或动态出题系统。

## 掌握证据

知识状态依次为：

`not_started → introduced → supported → independent → mastered`

另有 `placement_credited` 表示分级时独立证明。

- 示范只能形成 `introduced`。
- 跟读和带答案提示的练习最多形成 `supported`。
- 新情境、无答案泄露的成功表达才可形成 `independent`。
- 至少两个不同课次的独立成功，且包含后续检验或复习，才可形成 `mastered`。

发音只记录 GPT Live 中直接听到的定性可懂度现象。只有转写文本时必须标记 `not_assessed`；本版本不提供数字、百分比、音素或声学精确评分。

## 学习档案 v3.0

在原有 `scientific_assessment`、`active_repertoire` 和 `session_log` 基础上新增：

- `learning_track`：课程、版本、阶段和分级依据；
- `current_course_position`：当前单元、阶段、解锁与完成单元；
- `knowledge_state`：每个知识点的状态及独立证据；
- `skill_weaknesses`：听力、口语和发音薄弱项；
- `practice_evidence`：任务、支持程度、结果、模态、题目是否未见、是否提前显示文字和语音证据来源；
- `migration_history`：旧档案迁移记录。

v2.1 档案会保留原字段、复习阶段、日期、会话和未知兼容扩展。旧 B2–C2 档案进入 `legacy_conversation` 模式；Pre-A1–B1 档案先做桥接检验，再定位具体单元。

## 仓库内容

```text
English_Learning_Instructions.md
curriculum/
  PRE_A1.json
  A1.json
  A2.json
  B1.json
schemas/
  curriculum.schema.json
  learning-profile.schema.json
tools/
  learning_data.py
tests/
  fixtures/
  test_curriculum.py
  test_memory_engine.py
  test_profile.py
```

## 校验

无需安装第三方依赖：

```bash
python tools/learning_data.py validate
python -m unittest discover -s tests -v
```

测试覆盖 JSON Schema 实际执行、课程顺序与引用、七阶段流程、跨级 placement、未见听力证据、v2.1 迁移、确定性复习队列、发音边界以及导出回读。

## 限制

- 这是教学工作流，不是官方 CEFR、IELTS 或发音测评工具。
- GPT Live、文件工具和语音可用性可能随 ChatGPT 产品变化。
- 本仓库不存储音频，也不进行声学分析。
- B1 现实话题受网页搜索可用性影响；Pre-A1/A1 不依赖新闻讨论。

## 版本与许可

- Instruction：**v3.0.0**
- Profile schema：**3.0**
- Curriculum：**1.0.0**
- Instruction、课程、文档、schema 与示例档案采用 `LICENSE` 中的 CC BY 4.0。
- `tools/` 与 `tests/` 中的 Python 代码采用 `tests/LICENSE` 中的 MIT License。
