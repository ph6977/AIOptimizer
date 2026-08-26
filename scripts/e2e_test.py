"""E2E 验证脚本：模拟 OpenAI 兼容客户端调用网关"""
import json
import os
import subprocess
import sys
import time

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "http://127.0.0.1:8000"

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


def main() -> None:
    env = os.environ.copy()
    env["AIOPTIMIZER_TEST_MODE"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.core.gateway:app",
         "--host", "127.0.0.1", "--port", "8000", "--log-level", "warning"],
        cwd=ROOT, env=env,
    )
    try:
        # 等待就绪
        for _ in range(30):
            time.sleep(0.5)
            try:
                if httpx.get(f"{BASE}/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                continue
        else:
            print("Gateway failed to start")
            sys.exit(1)

        print("=== 1. Health ===")
        r = httpx.get(f"{BASE}/health", timeout=5)
        check("health 200", r.status_code == 200, str(r.json()))

        print("=== 2. /v1/models ===")
        r = httpx.get(f"{BASE}/v1/models", timeout=10)
        data = r.json()
        model_ids = [m["id"] for m in data.get("data", [])]
        check("models 200", r.status_code == 200)
        check("mock-model listed", any("mock" in m for m in model_ids), str(model_ids))

        print("=== 3. 非流式 chat（模拟 Cherry Studio）===")
        r = httpx.post(f"{BASE}/v1/chat/completions", timeout=15, json={
            "model": "",
            "messages": [
                {"role": "system", "content": "你是一个助手"},
                {"role": "user", "content": "请介绍一下 Python 装饰器"},
            ],
            "temperature": 0.7,
            "stream": False,
        })
        check("chat 200", r.status_code == 200)
        if r.status_code == 200:
            data = r.json()
            choices = data.get("choices", [])
            content = choices[0]["message"]["content"] if choices else ""
            check("choices non-empty", bool(choices))
            check("content non-empty", len(content) > 0, content[:50])
            check("usage present", "usage" in data, str(data.get("usage")))
            opt = data.get("optimization")
            check("optimization metadata", isinstance(opt, dict),
                  f"routing={opt.get('routing')}")
            check("X-Request-ID header", "x-request-id" in {k.lower() for k in r.headers})

        print("=== 4. 流式 chat（SSE）===")
        chunks: list[str] = []
        with httpx.stream("POST", f"{BASE}/v1/chat/completions", timeout=15, json={
            "model": "",
            "messages": [{"role": "user", "content": "什么是 LRU 缓存"}],
            "stream": True,
        }) as resp:
            check("stream 200", resp.status_code == 200)
            ctype = resp.headers.get("content-type", "")
            check("SSE content-type", "text/event-stream" in ctype, ctype)
            done = False
            for line in resp.iter_lines():
                if line.startswith("data: [DONE]"):
                    done = True
                elif line.startswith("data: "):
                    try:
                        payload = json.loads(line[6:])
                        delta = payload["choices"][0].get("delta", {})
                        chunks.append(delta.get("content", ""))
                    except (json.JSONDecodeError, KeyError, IndexError):
                        pass
            check("stream [DONE] received", done)
            full = "".join(chunks)
            check("stream content non-empty", len(full) > 0, f"{len(chunks)} chunks: {full[:50]}")

        print("=== 5. 用量统计 ===")
        r = httpx.get(f"{BASE}/v1/usage/stats", params={"days": 7}, timeout=5)
        check("stats 200", r.status_code == 200)
        summary = r.json().get("summary", {})
        check("stats has requests", (summary.get("requests") or 0) > 0, str(summary))

        print("=== 6. 配置端点 ===")
        r = httpx.get(f"{BASE}/v1/config", timeout=5)
        check("config 200", r.status_code == 200)
        providers = r.json().get("providers", [])
        check("mock provider in config", any(p["name"] == "mock" for p in providers))

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("\n=== E2E Summary ===")
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"{passed}/{len(results)} checks passed")
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, d in failed:
        print(f"  FAILED: {n} {d}")
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
