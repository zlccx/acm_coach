# ACM Coach

基于 Codex / OpenCode 的本地算法训练 Skill。当前交付为 MVP：真实资源研究 → 有序题单 → 编号任务 → 独立交互学习 → 复盘与笔记暂存。

## 开始使用

在本目录打开新的 Codex 或 OpenCode 会话，输入：

```text
使用 acm-coach，看看今天适合练什么。
使用 acm-coach，我想学习点分治。
使用 acm-coach，继续 P00001。
```

Codex 可用 `$acm-coach` 显式调用。若新技能未出现，重新打开会话；也可以直接让 Agent 读取 `.agents/skills/acm-coach/SKILL.md`。首次画像为空，Coach 会根据对话补充，已有训练数据不会被初始化覆盖。

共享 Skill 位于 `.agents/skills/acm-coach/`，两个客户端读取同一份文件和本仓库的 data，不需要复制 Skill 或修改全局配置。目录发现依据：[Codex 官方文档](https://learn.chatgpt.com/docs/build-skills)、[OpenCode 官方文档](https://opencode.ai/docs/skills/)。文档支持不等同于每个本地客户端版本已做交互验收。

Tutor 是你打开的独立聊天。创建任务后可在新聊天输入 `使用 acm-coach，继续 P00001`；Task ID 只在这一个训练仓库内有意义，两个客户端要打开相同目录。Research 可以按需交给检索 subagent；教学始终在可追问的会话里。

## 个人数据

这是不含个人偏好和训练记录的初始环境。首次运行 `init` 会生成空白画像和训练目录；每位使用者维护自己的数据。可自行新建个人笔记，默认不要在 strict 练习中读取含解法的笔记。

## 命令行

需要 Python 3.10+，无 pip 依赖。在仓库根目录运行：

```powershell
python .agents/skills/acm-coach/scripts/coach.py init
python .agents/skills/acm-coach/scripts/coach.py status
python .agents/skills/acm-coach/scripts/coach.py cf-search --tag dp --min-rating 1200 --max-rating 1600 --limit 3
python .agents/skills/acm-coach/scripts/coach.py cses-playlist --section "Dynamic Programming" --id cses-dp
python .agents/skills/acm-coach/scripts/coach.py create --title "Watermelon" --url https://codeforces.com/problemset/problem/4/A
python .agents/skills/acm-coach/scripts/coach.py resume P00001
```

最后两个命令会创建真实训练任务，仅在打算练习时运行。`cf-search` 输出含标签，不用于严格练习 Tutor；`cses-playlist` 只输出，不自动导入。其他工作目录运行时显式加 `--root <本仓库绝对路径>`（放在子命令前）。题单导入、提示、代码关联、笔记确认等见 [操作协议](.agents/skills/acm-coach/references/operations.md)。

## 已实现与边界

- Python CLI：任务唯一编号、跨进程恢复、用户思路与模型猜测分离、严格恢复字段过滤、提示等级、题单暂停/推进、复盘日志、笔记暂存/确认提升。
- Codeforces API：题目、rating、标签、缓存与显式失败降级；官方题解由 Agent 从真实比赛页面定位，未做专用解析器。
- CSES：真实题目集的章节题单解析，保留原始顺序和来源。
- 洛谷：真实站内题目/文章/日报关键词检索，题面、文章、原始有序题单解析；题单发现另支持当前目录页标题匹配。
- AcWing：真实公开课程目录检索、课程简介与知识点顺序解析；受限课件不读取。
- OI Wiki：导航目录标题检索及真实文章正文读取；正文关键词发现保留浏览器/web search。
- NOI 大纲：提供本地 PDF 索引构建与查询工具，支持物理页码和源文件哈希；公开包不附带 PDF 和全文索引，需要使用者自行准备有权使用的源文件并构建。详情见 [本地索引](.agents/skills/acm-coach/references/noi-index.md)。
- 浏览器保底：专用脚本失败或范围不足时，可用已打开 Chrome 的站内搜索、DOM 提取脚本，或 web search。见 [浏览器降级](.agents/skills/acm-coach/references/browser-fallback.md)。其余 P1/P2 来源保留站点检索规则。
- strict 防剧透结合 CLI 过滤与 Skill 行为规则；CLI 无法自动证明提示文本未泄题，仍需真实交互验收。
- 本地执行不意味着官方判题通过，完成记录保持 self_reported；不自动提交代码、报名比赛、评分掌握度或搭建 Dashboard。

数据目录 init 后建立，空子目录会在首次使用时生成。`data/notes/knowledge/` 的人工笔记不会被提升操作覆盖。测试在系统临时目录，与真实历史隔离。个人训练数据、解题代码和笔记已默认被 .gitignore 排除，首次使用前无需复制他人的 data。

## 验证

```powershell
python -m unittest discover -s tests -v
```

新资源工具示例（仓库根目录）：

```powershell
python .agents/skills/acm-coach/scripts/coach.py resource-search luogu-daily "点分治" --limit 3
python .agents/skills/acm-coach/scripts/coach.py resource-search acwing "算法基础课"
python .agents/skills/acm-coach/scripts/coach.py resource-search oi-wiki "分治"
python .agents/skills/acm-coach/scripts/coach.py resource-search noi "分治"
python .agents/skills/acm-coach/scripts/coach.py resource-read https://www.luogu.com.cn/problem/P3806 --strict
python .agents/skills/acm-coach/scripts/coach.py resource-playlist https://www.luogu.com.cn/training/100 --output resources/luogu-100.json
```

题单输出不自动导入训练记录；需要采用时再 `playlist-import resources/luogu-100.json`。带标签资源搜索只供选题/学习模式，严格练习仅使用专用题面读取。显式在线冒烟：`python tests/smoke_resources.py`；它不创建 Task 或写训练日志。

[交互验收清单](tests/acceptance.md) 区分脚本测试和独立会话验收。并发锁与 redo journal 用于本地文件一致性；进程硬退出留下 `.lock` 时先确认写入进程已停止，再手动移除，下一命令会恢复未完成事务。

## 共享包说明

此目录可单独作为 GitHub 仓库根目录。包含 Skill、标准库 CLI 和测试，不包含原使用者的画像、训练记录、解题代码、笔记、编辑器配置或本机验证输出。首次使用先运行上文的 `init`，会生成空白个人环境。

基础训练功能只需 Python 3.10+。NOI 大纲原文注明未经授权不得转载，因此此包不分发 PDF 或全文 OCR 索引；相关工具保留。需要查询时，自行准备有权使用的 `NOI_Syllabus_Edition_2025.pdf` 放在根目录，再按 [本地索引说明](.agents/skills/acm-coach/references/noi-index.md) 构建；构建可能需要额外的本地 PDF/OCR 工具。缺少该资料不影响其他训练功能。

扫描版也可选择由当前模型自身读图进行 OCR：Agent 会先询问，得到明确同意后逐页转录并导入索引，无需 Ollama，但需要可用的 PDF 渲染工具。具体操作和导入命令见 [本地索引说明](.agents/skills/acm-coach/references/noi-index.md)。
