"""Read-only Codex app-server skills/list probe. Does not run a model turn."""
import json
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path


def run():
    executable = shutil.which("codex")
    if not executable:
        return {"status": "not_run", "reason": "codex executable missing"}
    root = str(Path(__file__).resolve().parents[1])
    proc = subprocess.Popen([executable, "app-server", "--stdio"], cwd=root,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    messages = queue.Queue()

    def reader():
        for line in proc.stdout:
            try:
                messages.put(json.loads(line))
            except ValueError:
                pass

    threading.Thread(target=reader, daemon=True).start()

    def send(value):
        proc.stdin.write(json.dumps(value) + "\n")
        proc.stdin.flush()

    def response(ident):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                message = messages.get(timeout=min(1, max(0.01, deadline - time.monotonic())))
            except queue.Empty:
                continue
            if message.get("id") == ident:
                return message
        raise TimeoutError("app-server response timeout")

    try:
        send({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "acm_coach_discovery", "version": "0.1.0"}, "capabilities": {"experimentalApi": True}}})
        initialized = response(1)
        if "error" in initialized:
            return {"status": "failed", "error": initialized["error"]}
        send({"method": "initialized", "params": {}})
        send({"id": 2, "method": "skills/list", "params": {"cwds": [root], "forceReload": True}})
        reply = response(2)
        if "error" in reply:
            return {"status": "failed", "error": reply["error"]}
        found = []
        for item in reply.get("result", {}).get("data", []):
            for skill in item.get("skills", []):
                if skill.get("name") == "acm-coach":
                    found.append({k: skill.get(k) for k in ("name", "path", "enabled", "scope")})
        return {"status": "passed" if found else "not_found", "skills": found,
                "note": "仅验证技能发现；没有启动模型或创建聊天"}
    except (OSError, TimeoutError) as exc:
        return {"status": "failed", "error": str(exc)}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        for stream in (proc.stdin, proc.stdout):
            stream.close()


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=True, indent=2))
