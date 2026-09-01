"""
AIOptimizer 应用程序主入口
"""

import os
import sys

# ===== 最先执行：将 CWD 切换到 exe/脚本所在目录 =====
if getattr(sys, "frozen", False):
    _app_dir = os.path.dirname(sys.executable)
else:
    _app_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(_app_dir)

import threading
import time
import traceback

import uvicorn
from PySide6.QtWidgets import QApplication

from app.core.config import settings
from app.ui.main_window import MainWindow

# 预导入 gateway 模块，确保在主线程完成模块加载
from app.core.gateway import app as _gateway_app  # noqa: F401


def run_gateway() -> None:
    """在后台线程中运行 FastAPI 网关服务"""
    try:
        from app.core.gateway import app as gateway_app

        uvicorn.run(
            gateway_app,
            host=settings.gateway_host,
            port=settings.gateway_port,
            log_level="warning",
            access_log=False,
        )
    except Exception:
        traceback.print_exc()


def main() -> None:
    """应用程序主函数"""
    gateway_thread = threading.Thread(target=run_gateway, daemon=True)
    gateway_thread.start()

    import httpx

    for _ in range(30):
        time.sleep(0.5)
        try:
            resp = httpx.get(
                f"http://{settings.gateway_host}:{settings.gateway_port}/health",
                timeout=1.0,
            )
            if resp.status_code == 200:
                break
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("AIOptimizer")
    app.setOrganizationName("ph6977")

    window = MainWindow()
    window.show()

    def on_exit() -> None:
        import asyncio
        from app.providers import ProviderFactory

        asyncio.run(ProviderFactory.close_all())

    app.aboutToQuit.connect(on_exit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
