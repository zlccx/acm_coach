#!/usr/bin/env python3
"""ACM Coach persistence and resource CLI. Python 3.10+, standard library only."""
import argparse
import contextlib
import copy
import datetime as dt
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


class CoachError(Exception):
    pass


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def encode(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def url(value):
    p = urllib.parse.urlsplit(value)
    if p.scheme not in ("https", "http") or not p.hostname or p.username or p.password:
        raise CoachError("需要不含凭据的 HTTP(S) 来源 URL")
    return value


def token(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise CoachError("ID 只能包含字母、数字、下划线和连字符，最长 64 字符")
    return value


def atomic(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.data = self.root / "data"

    def path(self, relative):
        p = (self.data / relative).resolve()
        if not p.is_relative_to(self.data.resolve()):
            raise CoachError("路径超出 data 目录")
        return p

    @contextlib.contextmanager
    def locked(self):
        self.data.mkdir(parents=True, exist_ok=True)
        lock = self.data / ".lock"
        deadline = time.monotonic() + 5
        while True:
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise CoachError("数据被锁定。确认没有写入进程后才可手动移除 data/.lock；不要自动抢锁")
                time.sleep(0.05)
        try:
            with os.fdopen(fd, "w") as f:
                f.write(str(os.getpid()))
            self.recover()
            yield
        finally:
            lock.unlink()

    def recover(self):
        journal = self.data / ".transaction.json"
        if journal.exists():
            for name, content in read_json(journal).items():
                atomic(self.path(name), content)
            journal.unlink()

    def commit(self, files):
        # Write-ahead redo journal: readers also take the lock and recover first.
        for name in files:
            self.path(name)
        atomic(self.data / ".transaction.json", encode(files))
        for name, content in files.items():
            atomic(self.path(name), content)
        (self.data / ".transaction.json").unlink()

    def load(self, name):
        return read_json(self.path(name))

    def state(self):
        if not self.path("state.json").exists():
            raise CoachError("尚未初始化，请先执行 init")
        s = self.load("state.json")
        if s.get("schema_version") != 1:
            raise CoachError("不支持的数据版本；不要自动覆盖或迁移")
        return s

    def init(self):
        if self.path("state.json").exists():
            return self.state()
        state = {"schema_version": 1, "next_task": 1, "active_task": None,
                 "active_playlists": [], "active_topic": None, "updated_at": now()}
        defaults = {
            "state.json": encode(state),
            "profile.md": "# 学习背景\n\n尚未填写。通过对话了解水平、目标、时间与习惯；不要代填假设。\n",
            "logs.jsonl": "",
            "notes/inbox.md": "# 待整理笔记\n\nAI 暂存；确认后再进入 knowledge。\n",
        }
        self.commit({k: v for k, v in defaults.items() if not self.path(k).exists()})
        (self.root / "solutions").mkdir(exist_ok=True)
        self.path("notes/knowledge").mkdir(parents=True, exist_ok=True)
        return state

    def task(self, ident):
        ident = ident.upper()
        if not re.fullmatch(r"P\d{5,}", ident):
            raise CoachError("任务编号格式为 P00001")
        return self.load(f"tasks/{ident}.json")

    def save_event(self, event, task=None, files=None):
        files = dict(files or {})
        event = {"event_id": uuid.uuid4().hex, "at": now(), **event}
        if task:
            task["revision"] += 1
            task["updated_at"] = event["at"]
            files[f"tasks/{task['id']}.json"] = encode(task)
        log = self.path("logs.jsonl")
        files["logs.jsonl"] = (log.read_text(encoding="utf-8") if log.exists() else "") + json.dumps(event, ensure_ascii=False) + "\n"
        self.commit(files)

    def playlist(self, value):
        if not isinstance(value, dict):
            raise CoachError("题单必须为 JSON 对象")
        pid = token(value["id"])
        if self.path(f"playlists/{pid}.json").exists():
            raise CoachError("题单已存在，不覆盖原始顺序；新版本请使用新 ID")
        if not value.get("title") or not isinstance(value.get("items"), list) or not value["items"]:
            raise CoachError("题单必须包含 title 和非空 items")
        url(value["source_url"])
        for i, item in enumerate(value["items"], 1):
            if not isinstance(item, dict) or not item.get("title"):
                raise CoachError("每道题需有 title 和 url")
            url(item["url"])
            item["position"] = i
        value = {**value, "created_at": now(), "status": "active", "cursor": 1,
                 "verification": value.get("verification", "unverified")}
        state = self.state()
        state["active_playlists"].append(pid)
        state["updated_at"] = now()
        self.save_event({"type": "playlist_import", "playlist_id": pid}, files={
            f"playlists/{pid}.json": encode(value), "state.json": encode(state)})
        return value

    def create(self, kind, title=None, source=None, topic=None, playlist=None, position=None):
        state = self.state()
        item = None
        if playlist:
            pl = self.load(f"playlists/{token(playlist)}.json")
            position = position or pl["cursor"]
            if not 1 <= position <= len(pl["items"]):
                raise CoachError("题单已结束或位置越界")
            item = pl["items"][position - 1]
            title, source = item["title"], item["url"]
            topic = topic or pl.get("topic")
        if not title or (kind in ("practice", "contest") and not source):
            raise CoachError("需要标题；练习/模拟赛还需要真实题目/比赛 URL")
        if source:
            url(source)
        number = state["next_task"]
        while self.path(f"tasks/P{number:05d}.json").exists():
            number += 1
        ident = f"P{number:05d}"
        task = {"schema_version": 1, "id": ident, "created_at": now(), "updated_at": now(),
                "revision": 1, "kind": kind, "title": title, "source_url": source,
                "source_metadata": copy.deepcopy(item), "topic": topic, "playlist_id": playlist,
                "position": position, "status": "pending", "mode": "strict" if kind in ("practice", "contest") else "learning",
                "goal": "", "user_ideas": [], "hypotheses": [], "hints": [], "code_paths": [],
                "summary": None, "result": None}
        state.update(next_task=number + 1, active_task=ident, updated_at=now())
        if kind == "topic" and topic:
            state["active_topic"] = topic
        self.save_event({"type": "task_create", "task_id": ident}, files={
            f"tasks/{ident}.json": encode(task), "state.json": encode(state)})
        return self.resume(ident)

    def resume(self, ident):
        task = self.task(ident)
        if task["mode"] == "strict":
            # Whitelist instead of blacklist: source metadata may contain tags or solutions.
            safe = ("id", "created_at", "updated_at", "revision", "kind", "title", "source_url",
                    "status", "mode", "user_ideas", "hints", "code_paths")
            return {**{k: task[k] for k in safe}, "spoiler_boundary": "仅题面、用户思路与已获提示；不加载题单标签、题解或模型猜测"}
        return task

    def update(self, ident, action, text=None, level=None, evidence=None):
        task = self.task(ident)
        if action == "start":
            if task["status"] not in ("pending", "in_progress"):
                raise CoachError("终态任务请创建新的训练记录")
            task["status"] = "in_progress"
        elif action == "mode":
            if text not in ("strict", "learning"):
                raise CoachError("mode 应为 strict 或 learning")
            task["mode"] = text
        elif action in ("idea", "hypothesis"):
            task["user_ideas" if action == "idea" else "hypotheses"].append({"at": now(), "text": text})
        elif action == "goal":
            task["goal"] = text
        elif action == "code":
            p = (self.root / text).resolve()
            if not p.is_relative_to((self.root / "solutions").resolve()) or p.suffix != ".cpp":
                raise CoachError("代码路径必须是本仓库 solutions/ 下的 .cpp 文件")
            relative = p.relative_to(self.root).as_posix()
            if relative not in task["code_paths"]:
                task["code_paths"].append(relative)
        elif action == "hint":
            previous = max((h["level"] for h in task["hints"]), default=0)
            if level not in (1, 2, 3) or level > previous + 1:
                raise CoachError("提示须从 1 开始逐级记录，不可跳级；完整讲解请显式切换 learning")
            if task["kind"] == "contest" and task["mode"] == "strict":
                raise CoachError("独立模拟赛不提供提示；请先明确结束独立作答并切换 learning")
            task["hints"].append({"at": now(), "level": level, "text": text})
        elif action in ("complete", "abandon"):
            if task["status"] in ("completed", "abandoned"):
                raise CoachError("任务已结束，不重复写入复盘；重做请新建 Task")
            if not text:
                raise CoachError("完成/放弃需提供复盘摘要")
            task.update(status="completed" if action == "complete" else "abandoned", summary=text,
                        result={"verdict": "self_reported", "evidence": evidence})
        else:
            raise CoachError("未知操作")
        files = {}
        if action in ("start", "complete", "abandon"):
            state = self.state()
            if action == "start":
                state["active_task"] = task["id"]
            elif state["active_task"] == task["id"]:
                state["active_task"] = None
            state["updated_at"] = now()
            files["state.json"] = encode(state)
        if action == "complete" and task["playlist_id"]:
            name = f"playlists/{task['playlist_id']}.json"
            pl = self.load(name)
            # Completing an out-of-order task must not skip unfinished preceding items.
            completed = set(pl.get("completed_positions", []))
            completed.add(task["position"])
            pl["completed_positions"] = sorted(completed)
            while pl["cursor"] in completed:
                pl["cursor"] += 1
            pl["status"] = "completed" if pl["cursor"] > len(pl["items"]) else pl["status"]
            files[name] = encode(pl)
        self.save_event({"type": action, "task_id": task["id"], "mode": task["mode"],
                         "status": task["status"], "hint_level": level if action == "hint" else None}, task, files)
        return self.resume(ident)

    def note(self, text, task_id=None):
        if task_id:
            self.task(task_id)
        ident = "N" + uuid.uuid4().hex[:12]
        record = {"id": ident, "at": now(), "task_id": task_id, "text": text, "promoted": False}
        inbox = self.path("notes/inbox.md").read_text(encoding="utf-8")
        self.save_event({"type": "note_inbox", "note_id": ident, "task_id": task_id}, files={
            f"notes/drafts/{ident}.json": encode(record),
            "notes/inbox.md": inbox + f"\n## {ident} · {task_id or '无关联任务'} · {record['at']}\n\n{text}\n"})
        return record

    def promote(self, note_id, slug, confirmed=False):
        if not confirmed:
            raise CoachError("精华笔记必须先由用户明确确认，再传 --confirmed")
        token(note_id)
        slug = token(slug)
        record = self.load(f"notes/drafts/{note_id}.json")
        target = f"notes/knowledge/{slug}.md"
        if record["promoted"] or self.path(target).exists():
            raise CoachError("已整理或目标已存在，不覆盖人工笔记")
        record["promoted"] = True
        self.save_event({"type": "note_promote", "note_id": note_id}, files={
            f"notes/drafts/{note_id}.json": encode(record),
            target: f"# {slug}\n\n来源任务：{record['task_id']}\n确认时间：{now()}\n\n{record['text']}\n"})
        return {"path": str(self.path(target))}


def fetch_json(address, timeout=20):
    req = urllib.request.Request(address, headers={"User-Agent": "ACM-Coach/0.1 (personal study)"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read(32 * 1024 * 1024).decode("utf-8"))


def cf_problem(p, fetched_at):
    if not isinstance(p, dict) or not isinstance(p.get("contestId"), int) or not re.fullmatch(r"[A-Z][0-9A-Z]*", str(p.get("index", ""))) or not p.get("name"):
        raise CoachError("Codeforces 题目数据格式异常")
    if (not isinstance(p["name"], str) or
            (p.get("rating") is not None and type(p["rating"]) is not int) or
            not isinstance(p.get("tags", []), list) or
            any(not isinstance(tag, str) for tag in p.get("tags", []))):
        raise CoachError("Codeforces 标题、rating 或 tags 格式异常")
    return {"title": p["name"], "url": f"https://codeforces.com/problemset/problem/{p['contestId']}/{p['index']}",
            "source": "Codeforces", "resource_type": "problem", "problem_id": f"{p['contestId']}{p['index']}",
            "topics": p.get("tags", []), "rating": p.get("rating"), "retrieved_at": fetched_at,
            "verification": "api_verified", "verified_at": fetched_at,
            "raw_source": {"api": "https://codeforces.com/api/problemset.problems", "contestId": p["contestId"], "index": p["index"]}}


def cf_search(store, tag=None, minimum=None, maximum=None, limit=10, refresh=False, fetch=fetch_json):
    if not 1 <= limit <= 100:
        raise CoachError("limit 必须在 1..100")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise CoachError("min-rating 不得大于 max-rating")
    key = hashlib.sha256((tag or "").encode()).hexdigest()[:16]
    relative = f"cache/cf-{key}.json"
    with store.locked():
        cache = store.load(relative) if store.path(relative).exists() else None
    fresh = cache and (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(cache["retrieved_at"])).total_seconds() < 86400
    warning = None
    if refresh or not fresh:
        address = "https://codeforces.com/api/problemset.problems"
        if tag:
            address += "?" + urllib.parse.urlencode({"tags": tag})
        try:
            payload = fetch(address)
            if not isinstance(payload, dict) or payload.get("status") != "OK":
                raise CoachError("Codeforces API 返回失败状态")
            result = payload.get("result")
            problems = result.get("problems") if isinstance(result, dict) else None
            if not isinstance(problems, list) or not problems:
                raise CoachError("Codeforces API 返回空结果或异常结构")
            stamp = now()
            rows = [cf_problem(p, stamp) for p in problems]
            cache = {"retrieved_at": stamp, "items": rows}
            with store.locked():
                store.commit({relative: encode(cache)})
        except (OSError, ValueError, CoachError) as exc:
            if not cache:
                raise CoachError(f"Codeforces 检索失败：{exc}；请用站点检索/题目链接；未伪造结果") from exc
            warning = f"本次网络/解析失败，仅使用旧缓存：{exc}"
    rows = copy.deepcopy(cache["items"])
    rows = [p for p in rows if (minimum is None or (p["rating"] is not None and p["rating"] >= minimum))
            and (maximum is None or (p["rating"] is not None and p["rating"] <= maximum))]
    if warning:
        for p in rows:
            p["verification"] = "stale_cache"
    return {"items": rows[:limit], "warning": warning, "cache_reused": bool(fresh and not refresh),
            "retrieved_at": cache["retrieved_at"], "note": "API 验证题目元数据，不等于已打开题面或定位官方题解"}


def search_plan(site, query):
    sites = read_json(Path(__file__).parent.parent / "references" / "sites.json")
    if site not in sites:
        raise CoachError("未知站点：" + site)
    rule = sites[site]
    q = f"site:{rule['domain']} {query}"
    return {"site": site, "query": q, "search_url": "https://www.google.com/search?" + urllib.parse.urlencode({"q": q}),
            "verification": "search_plan_only", "rules": rule}


class CSESParser(HTMLParser):
    """Keep the original order and exact section boundaries of the task set."""
    def __init__(self, section):
        super().__init__()
        self.section = section.casefold()
        self.current = ""
        self.heading = None
        self.link = None
        self.items = []

    def handle_starttag(self, tag, attrs):
        if tag == "h2":
            self.heading = []
        if tag == "a" and self.current.casefold() == self.section:
            href = dict(attrs).get("href", "")
            if re.fullmatch(r"/problemset/task/\d+/?", href):
                self.link = [href, []]

    def handle_data(self, data):
        if self.heading is not None:
            self.heading.append(data)
        if self.link is not None:
            self.link[1].append(data)

    def handle_endtag(self, tag):
        if tag == "h2" and self.heading is not None:
            self.current = "".join(self.heading).strip()
            self.heading = None
        if tag == "a" and self.link is not None:
            href, title = self.link
            self.items.append({"title": "".join(title).strip(), "url": "https://cses.fi" + href,
                               "source": "CSES", "problem_id": href.rstrip("/").split("/")[-1]})
            self.link = None


def cses_playlist(section, ident, html=None):
    source = "https://cses.fi/problemset/"
    if html is None:
        req = urllib.request.Request(source, headers={"User-Agent": "ACM-Coach/0.1 (personal study)"})
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                html = response.read(4 * 1024 * 1024).decode("utf-8")
        except (OSError, ValueError) as exc:
            raise CoachError(f"CSES 题单读取失败：{exc}；请用网页工具读取原页，不生成假题单") from exc
    parsed = CSESParser(section)
    parsed.feed(html)
    if not parsed.items or any(not p["title"] for p in parsed.items):
        raise CoachError("CSES 未找到该章节/页面结构改变，请人工核对原页")
    return {"id": token(ident), "title": "CSES — " + section, "source_url": source,
            "topic": section, "ordering": "original", "verification": "page_verified",
            "retrieved_at": now(), "raw_source": {"section": section, "parser": "h2 + problemset/task links"},
            "items": parsed.items}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[4], help="训练仓库根目录")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("status")
    sub.add_parser("next", help="从活跃题单给出下一位置；不自动选题或创建任务")
    a = sub.add_parser("create")
    a.add_argument("--kind", choices=["practice", "topic", "review", "contest"], default="practice")
    for key in ("title", "url", "topic", "playlist"):
        a.add_argument("--" + key)
    a.add_argument("--position", type=int)
    a = sub.add_parser("resume")
    a.add_argument("id")
    a = sub.add_parser("update")
    a.add_argument("id")
    a.add_argument("action", choices=["start", "mode", "idea", "hypothesis", "goal", "code", "hint", "complete", "abandon"])
    a.add_argument("--text")
    a.add_argument("--text-file", type=Path)
    a.add_argument("--level", type=int)
    a.add_argument("--evidence", help="用户提供的提交链接/测试说明；不会自动认定官方 AC")
    a = sub.add_parser("playlist-import")
    a.add_argument("file", type=Path)
    a = sub.add_parser("playlist-status")
    a.add_argument("id")
    a.add_argument("status", choices=["active", "paused"])
    a = sub.add_parser("note")
    a.add_argument("--text")
    a.add_argument("--text-file", type=Path)
    a.add_argument("--task")
    a = sub.add_parser("promote")
    a.add_argument("id")
    a.add_argument("slug")
    a.add_argument("--confirmed", action="store_true")
    a = sub.add_parser("cf-search")
    a.add_argument("--tag")
    a.add_argument("--min-rating", type=int)
    a.add_argument("--max-rating", type=int)
    a.add_argument("--limit", type=int, default=10)
    a.add_argument("--refresh", action="store_true")
    a = sub.add_parser("search-plan")
    a.add_argument("site")
    a.add_argument("query")
    a = sub.add_parser("cses-playlist", help="读取真实章节并输出可导入 JSON，不自动写入题单")
    a.add_argument("--section", required=True)
    a.add_argument("--id", required=True)
    a = sub.add_parser('resource-search', help='真实公开资源检索；失败返回 browser/web search 降级')
    a.add_argument('site', choices=['luogu', 'luogu-daily', 'acwing', 'oi-wiki', 'noi'])
    a.add_argument('query')
    a.add_argument('--kind', choices=['problem', 'playlist', 'article'], default='problem')
    a.add_argument('--limit', type=int, default=10)
    a.add_argument('--page', type=int, default=1)
    a.add_argument('--pdf', type=Path)
    a.add_argument('--index', type=Path)
    a = sub.add_parser('resource-read')
    a.add_argument('url')
    a.add_argument('--strict', action='store_true')
    a = sub.add_parser('resource-playlist', help='输出洛谷真实有序题单，可用 --output 保存后导入')
    a.add_argument('url')
    a.add_argument('--output', type=Path)
    a = sub.add_parser('resource-fallback')
    a.add_argument('site', choices=['luogu', 'luogu-daily', 'acwing', 'oi-wiki', 'noi'])
    a.add_argument('query')
    a = sub.add_parser('noi-index', help='显式从本地PDF重建索引；无文本层时用本地GLM-OCR')
    a.add_argument('--pdf', type=Path)
    a.add_argument('--index', type=Path)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    store = Store(args.root)
    try:
        if args.cmd == "cf-search":
            result = cf_search(store, args.tag, args.min_rating, args.max_rating, args.limit, args.refresh)
        elif args.cmd == "search-plan":
            result = search_plan(args.site, args.query)
        elif args.cmd == "cses-playlist":
            result = cses_playlist(args.section, args.id)
        elif args.cmd.startswith('resource-'):
            import resources
            if args.cmd == 'resource-search':
                result = resources.search(args.site, args.query, args.limit, args.kind, args.page, args.root, args.pdf, args.index)
            elif args.cmd == 'resource-fallback':
                result = {'verification': 'fallback_plan_only', **resources.fallback(args.site, args.query)}
            else:
                result = resources.read(args.url, getattr(args, 'strict', False))
                if args.cmd == 'resource-playlist' and result.get('ok'):
                    result = result['resource']
                    if result.get('resource_type') != 'playlist':
                        raise CoachError('该资源不是题单')
                    if args.output:
                        if args.output.exists():
                            raise CoachError('输出文件已存在，不覆盖；请使用新路径')
                        atomic(args.output, encode(result))
            if result.get('ok') is False:
                print(encode(result), file=sys.stderr, end='')
                return 1
        elif args.cmd == 'noi-index':
            import noi_adapter
            import subprocess
            source = args.pdf or args.root / 'NOI_Syllabus_Edition_2025.pdf'
            target = args.index or args.root / 'resources/noi-syllabus-2025.index.json'
            try:
                index = noi_adapter.build_index(source, target)
            except subprocess.SubprocessError as exc:
                raise CoachError('本地 PDF/OCR 提取失败：' + str(exc)) from exc
            result = {k: v for k, v in index.items() if k != 'pages'}
            result['page_count'] = len(index['pages'])
        else:
            with store.locked():
                if args.cmd == "init":
                    result = store.init()
                else:
                    state = store.state()
                    if args.cmd == "status":
                        result = {"state": state, "profile": store.path("profile.md").read_text(encoding="utf-8"),
                                  "active_task": store.resume(state["active_task"]) if state["active_task"] else None}
                    elif args.cmd == "next":
                        result = []
                        for pid in state["active_playlists"]:
                            pl = store.load(f"playlists/{pid}.json")
                            if pl["status"] == "active" and pl["cursor"] <= len(pl["items"]):
                                result.append({"playlist_id": pid, "position": pl["cursor"], "length": len(pl["items"])})
                    elif args.cmd == "create":
                        result = store.create(args.kind, args.title, args.url, args.topic, args.playlist, args.position)
                    elif args.cmd == "resume":
                        result = store.resume(args.id)
                    elif args.cmd in ("update", "note"):
                        if args.text and args.text_file:
                            raise CoachError("text 与 text-file 不能同时使用")
                        text = args.text_file.read_text(encoding="utf-8-sig") if args.text_file else args.text
                        if not text and (args.cmd == "note" or args.action != "start"):
                            raise CoachError("该操作需要 --text 或 --text-file")
                        if args.cmd == "update":
                            result = store.update(args.id, args.action, text, args.level, args.evidence)
                        else:
                            result = store.note(text, args.task)
                    elif args.cmd == "playlist-import":
                        result = store.playlist(read_json(args.file))
                    elif args.cmd == "playlist-status":
                        name = f"playlists/{token(args.id)}.json"
                        pl = store.load(name)
                        if pl["cursor"] > len(pl["items"]):
                            raise CoachError("题单已完成；重练请创建新任务")
                        pl["status"] = args.status
                        store.save_event({"type": "playlist_status", "playlist_id": args.id, "status": args.status}, files={name: encode(pl)})
                        result = {"id": args.id, "status": args.status}
                    elif args.cmd == "promote":
                        result = store.promote(args.id, args.slug, args.confirmed)
        print(encode(result), end="")
        return 0
    except (CoachError, OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        print(encode({"error": str(exc)}), file=sys.stderr, end="")
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
