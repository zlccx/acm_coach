# CLI 与本地协议

下文 `coach` 表示 `python <skill>/scripts/coach.py --root <仓库>`。所有输出 JSON，失败 stderr JSON + 非零退出；全局参数 `--root` 在子命令前。含引号或长文本建议先用文件工具保存 UTF-8 文本，再 `--text-file <绝对路径>`，避免 shell 插值。

## 常用操作

```text
coach init
coach status
coach next
coach create --title "Watermelon" --url https://codeforces.com/problemset/problem/4/A
coach create --kind topic --title "点分治" --topic centroid-decomposition
coach create --playlist list-id
coach create --playlist list-id --position 3
coach resume P00001
coach update P00001 start
coach update P00001 goal --text "独立完成并解释自己的证明"
coach update P00001 idea --text-file <用户思路文件>
coach update P00001 hypothesis --text "模型推测：边界条件可能有遗漏，用户未确认"
coach update P00001 code --text solutions/P00001.cpp
coach update P00001 hint --level 1 --text-file <本次提示文件>
coach update P00001 mode --text learning
coach update P00001 complete --text-file <复盘文件> --evidence <用户提交链接或本地验证说明>
coach update P00001 abandon --text "暂时放弃，卡在……"
coach note --task P00001 --text-file <待整理笔记文件>
coach promote Nxxxxxxxxxxxx trick-name --confirmed
coach playlist-status list-id paused
coach playlist-status list-id active
```

`complete` 表示本次训练活动结束，不表示 AC。不会调用远程判题。日志只记录发生的操作、时间、对象；具体思路、提示和复盘保存在 Task。需要重练时创建新 Task，旧 ID 永不复用。未 `start` 的训练也可直接完成（例如导入真实训练结果），不得伪造不存在的训练。

`next` 仅返回活跃题单 ID 和游标，不创建任务，不输出可能泄题的专题标题。暂停题单不会改变顺序；需要重练整张题单可用新 ID 导入，出处不变。乱序完成会记录已完成位置，游标仅越过连续完成的题目。允许同题多次训练，但完成同一 Task 不可重复写复盘。

## 题单导入

先把真实原题单转成以下 JSON，再 `coach playlist-import <file.json>`。不要将样例导入真实历史。`items` 原始顺序不重排，`position` 从 1 自动生成；ID 已存在会拒绝，更新请用新版本 ID。

```json
{
  "id": "example-v1",
  "title": "原题单标题",
  "source_url": "https://example.org/original-list",
  "topic": "topic-slug",
  "verification": "unverified",
  "retrieved_at": "2026-10-27T00:00:00+00:00",
  "ordering": "original",
  "items": [
    {"title": "真实题目标题", "url": "https://example.org/problem/1", "problem_id": "1", "source": "站点"}
  ]
}
```

`verification` 是导入者声明，脚本只校验结构/URL，不把它当网络验证证据。研究者应保存访问时间、验证方式与原文片段（短摘录），不能给未打开的链接标成 verified。AI 组合题单用 `ordering: ai_curated`，保留每题出处、补题理由，不能称为已有题单。

## 数据布局

资源相关命令（不改变训练状态）见 [research.md](research.md)：`resource-search`、`resource-read`、`resource-playlist`、`resource-fallback`、`noi-index`。`resource-playlist --output` 保存新 JSON 文件，之后的显式 `playlist-import` 才把该题单纳入训练。NOI 搜索读取 `resources/noi-syllabus-2025.index.json`，显式重建依赖 [本地OCR说明](noi-index.md)。

- `data/profile.md`：用户提供的背景、目标、时间和习惯；首次仅空白提示。
- `data/state.json`：schema_version=1、next_task、active_task、active_playlists、active_topic（保留扩展）、updated_at。
- `data/tasks/P00001.json`：schema_version、id、revision、created_at、updated_at、kind、title、source_url、source_metadata、topic、playlist_id、position、status、mode、goal、user_ideas、hypotheses、hints、code_paths、summary、result。
- `data/playlists/<id>.json`：导入字段 + cursor、completed_positions、status、created_at。
- `data/logs.jsonl`：带 UUID 和 UTC 时间的操作事件；不包含完整聊天。
- `data/notes/inbox.md`：可读暂存；`drafts/<note-id>.json` 是 promote 的结构化来源；修改草稿需重新暂存并确认，不盲目提升旧版本。
- `data/notes/knowledge/<slug>.md`：确认后的人工知识，不自动追加/覆盖。
- `data/cache/`：资源元数据缓存，非训练结果。
- `solutions/`：用户 C++ 解答，登记路径不会自动编写或编译代码。
- `resources/noi-syllabus-2025.index.json`：本地源 PDF 的逐页 OCR 索引，不属于训练历史；原文可能误识别，查询校验原PDF哈希。

时间统一存 UTC，显示时换成用户当地时间。`P` + 至少五位数字为统一 Task 协议，三种对象 Topic / Playlist / Task 不互相冒充；Topic 第一版用稳定 slug，无掌握度表。

## 恢复和并发

每次读写都获取 `data/.lock`；超过 5 秒报告被占用。事务先写 `.transaction.json`，再原子替换目标文件。下次加锁时按 journal 完成同一次写入，日志以完整目标文本写入，不重复追加事件。这个恢复机制处理进程中断，不保证硬件损坏后的恢复；定期备份整个 data 和 solutions。

遇到未知 schema 或 JSON 损坏立即停止；保留原文，先备份再诊断，不执行 init 清空重建。命令不会自动移除残留锁，也没有删除训练历史命令。不要在网络文件系统上假定本地锁/原子替换有相同保证。
