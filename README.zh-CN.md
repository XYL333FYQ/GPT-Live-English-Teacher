# GPT Live English Coach

<p align="center">
  <a href="README.md">English</a> ·
  <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <img alt="GPT-Live" src="https://img.shields.io/badge/Built%20for-GPT--Live-10a37f">
  <img alt="ChatGPT Voice" src="https://img.shields.io/badge/ChatGPT-Voice-111827">
  <img alt="AI English Tutor" src="https://img.shields.io/badge/AI-English%20Tutor-2f6fed">
  <img alt="Portable Memory" src="https://img.shields.io/badge/Memory-Portable%20JSON-4b79ff">
  <img alt="License" src="https://img.shields.io/badge/License-CC%20BY%204.0%20%2B%20MIT-b8c0cc">
</p>

<h3 align="center">为 GPT‑Live 而生的英语课程。</h3>

<p align="center">
  <strong>一个运行在 ChatGPT Voice 里的开源 AI 英语教练。</strong><br>
  挂载两个文件，走进 Live：从真实生活开口，在最需要的时候得到纠正，进入新鲜的现实话题与辩论，最后带着一份记得下一步该练什么的学习档案离开。
</p>

<p align="center">
  <sub>全双工口语 · 联网新话题 · 实时纠正 · 间隔复习 · 无需安装应用</sub>
</p>

<p align="center">
  <a href="https://github.com/loiqy/GPT-Live-English-Coach/raw/refs/heads/main/English_Learning_Instructions.md">
    <img
      src="https://img.shields.io/badge/下载-最新版%20Instruction-2ea44f?style=for-the-badge&logo=github"
      alt="下载最新版 Instruction"
    >
  </a>
  &nbsp;
  <a href="https://github.com/loiqy/GPT-Live-English-Coach/releases/latest">
    <img
      src="https://img.shields.io/badge/查看-最新稳定版本-2563eb?style=for-the-badge&logo=github"
      alt="查看最新稳定版本"
    >
  </a>
</p>

<p align="center">
  <img src="assets/hero-collage.png" width="100%" alt="GPT Live English Coach：面向 ChatGPT Voice 的开源 AI 英语教练与口语陪练方案">
</p>

## 语音终于成为一块真正的学习界面

OpenAI 表示，每周已有**超过 1.5 亿人**使用 Voice、Dictation 等语音功能。GPT‑Live 带来了全双工对话、更懂停顿的倾听、更自然的插话与打断，以及在对话继续流动时委托搜索和深度推理的能力。口语练习由此拥有了真实交流所需要的节奏、压力与临场感。[查看 GPT‑Live 官方介绍](https://openai.com/index/introducing-gpt-live/)。

**GPT Live English Coach 为这套新界面装上课程、记忆和教练人格。**

- **从生活里开口。** 酒店、咖啡馆、旅行、small talk、澄清、礼貌与日常社交，先让英语真正用起来。
- **在关键时刻被点醒。** 教练会捕捉不自然表达、中式英语、语域、语用与值得带走的 lexical chunks。
- **把谈话推向现实世界。** 每节课都可以自然进入一个经过网页搜索确认的新鲜话题与更深入的辩论。
- **让进步延续到下一次。** 一个可携带的 JSON 档案保存表达盲点、复习项目、课程历史与下一步训练方向。

## GPT‑Live 为这套课程带来的新空间

传统语音陪练通常依次完成语音转文字、模型回答、文字转语音。GPT‑Live 在 ChatGPT Voice 中持续处理交互，让学习者可以停顿、插话、边想边说，并维持同一条自然流动的对话。它还可以在同一个聊天中调用网页搜索、记忆、文本、图片与可视化结果。这让一份 instruction 也能承载接近完整口语课程的体验。

## 用户实际只需要什么

你真正需要使用的，只有两个文件：

1. `English_Learning_Instructions.md`
2. 你最新的 `English_Learning_Profile.json`

这就是完整的用户侧工作流。

## 工作流程

<p align="center">
  <img src="assets/how-it-works.png" width="100%" alt="GPT Live English Coach 工作流程图">
</p>

## 快速开始

### 第一节课

1. 下载 `English_Learning_Instructions.md`。
2. 在 ChatGPT 中新开一个对话。
3. 挂载 instruction 文件。
4. 发送：`Start my first class.`
5. 跟随初始化与分级流程。
6. 课程结束后回到文本模式，发送：`Test finished`。
7. 下载生成的 `English_Learning_Profile.json`。

> 第一节课无需准备 profile 文件；完成初始测评后，ChatGPT 会生成属于你的个人学习档案。

### 后续每一节课

1. 在 ChatGPT 中新开一个对话。
2. 挂载：
   - `English_Learning_Instructions.md`
   - 你最新的 `English_Learning_Profile.json`
3. 发送：`Prepare for class`。
4. 阅读起飞前 briefing。
5. 进入 GPT Live 开始说话。
6. 结束后回到文本模式，发送：`Class is over, export data.`
7. 下载更新后的 profile JSON，用于下一节课。

## 一节课的体验

### 开场

挂载两个文件，发送 `Prepare for class`，你会获得一份为当日课程量身整理的起飞前说明。

### 上课

课程先从一个日常说话场景开始，把表达带热，再一步步推进到更深入的对话。

### 收束

课程结束时，你会收到简洁反馈、一次同步整理，以及一个更新后的 profile 文件。

## 示例对话

**Learner:** I very agree with that, because—

**Coach:** Tiny fix: **I completely agree with that.** Say that once.

**Learner:** I completely agree with that.

**Coach:** Exactly. Now—what makes you so sure?

---

**Learner:** I felt I was abandoned by the team after I did most of the work.

**Coach:** That sounds genuinely painful, especially if you had been carrying the project. Here, **I felt let down by the team** is probably the more natural fit; **abandoned** sounds stronger and more absolute. Which hurt more—the lack of help or the lack of recognition?

## 仓库内容

- `English_Learning_Instructions.md` — 主 instruction 文件（当前版本：**v2.2.3**）
- `assets/hero-collage.png` — README 主视觉图
- `assets/how-it-works.png` — README 流程海报
- `assets/social-preview.jpg` — GitHub 社交预览图
- `tests/test_memory_engine.py` — 复习逻辑与示例数据的轻量测试脚本

## 为什么它很适合移动端

这个项目贴合 ChatGPT Live 的真实使用方式：

- 挂载文件，
- 进入 Live，
- 自然说话，
- 导出进度。

整体体验非常轻，携带成本也很低。

<details>
<summary><strong>补充说明</strong></summary>

- 这是英语教练工作流，不是正式 IELTS 测评工具。
- ChatGPT Live 的行为可能会随着产品更新而演化。
- 深度讨论阶段会受网页搜索可用性的影响。
- 语音转写效果会受到设备与环境影响。

</details>

## 版本信息

- Instruction version: **2.2.3**
- Profile schema: **2.1**
- 本次仓库打包日期：**2026-07-11**

## 许可证

- Instruction、文档、profile 模板与图片采用 **CC BY 4.0**，详见 [`LICENSE`](LICENSE)。
- `tests/` 目录下的文件采用 **MIT License**，详见 [`tests/LICENSE`](tests/LICENSE)。

## 贡献

欢迎提交 issue 或 PR，尤其是：

- 课程体验反馈，
- 教练人格微调，
- 复习引擎边界情况，
- 移动端使用体验，
- 文档与展示优化。

详见 `CONTRIBUTING.md`。
