"""会话管理页面"""

import json

import httpx
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
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
            url = (
                f"http://{settings.gateway_host}:{settings.gateway_port}/v1/usage/stats"
            )
            resp = httpx.get(url, params={"days": self.days}, timeout=10.0)
            if resp.status_code == 200:
                # 这里简化：实际应有专门的会话查询 API
                self.finished.emit([])
            else:
                self.error.emit(f"HTTP {resp.status_code}")
        except httpx.HTTPError as e:
            self.error.emit(str(e))


class SessionsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        # 顶部控制栏
        control = QHBoxLayout()
        control.addWidget(QLabel("会话管理 (数据来源: 用量日志)"))

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索会话/请求ID...")
        self.search_edit.setMaximumWidth(300)
        control.addWidget(self.search_edit)

        export_btn = QPushButton("📤 导出选中会话")
        export_btn.clicked.connect(self._export_sessions)
        control.addWidget(export_btn)

        layout.addLayout(control)

        # 会话表格
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["时间", "Provider", "模型", "请求数", "总 Tokens", "成本", "节省率"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self.table)

        # 底部状态
        self.status_label = QLabel("暂无会话数据（需实现 /v1/sessions API）")
        self.status_label.setStyleSheet("color: #666; padding: 8px;")
        layout.addWidget(self.status_label)

        # 占位提示
        placeholder = QLabel("""
        <div style='text-align:center; color:#999; padding:40px;'>
            <h3>📝 会话管理功能待完善</h3>
            <p>需要后端实现 <code>/v1/sessions</code> API 以支持：</p>
            <ul style='text-align:left; display:inline-block;'>
                <li>按会话 ID 分组查询</li>
                <li>会话详情：完整对话历史、压缩详情、质量分</li>
                <li>书签/标签管理</li>
                <li>导出 Markdown/JSON</li>
            </ul>
        </div>
        """)
        placeholder.setWordWrap(True)
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(placeholder)

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

        # 简化导出
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
                        f.write(f"## {d.get('时间', '')}\n")
                        f.writelines(f"- **{k}**: {v}\n" for k, v in d.items())
                        f.write("\n")
            else:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "成功", f"已导出 {len(data)} 条记录到 {path}")
        except OSError as e:
            QMessageBox.critical(self, "错误", str(e))
