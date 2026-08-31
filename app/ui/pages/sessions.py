"""会话管理页面"""

import json

import httpx
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
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
        self._sessions: list[dict] = []
        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        # 顶部控制栏
        control = QHBoxLayout()
        control.addWidget(QLabel("会话管理"))

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索会话ID/标签...")
        self.search_edit.setMaximumWidth(300)
        self.search_edit.textChanged.connect(self._filter_rows)
        control.addWidget(self.search_edit)

        self.bookmark_only = QCheckBox("仅书签")
        self.bookmark_only.toggled.connect(self._filter_rows)
        control.addWidget(self.bookmark_only)

        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.clicked.connect(self.refresh)
        control.addWidget(self.refresh_btn)

        export_btn = QPushButton("📤 导出会话")
        export_btn.clicked.connect(self._export_sessions)
        control.addWidget(export_btn)

        layout.addLayout(control)

        # 会话表格
        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels(
            ["", "会话 ID", "请求数", "总 Tokens", "成本", "节省 Tokens", "Provider", "模型", "标签", "最后活动"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setColumnWidth(0, 30)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        layout.addWidget(self.table)

        # 底部操作栏
        bottom_bar = QHBoxLayout()
        self.bookmark_btn = QPushButton("⭐ 切换书签")
        self.bookmark_btn.clicked.connect(self._toggle_bookmark)
        bottom_bar.addWidget(self.bookmark_btn)

        self.tag_btn = QPushButton("🏷 设置标签")
        self.tag_btn.clicked.connect(self._set_tag)
        bottom_bar.addWidget(self.tag_btn)

        bottom_bar.addStretch()
        self.status_label = QLabel("加载中...")
        self.status_label.setStyleSheet("color: #666; padding: 8px;")
        bottom_bar.addWidget(self.status_label)
        layout.addLayout(bottom_bar)

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
        self._sessions = sessions
        self._populate_table(sessions)

    def _populate_table(self, sessions: list) -> None:
        self.table.setRowCount(0)

        if not sessions:
            self.status_label.setText("暂无会话数据（需要先发起 API 请求）")
            return

        for session in sessions:
            row = self.table.rowCount()
            self.table.insertRow(row)

            bookmarked = session.get("bookmarked", 0)
            tags = session.get("tags", "") or ""
            session_id = session.get("session_id", "")
            request_count = str(session.get("request_count", 0))
            total_tokens = f"{session.get('total_tokens', 0):,}"
            total_cost = f"${session.get('total_cost', 0):.4f}"
            saved_tokens = f"{session.get('saved_tokens', 0):,}"
            providers = session.get("providers", "")
            models = session.get("models", "")
            last_request = session.get("last_request", "")[:19]

            star_item = QTableWidgetItem("⭐" if bookmarked else "")
            star_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            star_item.setData(Qt.ItemDataRole.UserRole, session_id)
            self.table.setItem(row, 0, star_item)

            id_item = QTableWidgetItem(session_id[:16] + "..." if len(session_id) > 16 else session_id)
            id_item.setData(Qt.ItemDataRole.UserRole, session_id)
            self.table.setItem(row, 1, id_item)
            self.table.setItem(row, 2, QTableWidgetItem(request_count))
            self.table.setItem(row, 3, QTableWidgetItem(total_tokens))
            self.table.setItem(row, 4, QTableWidgetItem(total_cost))
            self.table.setItem(row, 5, QTableWidgetItem(saved_tokens))
            self.table.setItem(row, 6, QTableWidgetItem(providers))
            self.table.setItem(row, 7, QTableWidgetItem(models))

            tag_item = QTableWidgetItem(tags)
            tag_item.setData(Qt.ItemDataRole.UserRole, session_id)
            self.table.setItem(row, 8, tag_item)

            self.table.setItem(row, 9, QTableWidgetItem(last_request))

        self.status_label.setText(f"共 {len(sessions)} 个会话")

    def _filter_rows(self) -> None:
        keyword = self.search_edit.text().lower()
        bookmark_only = self.bookmark_only.isChecked()

        for row in range(self.table.rowCount()):
            id_item = self.table.item(row, 1)
            tag_item = self.table.item(row, 8)
            star_item = self.table.item(row, 0)

            session_id = id_item.data(Qt.ItemDataRole.UserRole) if id_item else ""
            tags = tag_item.text().lower() if tag_item else ""
            is_bookmarked = star_item.text() == "⭐" if star_item else False

            match_keyword = not keyword or keyword in (session_id or "").lower() or keyword in tags
            match_bookmark = not bookmark_only or is_bookmarked

            self.table.setRowHidden(row, not (match_keyword and match_bookmark))

    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        if col == 8:
            self._edit_tag_at_row(row)

    def _get_selected_session_id(self) -> str | None:
        rows = {item.row() for item in self.table.selectedItems()}
        if not rows:
            QMessageBox.warning(self, "提示", "请先选择一行")
            return None
        row = next(iter(rows))
        id_item = self.table.item(row, 1)
        return id_item.data(Qt.ItemDataRole.UserRole) if id_item else None

    def _toggle_bookmark(self) -> None:
        session_id = self._get_selected_session_id()
        if not session_id:
            return
        try:
            base = f"http://{settings.gateway_host}:{settings.gateway_port}"
            resp = httpx.post(f"{base}/v1/sessions/{session_id}/bookmark", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                self.refresh()
                self.status_label.setText(
                    f"会话 {session_id[:12]}... {'已书签' if data.get('bookmarked') else '已取消书签'}"
                )
            else:
                QMessageBox.warning(self, "错误", f"操作失败: HTTP {resp.status_code}")
        except httpx.HTTPError as e:
            QMessageBox.warning(self, "错误", str(e))

    def _set_tag(self) -> None:
        self._edit_tag_at_row(None)

    def _edit_tag_at_row(self, row: int | None) -> None:
        if row is None:
            rows = {item.row() for item in self.table.selectedItems()}
            if not rows:
                QMessageBox.warning(self, "提示", "请先选择一行")
                return
            row = next(iter(rows))

        id_item = self.table.item(row, 1)
        session_id = id_item.data(Qt.ItemDataRole.UserRole) if id_item else ""
        if not session_id:
            return

        tag_item = self.table.item(row, 8)
        current_tags = tag_item.text() if tag_item else ""

        from PySide6.QtWidgets import QInputDialog

        tags, ok = QInputDialog.getText(
            self, "设置标签", f"会话 {session_id[:12]}... 的标签:", text=current_tags
        )
        if not ok:
            return

        try:
            base = f"http://{settings.gateway_host}:{settings.gateway_port}"
            resp = httpx.post(
                f"{base}/v1/sessions/{session_id}/tags",
                json={"tags": tags},
                timeout=5.0,
            )
            if resp.status_code == 200:
                self.refresh()
            else:
                QMessageBox.warning(self, "错误", f"设置失败: HTTP {resp.status_code}")
        except httpx.HTTPError as e:
            QMessageBox.warning(self, "错误", str(e))

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

        data = []
        for row in sorted(rows):
            id_item = self.table.item(row, 1)
            session_id = id_item.data(Qt.ItemDataRole.UserRole) if id_item else ""
            row_data = {
                "session_id": session_id,
                "request_count": self.table.item(row, 2).text() if self.table.item(row, 2) else "",
                "total_tokens": self.table.item(row, 3).text() if self.table.item(row, 3) else "",
                "cost": self.table.item(row, 4).text() if self.table.item(row, 4) else "",
                "saved_tokens": self.table.item(row, 5).text() if self.table.item(row, 5) else "",
                "providers": self.table.item(row, 6).text() if self.table.item(row, 6) else "",
                "models": self.table.item(row, 7).text() if self.table.item(row, 7) else "",
                "tags": self.table.item(row, 8).text() if self.table.item(row, 8) else "",
            }
            data.append(row_data)

        try:
            if path.endswith(".md"):
                with open(path, "w", encoding="utf-8") as f:
                    f.write("# 会话导出\n\n")
                    for d in data:
                        f.write(f"## 会话 `{d.get('session_id', '')}`\n")
                        if d.get("tags"):
                            f.write(f"**标签**: {d['tags']}\n\n")
                        f.writelines(f"- **{k}**: {v}\n" for k, v in d.items() if k != "tags")
                        f.write("\n")
            else:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "成功", f"已导出 {len(data)} 条记录到 {path}")
        except OSError as e:
            QMessageBox.critical(self, "错误", str(e))
