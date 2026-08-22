"""启动并驻留 Mock OpenAI 服务器"""
import subprocess
import sys
import os
import time
import atexit

SERVER_SCRIPT = os.path.join(os.path.dirname(__file__), "mock_openai_server.py")
PORT = 8001

# 杀掉旧进程
def kill_port(port):
    import subprocess
    result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if f":{port}" in line and "LISTENING" in line:
            parts = line.split()
            pid = parts[-1]
            subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)

kill_port(PORT)
time.sleep(0.5)

# 启动新进程
proc = subprocess.Popen(
    [sys.executable, SERVER_SCRIPT],
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

# 等待就绪
for _ in range(20):
    try:
        import httpx
        r = httpx.get(f"http://127.0.0.1:{PORT}/models", timeout=1)
        if r.status_code == 200:
            print(f"Mock server started on port {PORT}, PID={proc.pid}")
            break
    except Exception:
        time.sleep(0.2)
else:
    print("Mock server failed to start")
    sys.exit(1)

# 注册退出时清理
def cleanup():
    try:
        proc.terminate()
    except Exception:
        pass

atexit.register(cleanup)

# 保持脚本运行（或写 PID 文件供外部管理）
pid_file = os.path.join(os.path.dirname(__file__), ".mock_server.pid")
with open(pid_file, "w") as f:
    f.write(str(proc.pid))

print("Mock server running in background. PID written to", pid_file)

# 防止主进程退出导致子进程被杀 - 这里简单 sleep 等待
try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    cleanup()