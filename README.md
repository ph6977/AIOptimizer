# AIOptimizer

> **AI 优化桌面应用** —— 本地运行的 OpenAI 兼容网关，内置上下文压缩、智能路由、提示词增强，配套 PySide6 GUI 面板。

## ✨ 核心功能

| 能力增强 | 体验优化 |
|---------|---------|
| **上下文保真压缩** - LLM-judge 两阶段分类→压缩，关键信息（代码/事实/决策/偏好）无损保留，闲聊水话摘要化，节省 30-60% tokens | **压缩透明化** - 每条摘要可展开原文、一键恢复，建立信任 |
| **智能模型路由** - 按任务类型/难度/成本偏好自动选模型 | **用量实时面板** - QtCharts 图表：token/成本/节省率/模型分布/质量分 |
| **提示词自动增强** - 任务类型识别 + 质量准则注入 | **会话管理** - 自动标签、决策书签、导出精炼摘要 |
| **知识注入** (P3) - 内置小型 RAG | **系统托盘** - 常驻后台、一键复制网关地址、开关压缩 |

## 🚀 快速开始

### 1. 环境要求
- Python 3.11+
- Windows 10/11 (主)，代码预留跨平台

### 2. 安装依赖
```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 3. 运行
```bash
python main.py
```

首次运行会在系统托盘显示图标，网关监听 `http://127.0.0.1:8000`。

### 4. 接入客户端
在任意 OpenAI 兼容客户端（Cherry Studio / Open WebUI / Dify / Cursor / Continue）设置：
- **Base URL**: `http://127.0.0.1:8000`
- **API Key**: 任意非空字符串（本地网关不校验）

即可享受自动压缩、路由、增强。

## ⚙️ 配置说明

打开 GUI → 设置页：
- **Provider 管理**: 填入各家 API Key（OpenAI/DeepSeek/GLM/Qwen/Kimi/Anthropic/Gemini/Ollama）
- **压缩设置**: 激进度 0-1、最大/目标上下文窗口
- **路由设置**: 质量/成本偏好滑杆
- **提示词增强**: 开关

配置保存后**运行时即时生效**，无需重启网关。

## 📊 评估体系

```bash
# 启动网关后运行评估
python -m app.eval.run_eval
```
- 基于 15+ 精选用例（chat/code/reasoning/creative/analysis/multi-turn）
- LLM-as-judge (DeepSeek) 对比压缩前后回答质量
- 输出 JSON + Markdown 报告，含分类别得分、胜负统计

## 📦 打包分发

```bash
# Windows PowerShell
.\scripts\build.ps1 -Version 0.1.0
```
产出 `dist/AIOptimizer.exe` (单文件，含 UPX 压缩) + SHA256 校验文件。

## 🏗️ 项目结构
```
AIOptimizer/
├── main.py                    # 入口：启动 GUI + 后台网关
├── requirements*.txt          # 依赖
├── PROJECT_PLAN.md            # 活项目计划书（含阶段汇报/变更台账）
├── app/
│   ├── core/                  # 网关骨架、配置、数据库
│   ├── providers/             # Provider 适配器 (OpenAI兼容/Claude/Gemini)
│   ├── optimizer/             # 压缩/路由/提示词增强引擎
│   ├── ui/                    # PySide6 GUI (面板/透明页/会话/设置/托盘)
│   └── eval/                  # 评估数据集 + llm-as-judge 运行器
├── tests/                     # 单测
├── scripts/build.ps1          # PyInstaller 打包脚本
└── .github/workflows/ci.yml   # CI: lint + test + build
```

## 📄 许可证
MIT License