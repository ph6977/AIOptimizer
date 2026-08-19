"""主窗口"""

from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMenu,
    QSystemTrayIcon,
    QTabWidget,
)

from app.core.config import settings
from app.ui.pages.dashboard import DashboardPage
from app.ui.pages.sessions import SessionsPage
from app.ui.pages.settings import SettingsPage
from app.ui.pages.transparency import TransparencyPage
from app.ui.widgets.toast import ToastManager


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AIOptimizer - AI 优化网关")
        self.resize(1000, 700)
        self.toast = ToastManager(self)

        # 中央标签页
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # 页面实例
        self.dashboard = DashboardPage()
        self.settings_page = SettingsPage()
        self.sessions_page = SessionsPage()
        self.transparency_page = TransparencyPage()

        self.tabs.addTab(self.dashboard, "📊 用量面板")
        self.tabs.addTab(self.transparency_page, "🔍 压缩透明")
        self.tabs.addTab(self.sessions_page, "💬 会话管理")
        self.tabs.addTab(self.settings_page, "⚙️ 设置")

        # 状态栏
        self.statusBar().showMessage(
            f"网关: http://{settings.gateway_host}:{settings.gateway_port} | 就绪"
        )

        # 系统托盘
        self._init_tray()

        # 定时刷新面板
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._refresh_dashboard)
        self.refresh_timer.start(5000)  # 5 秒刷新一次

    def _init_tray(self) -> None:
        self.tray = QSystemTrayIcon(self)
        self.tray.setToolTip("AIOptimizer - AI 优化网关")

        # 创建菜单
        menu = QMenu()
        show_action = QAction("显示主窗口", self)
        show_action.triggered.connect(self.showNormal)
        menu.addAction(show_action)

        copy_url_action = QAction("复制网关地址", self)
        copy_url_action.triggered.connect(self._copy_gateway_url)
        menu.addAction(copy_url_action)

        menu.addSeparator()

        self.toggle_compress_action = QAction("开启压缩", self)
        self.toggle_compress_action.setCheckable(True)
        self.toggle_compress_action.setChecked(settings.compression_enabled)
        self.toggle_compress_action.toggled.connect(self._toggle_compression)
        menu.addAction(self.toggle_compress_action)

        menu.addSeparator()

        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self._quit_app)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_activated(self, reason: Any) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.showNormal()
            self.activateWindow()

    def _copy_gateway_url(self) -> None:
        url = f"http://{settings.gateway_host}:{settings.gateway_port}"
        QApplication.clipboard().setText(url)
        self.toast.show(f"已复制: {url}", 2000)

    def _toggle_compression(self, checked: bool) -> None:
        settings.compression_enabled = checked
        self.toggle_compress_action.setText("关闭压缩" if checked else "开启压缩")
        self.toast.show(f"压缩已{'开启' if checked else '关闭'}", 2000)

    def _refresh_dashboard(self) -> None:
        self.dashboard.refresh()

    def _quit_app(self) -> None:
        self.tray.hide()
        QApplication.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        # 关闭窗口时最小化到托盘
        if self.tray.isVisible():
            self.hide()
            self.toast.show("已最小化到系统托盘", 3000)
            event.ignore()
        else:
            event.accept()
