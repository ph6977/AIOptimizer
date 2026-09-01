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

import socket
import threading
import time
import traceback

from PySide6.QtWidgets import QApplication

from app.core.config import settings
from app.ui.main_window import MainWindow


def _check_port_available(host: str, port: int) -> bool:
    """检查端口是否可用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _find_available_port(host: str, start_port: int) -> int:
    """从 start_port 开始寻找可用端口"""
    port = start_port
    while port < start_port + 100:
        if _check_port_available(host, port):
            return port
        port += 1
    return start_port


def run_gateway(port: int) -> None:
    """在后台线程中运行 FastAPI 网关服务"""
    try:
        import uvicorn
        from app.core.gateway import app as gateway_app

        uvicorn.run(
            gateway_app,
            host=settings.gateway_host,
            port=port,
            log_level="warning",
            access_log=False,
        )
    except Exception:
        traceback.print_exc()


def main() -> None:
    """应用程序主函数"""
    # 预导入 gateway 模块，确保在主线程完成模块加载
    from app.core.gateway import app as _gateway_app  # noqa: F401

    # 寻找可用端口，避免绑定冲突
    gw_port = _find_available_port(settings.gateway_host, settings.gateway_port)
    settings.gateway_port = gw_port

    gateway_thread = threading.Thread(
        target=run_gateway, args=(gw_port,), daemon=True
    )
    gateway_thread.start()

    import httpx

    for _ in range(30):
        time.sleep(0.5)
        try:
            resp = httpx.get(
                f"http://{settings.gateway_host}:{gw_port}/health",
                timeout=1.0,
            )
            if resp.status_code == 200:
                break
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("AIOptimizer")
    app.setOrganizationName("ph6977")

    # 设置应用图标（用 Qt 内置图标，避免资源文件缺失问题）
    from PySide6.QtGui import QIcon, QPixmap, QColor, QPainter

    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 120, 215))
    painter = QPainter(pixmap)
    painter.setPen(QColor(255, 255, 255))
    from PySide6.QtCore import Qt

    font = painter.font()
    font.setPixelSize(36)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "AI")
    painter.end()
    app.setWindowIcon(QIcon(pixmap))

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
