"""应用入口：启动 GUI + 后台网关线程"""
import sys
import threading

import uvicorn
from PySide6.QtWidgets import QApplication

from app.core.config import settings
from app.ui.main_window import MainWindow


def run_gateway():
    """在后台线程运行 FastAPI 网关"""
    uvicorn.run(
        "app.core.gateway:app",
        host=settings.gateway_host,
        port=settings.gateway_port,
        log_level="warning",
        access_log=False,
    )


def main():
    # 启动网关线程
    gateway_thread = threading.Thread(target=run_gateway, daemon=True)
    gateway_thread.start()

    # 等待网关启动
    import time
    time.sleep(1.5)

    # 启动 GUI
    app = QApplication(sys.argv)
    app.setApplicationName("AIOptimizer")
    app.setOrganizationName("ph6977")

    window = MainWindow()
    window.show()

    # 确保退出时清理
    def on_exit():
        import asyncio

        from app.providers import ProviderFactory
        asyncio.run(ProviderFactory.close_all())

    app.aboutToQuit.connect(on_exit)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()