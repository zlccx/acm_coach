"""Isolated persistence, recovery, CLI and adapter tests. Never use real data/."""
import concurrent.futures
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / ".agents/skills/acm-coach/scripts/coach.py"
spec = importlib.util.spec_from_file_location("coach", SCRIPT)
coach = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coach)

PAYLOAD = {"status": "OK", "result": {"problems": [
    {"contestId": 4, "index": "A", "name": "Watermelon", "rating": 800, "tags": ["math"]},
    {"contestId": 1, "index": "A", "name": "Theatre Square", "rating": 1000, "tags": ["math"]}
]}}


def playlist():
    return {"id": "ordered", "title": "SECRET technique", "topic": "SECRET", "source_url": "https://example.org/list",
            "items": [{"title": "First", "url": "https://example.org/1", "tags": ["SECRET"]},
                      {"title": "Second", "url": "https://example.org/2"},
                      {"title": "Third", "url": "https://example.org/3"}]}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = coach.Store(Path(self.tmp.name) / "训练仓库")
        with self.store.locked():
            self.store.init()

    def create(self, **kwargs):
        with self.store.locked():
            return self.store.create("practice", "Watermelon", "https://codeforces.com/problemset/problem/4/A", **kwargs)

    def cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.store.root), *args],
                              capture_output=True, encoding="utf-8", timeout=20)

    def test_init_does_not_touch_existing_profile_or_inbox(self):
        profile = self.store.path("profile.md")
        profile.write_text("人工目标", encoding="utf-8")
        with self.store.locked():
            self.store.init()
        self.assertEqual(profile.read_text(encoding="utf-8"), "人工目标")
        self.assertEqual(self.store.path("logs.jsonl").read_text(), "")

    def test_repeated_problem_new_id_and_cross_process_resume(self):
        first = self.create()
        second = self.create()
        self.assertNotEqual(first["id"], second["id"])
        with self.store.locked():
            self.store.update(first["id"], "idea", "用户真实思路")
            self.store.update(first["id"], "start")
        result = self.cli("resume", first["id"])
        self.assertEqual(result.returncode, 0, result.stderr)
        recovered = json.loads(result.stdout)
        self.assertEqual(recovered["user_ideas"][0]["text"], "用户真实思路")
        self.assertEqual(recovered["status"], "in_progress")

    def test_concurrent_ids_are_unique_and_log_valid(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.cli("create", "--title", "Repeat", "--url", "https://example.org/problem"), range(8)))
        for r in results:
            self.assertEqual(r.returncode, 0, r.stderr)
        ids = [json.loads(r.stdout)["id"] for r in results]
        self.assertEqual(len(set(ids)), 8)
        events = [json.loads(x) for x in self.store.path("logs.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(events), 8)
        self.assertEqual(len({e["event_id"] for e in events}), 8)

    def test_strict_whitelist_and_provenance(self):
        with self.store.locked():
            self.store.playlist(playlist())
            t = self.store.create("practice", playlist="ordered")
            self.store.update(t["id"], "hypothesis", "SECRET guessed bottleneck")
            safe = self.store.resume(t["id"])
            self.assertNotIn("SECRET", json.dumps(safe))
            self.assertNotIn("topic", safe)
            self.assertEqual(safe["user_ideas"], [])
            self.store.update(t["id"], "mode", "learning")
            full = self.store.resume(t["id"])
            self.assertIn("SECRET", full["hypotheses"][0]["text"])
            self.assertEqual(full["user_ideas"], [])

    def test_hints_cannot_skip_or_reset_on_reopen(self):
        t = self.create()
        with self.store.locked():
            with self.assertRaises(coach.CoachError):
                self.store.update(t["id"], "hint", "too much", 2)
            self.store.update(t["id"], "hint", "first", 1)
        resumed = json.loads(self.cli("resume", t["id"]).stdout)
        self.assertEqual(resumed["hints"][0]["level"], 1)
        with self.store.locked():
            self.store.update(t["id"], "hint", "second", 2)
            self.store.update(t["id"], "mode", "learning")
            self.store.update(t["id"], "mode", "strict")
            self.assertEqual(len(self.store.resume(t["id"])["hints"]), 2)

    def test_contest_no_hint_in_strict_mode(self):
        with self.store.locked():
            t = self.store.create("contest", "Virtual", "https://codeforces.com/contest/1")
            with self.assertRaises(coach.CoachError):
                self.store.update(t["id"], "hint", "hint", 1)

    def test_playlist_order_cursor_and_repeat_completion(self):
        with self.store.locked():
            pl = self.store.playlist(playlist())
            self.assertEqual([x["title"] for x in pl["items"]], ["First", "Second", "Third"])
            second = self.store.create("practice", playlist="ordered", position=2)
            self.store.update(second["id"], "complete", "用户自述完成")
            self.assertEqual(self.store.load("playlists/ordered.json")["cursor"], 1)
            first = self.store.create("practice", playlist="ordered")
            self.store.update(first["id"], "complete", "本地样例通过", evidence="local only")
            self.assertEqual(self.store.load("playlists/ordered.json")["cursor"], 3)
            self.assertEqual(self.store.task(first["id"])["result"]["verdict"], "self_reported")
            before = self.store.path("logs.jsonl").read_bytes()
            with self.assertRaises(coach.CoachError):
                self.store.update(first["id"], "complete", "duplicate")
            self.assertEqual(self.store.path("logs.jsonl").read_bytes(), before)

    def test_abandon_does_not_advance_playlist(self):
        with self.store.locked():
            self.store.playlist(playlist())
            t = self.store.create("practice", playlist="ordered")
            self.store.update(t["id"], "abandon", "先补知识")
            self.assertEqual(self.store.load("playlists/ordered.json")["cursor"], 1)

    def test_notes_require_confirmation_and_never_overwrite(self):
        with self.store.locked():
            n = self.store.note("草稿")
            with self.assertRaises(coach.CoachError):
                self.store.promote(n["id"], "trick")
            self.store.promote(n["id"], "trick", True)
            target = self.store.path("notes/knowledge/trick.md")
            target.write_text("人工修改", encoding="utf-8")
            other = self.store.note("别的草稿")
            with self.assertRaises(coach.CoachError):
                self.store.promote(other["id"], "trick", True)
            self.assertEqual(target.read_text(encoding="utf-8"), "人工修改")

    def test_transaction_recovers_interrupted_multi_file_commit(self):
        original = coach.atomic
        count = 0

        def interrupted(path, content):
            nonlocal count
            count += 1
            if count == 3:
                raise OSError("模拟写第二个文件时中断")
            return original(path, content)

        with self.store.locked():
            with patch.object(coach, "atomic", interrupted):
                with self.assertRaises(OSError):
                    self.store.commit({"a.json": "one", "b.json": "two"})
        self.assertTrue(self.store.path(".transaction.json").exists())
        with self.store.locked():
            self.assertEqual(self.store.path("a.json").read_text(), "one")
            self.assertEqual(self.store.path("b.json").read_text(), "two")
        self.assertFalse(self.store.path(".transaction.json").exists())

    def test_invalid_input_leaves_history_unchanged(self):
        before = self.store.path("logs.jsonl").read_bytes()
        with self.store.locked():
            for address in ("javascript:alert(1)", "file:///tmp/a", "https://user:secret@example.org/a"):
                with self.assertRaises(coach.CoachError):
                    self.store.create("practice", "bad", address)
            with self.assertRaises(coach.CoachError):
                self.store.path("../outside")
            with self.assertRaises(coach.CoachError):
                self.store.task("../../oops")
        self.assertEqual(self.store.path("logs.jsonl").read_bytes(), before)

    def test_unknown_schema_not_overwritten(self):
        self.store.path("state.json").write_text('{"schema_version":99}', encoding="utf-8")
        r = self.cli("init")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(json.loads(self.store.path("state.json").read_text())["schema_version"], 99)

    def test_cli_unicode_text_file_and_failure_exit(self):
        t = self.create()
        text = self.store.root / "用户思路.txt"
        text.write_text('反例："引号"、$()、`code`\n第二行', encoding="utf-8")
        r = self.cli("update", t["id"], "idea", "--text-file", str(text))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["user_ideas"][0]["text"], text.read_text(encoding="utf-8"))
        self.assertEqual(self.cli("resume", "P99999").returncode, 1)

    def test_code_paths_stay_inside_solutions(self):
        t = self.create()
        with self.store.locked():
            for path in ("../outside.cpp", "solutions/../../evil.cpp", "solutions/main.py"):
                with self.assertRaises(coach.CoachError):
                    self.store.update(t["id"], "code", path)
            self.store.update(t["id"], "code", "solutions/P00001.cpp")

    def test_pause_next_and_resume_without_changing_order(self):
        with self.store.locked():
            self.store.playlist(playlist())
        self.assertEqual(len(json.loads(self.cli("next").stdout)), 1)
        self.assertEqual(self.cli("playlist-status", "ordered", "paused").returncode, 0)
        self.assertEqual(json.loads(self.cli("next").stdout), [])
        self.assertEqual(self.cli("playlist-status", "ordered", "active").returncode, 0)
        self.assertEqual(json.loads(self.cli("next").stdout)[0]["position"], 1)

    def test_interrupted_event_recovers_without_duplicate_log(self):
        task = self.create()
        with self.store.locked():
            original = coach.atomic
            def interrupted(path, content):
                if Path(path).name == "logs.jsonl":
                    raise OSError("模拟日志写入中断")
                return original(path, content)
            with patch.object(coach, "atomic", interrupted):
                with self.assertRaises(OSError):
                    self.store.update(task["id"], "idea", "这条思路只记录一次")
        with self.store.locked():
            self.assertEqual(len(self.store.task(task["id"])["user_ideas"]), 1)
        with self.store.locked():
            events = [json.loads(x) for x in self.store.path("logs.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([x["type"] for x in events], ["task_create", "idea"])

    def test_existing_lock_is_not_stolen(self):
        self.store.path(".lock").write_text("999999")
        with patch.object(coach.time, "monotonic", side_effect=[0, 6]):
            with self.assertRaises(coach.CoachError):
                with self.store.locked():
                    self.fail("must not acquire an existing lock")
        self.assertTrue(self.store.path(".lock").exists())
        self.store.path(".lock").unlink()


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = coach.Store(self.tmp.name)

    def test_cf_real_schema_filter_and_cached_provenance(self):
        calls = []
        def fetch(address):
            calls.append(address)
            return copy.deepcopy(PAYLOAD)
        first = coach.cf_search(self.store, "math", 900, 1100, fetch=fetch)
        self.assertEqual(first["items"][0]["problem_id"], "1A")
        self.assertIn("tags=math", calls[0])
        second = coach.cf_search(self.store, "math", fetch=lambda _: self.fail("fresh cache must avoid network"))
        self.assertTrue(second["cache_reused"])
        self.assertEqual(first["retrieved_at"], second["retrieved_at"])

    def test_cf_failed_refresh_uses_stale_cache_and_retains_time(self):
        original = coach.cf_search(self.store, fetch=lambda _: PAYLOAD)
        def fail(_):
            raise OSError("403 forbidden")
        fallback = coach.cf_search(self.store, refresh=True, fetch=fail)
        self.assertIn("403", fallback["warning"])
        self.assertEqual(fallback["items"][0]["verification"], "stale_cache")
        self.assertEqual(fallback["retrieved_at"], original["retrieved_at"])

    def test_cf_failure_without_cache_is_explicit(self):
        for payload in ({"status": "FAILED"}, {"status": "OK", "result": []},
                        {"status": "OK", "result": {"problems": []}},
                        {"status": "OK", "result": {"problems": [{"name": "fake"}]}}):
            with self.subTest(payload=payload):
                with self.assertRaises(coach.CoachError):
                    coach.cf_search(self.store, fetch=lambda _: payload)

    def test_cf_malformed_rating_is_a_reported_adapter_failure(self):
        payload = copy.deepcopy(PAYLOAD)
        payload["result"]["problems"][0]["rating"] = "not-a-rating"
        with self.assertRaises(coach.CoachError):
            coach.cf_search(self.store, minimum=1000, fetch=lambda _: payload)

    def test_cses_order_nested_text_and_section_boundary(self):
        html = '<h2>Before</h2><a href="/problemset/task/1">Ignore</a><h2>Dynamic Programming</h2><ul><li><a href="/problemset/task/1633"><b>Dice</b> Combinations</a><li><a href="/problemset/task/1634">Minimizing Coins</a></ul><h2>After</h2><a href="/problemset/task/9">Ignore</a>'
        pl = coach.cses_playlist("Dynamic Programming", "cses-dp", html)
        self.assertEqual([x["problem_id"] for x in pl["items"]], ["1633", "1634"])
        self.assertEqual(pl["items"][0]["title"], "Dice Combinations")
        with self.assertRaises(coach.CoachError):
            coach.cses_playlist("missing", "empty", html)

    def test_search_plan_never_claims_search_execution(self):
        result = coach.search_plan("luogu", "点分治 题单")
        self.assertEqual(result["verification"], "search_plan_only")
        self.assertIn("site:luogu.com.cn", result["query"])


if __name__ == "__main__":
    unittest.main()
