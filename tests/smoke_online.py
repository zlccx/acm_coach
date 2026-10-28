"""Opt-in real public-resource smoke; all writes are in a temporary directory."""
import importlib.util
import json
from pathlib import Path
import tempfile

path = Path(__file__).resolve().parents[1] / ".agents/skills/acm-coach/scripts/coach.py"
spec = importlib.util.spec_from_file_location("coach", path)
coach = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coach)


def run():
    report = {"at": coach.now(), "checks": {}}
    with tempfile.TemporaryDirectory(prefix="acm-coach-online-") as tmp:
        store = coach.Store(tmp)
        with store.locked():
            store.init()
        try:
            result = coach.cf_search(store, tag="dp", minimum=1200, maximum=1600, limit=3, refresh=True)
            if not result["items"] or result["warning"]:
                raise coach.CoachError("未获得已验证题目")
            report["checks"]["codeforces"] = {"status": "passed", "items": result["items"]}
        except coach.CoachError as exc:
            report["checks"]["codeforces"] = {"status": "unavailable", "error": str(exc)}
        try:
            pl = coach.cses_playlist("Dynamic Programming", "cses-dp-smoke")
            # Separately restore Store and round-trip an actual ordered playlist.
            with store.locked():
                store.playlist(pl)
                task = store.create("practice", playlist=pl["id"])
                store.update(task["id"], "idea", "在线冒烟的测试思路，仅存在临时仓库")
            reopened = coach.Store(tmp)
            with reopened.locked():
                restored = reopened.resume(task["id"])
                assert restored["source_url"] == pl["items"][0]["url"]
                assert len(restored["user_ideas"]) == 1
                assert "topic" not in restored
                reopened.update(task["id"], "complete", "临时测试完成，并非真实学习或官方 AC")
                assert reopened.load(f"playlists/{pl['id']}.json")["cursor"] == 2
            report["checks"]["cses_ordered_playlist_roundtrip"] = {
                "status": "passed", "source_url": pl["source_url"], "section": pl["topic"],
                "count": len(pl["items"]), "first_three": pl["items"][:3],
                "last": pl["items"][-1], "note": "独立 Store 恢复，不是独立模型会话验收"}
        except (coach.CoachError, AssertionError) as exc:
            report["checks"]["cses_ordered_playlist_roundtrip"] = {"status": "failed", "error": str(exc)}
    return report


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=True, indent=2))
