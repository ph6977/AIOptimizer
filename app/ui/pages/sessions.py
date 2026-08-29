"""会话管理页面"""

import json

import httpx
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.config import settings


class SessionsWorker(QThread):
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, days: int, limit: int) -> None:
        super().__init__()
        self.days = days
        self.limit = limit

    def run(self) -> None:
        try:
            url = f"http://{settings.gateway_host}:{settings.gateway_port}/v1/sessions"
            resp = httpx.get(url, params={"days": self.days, "limit": self.limit}, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                self.finished.emit(data.get("sessions", []))
            else:
                self.error.emit(f"HTTP {resp.status_code}")
        except httpx.HTTPError as e:
            self.error.emit(str(e))


class SessionsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        # 顶部控制栏
        control = QHBoxLayout()
        control.addWidget(QLabel("会话管理"))

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索会话ID...")
        self.search_edit.setMaximumWidth(300)
        control.addWidget(self.search_edit)

        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.clicked.connect(self.refresh)
        control.addWidget(self.refresh_btn)

        export_btn = QPushButton("📤 导出会话")
        export_btn.clicked.connect(self._export_sessions)
        control.addWidget(export_btn)

        layout.addLayout(control)

        # 会话表格
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            ["会话 ID", "请求数", "总 Tokens", "成本", "节省 Tokens", "Provider", "模型", "最后活动"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self.table)

        # 底部状态
        self.status_label = QLabel("加载中...")
        self.status_label.setStyleSheet("color: #666; padding: 8px;")
        layout.addWidget(self.status_label)

    def refresh(self) -> None:
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("刷新中...")
        self.worker = SessionsWorker(days=7, limit=50)
        self.worker.finished.connect(self._on_data_ready)
        self.worker.error.connect(self._on_error)
        self.worker.finished.connect(lambda _: self._reset_refresh_btn())
        self.worker.start()

    def _reset_refresh_btn(self) -> None:
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("🔄 刷新")

    def _on_data_ready(self, sessions: list) -> None:
        self.table.setRowCount(0)

        if not sessions:
            self.status_label.setText("暂无会话数据（需要先发起 API 请求）")
            return

        for session in sessions:
            row = self.table.rowCount()
            self.table.insertRow(row)

            session_id = session.get("session_id", "")[:12] + "..."
            request_count = str(session.get("request_count", 0))
            total_tokens = f"{session.get('total_tokens', 0):,}"
            total_cost = f"${session.get('total_cost', 0):.4f}"
            saved_tokens = f"{session.get('saved_tokens', 0):,}"
            providers = session.get("providers", "")
            models = session.get("models", "")
            last_request = session.get("last_request", "")[:19]

            self.table.setItem(row, 0, QTableWidgetItem(session_id))
            self.table.setItem(row, 1, QTableWidgetItem(request_count))
            self.table.setItem(row, 2, QTableWidgetItem(total_tokens))
            self.table.setItem(row, 3, QTableWidgetItem(total_cost))
            self.table.setItem(row, 4, QTableWidgetItem(saved_tokens))
            self.table.setItem(row, 5, QTableWidgetItem(providers))
            self.table.setItem(row, 6, QTableWidgetItem(models))
            self.table.setItem(row, 7, QTableWidgetItem(last_request))

        self.status_label.setText(f"共 {len(sessions)} 个会话")

    def _on_error(self, err: str) -> None:
        self.status_label.setText(f"加载失败: {err}")

    def _export_sessions(self) -> None:
        rows = {item.row() for item in self.table.selectedItems()}
        if not rows:
            QMessageBox.warning(self, "提示", "请先选择要导出的行")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "导出会话", "sessions.json", "JSON Files (*.json);;Markdown (*.md)"
        )
        if not path:
            return

        # 导出数据
        data = []
        for row in sorted(rows):
            row_data = {}
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                header_item = self.table.horizontalHeaderItem(col)
                header = header_item.text() if header_item else ""
                row_data[header] = item.text() if item else ""
            data.append(row_data)

        try:
            if path.endswith(".md"):
                with open(path, "w", encoding="utf-8") as f:
                    f.write("# 会话导出\n\n")
                    for d in data:
                        f.write(f"## 会话 {d.get('会话 ID', '')}\n")
                        f.writelines(f"- **{k}**: {v}\n" for k, v in d.items())
                        f.write("\n")
            else:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "成功", f"已导出 {len(data)} 条记录到 {path}")
        except OSError as e:
            QMessageBox.critical(self, "错误", str(e))
