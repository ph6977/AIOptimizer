"""压缩透明页：展示每条压缩决策的详情，可展开/恢复"""

from typing import Any

import httpx
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.config import settings


class TransparencyWorker(QThread):
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, limit: int = 100) -> None:
        super().__init__()
        self.limit = limit

    def run(self) -> None:
        try:
            url = f"http://{settings.gateway_host}:{settings.gateway_port}/v1/compression/details"
            resp = httpx.get(url, params={"limit": self.limit}, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                self.finished.emit(data.get("details", []))
            else:
                self.error.emit(f"HTTP {resp.status_code}")
        except httpx.HTTPError as e:
            self.error.emit(str(e))


class TransparencyPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.current_items: list[QTreeWidgetItem] = []
        self.current_data: Any = None
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        # 顶部控制栏
        control = QHBoxLayout()
        control.addWidget(QLabel("压缩透明化 - 查看每条消息的压缩决策"))

        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.clicked.connect(self.refresh)
        control.addWidget(self.refresh_btn)

        clear_btn = QPushButton("🗑️ 清空显示")
        clear_btn.clicked.connect(self._clear)
        control.addWidget(clear_btn)
        control.addStretch()
        layout.addLayout(control)

        # 主分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧：决策列表树
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["消息", "动作", "类型", "原因", "Token", "节省"])
        self.tree.setColumnWidth(0, 280)
        self.tree.setColumnWidth(1, 70)
        self.tree.setColumnWidth(2, 80)
        self.tree.setColumnWidth(3, 140)
        self.tree.setColumnWidth(4, 70)
        self.tree.setColumnWidth(5, 70)
        self.tree.itemClicked.connect(self._on_item_clicked)
        left_layout.addWidget(self.tree)

        # 统计摘要
        self.summary_label = QLabel(
            "总计: 0 条, 保留: 0, 摘要: 0, 丢弃: 0, 节省: 0 tokens"
        )
        self.summary_label.setStyleSheet(
            "color: #666; padding: 8px; background: #f5f5f5; border-radius: 4px;"
        )
        left_layout.addWidget(self.summary_label)

        splitter.addWidget(left_widget)

        # 右侧：详情面板
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        detail_group = QGroupBox("原文 / 摘要详情")
        detail_layout = QVBoxLayout(detail_group)

        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setFont(QFont("Consolas", 10))
        detail_layout.addWidget(self.detail_text)

        # 操作按钮
        btn_layout = QHBoxLayout()
        self.restore_btn = QPushButton("↩️ 恢复原文")
        self.restore_btn.setEnabled(False)
        self.restore_btn.clicked.connect(self._restore_original)
        btn_layout.addWidget(self.restore_btn)

        self.copy_btn = QPushButton("📋 复制")
        self.copy_btn.clicked.connect(self._copy_detail)
        btn_layout.addWidget(self.copy_btn)
        btn_layout.addStretch()
        detail_layout.addLayout(btn_layout)

        right_layout.addWidget(detail_group)
        splitter.addWidget(right_widget)

        splitter.setSizes([500, 500])
        layout.addWidget(splitter, 1)

        # 底部说明
        hint = QLabel(
            "💡 点击左侧列表项查看详情。<b>保留</b>=完整保留，<b>摘要</b>=已压缩（可恢复），<b>丢弃</b>=已移除。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; padding: 8px;")
        layout.addWidget(hint)

    def refresh(self) -> None:
        self.worker = TransparencyWorker()
        self.worker.finished.connect(self._on_data_ready)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_data_ready(self, data: list[Any]) -> None:
        self.tree.clear()
        self.current_items = []

        if not data:
            self.summary_label.setText("暂无压缩决策数据（需要先发起带压缩的请求）")
            return

        kept = summarized = dropped = saved_total = 0

        # 信息类型颜色映射
        INFO_COLORS: dict[str, str] = {
            "code": "#3498db",
            "reasoning": "#9b59b6",
            "context": "#2ecc71",
            "dialog": "#f39c12",
            "other": "#95a5a6",
        }

        for record in data:
            role = record.get("role", "unknown")
            action = record.get("action", "keep")
            reason = record.get("reason", "")
            info_type = record.get("info_type", "other")
            original_tokens = record.get("original_tokens", 0)
            saved_tokens = record.get("saved_tokens", 0)
            original_content = record.get("original_content", "")
            summary_content = record.get("summary_content", "")

            type_tag = f"[{info_type}]"
            display_text = f"{type_tag} [{role}] {original_content[:50]}{'...' if len(original_content) > 50 else ''}"

            item = QTreeWidgetItem(
                [
                    display_text,
                    action.upper(),
                    info_type,
                    reason,
                    str(original_tokens),
                    f"+{saved_tokens}" if saved_tokens else "0",
                ]
            )
            item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                {
                    "role": role,
                    "action": action,
                    "reason": reason,
                    "info_type": info_type,
                    "original_tokens": original_tokens,
                    "saved_tokens": saved_tokens,
                    "original": original_content,
                    "summary": summary_content,
                },
            )
            self.tree.addTopLevelItem(item)
            self.current_items.append(item)

            if action == "keep":
                kept += 1
            elif action == "summarize":
                summarized += 1
            elif action == "drop":
                dropped += 1
            saved_total += saved_tokens

        self.summary_label.setText(
            f"总计: {len(data)} 条, 保留: {kept}, 摘要: {summarized}, 丢弃: {dropped}, 节省: {saved_total} tokens"
        )

        # 颜色标记
        INFO_COLORS: dict[str, str] = {
            "code": "#3498db",
            "reasoning": "#9b59b6",
            "context": "#2ecc71",
            "dialog": "#f39c12",
            "other": "#95a5a6",
        }
        for i in range(self.tree.topLevelItemCount()):
            item_opt = self.tree.topLevelItem(i)
            if item_opt is None:
                continue
            item = item_opt
            action = item.text(1)
            info_type = item.text(2)
            if action == "KEEP":
                item.setBackground(1, Qt.GlobalColor.green)
            elif action == "SUMMARIZE":
                item.setBackground(1, Qt.GlobalColor.yellow)
            elif action == "DROP":
                item.setBackground(1, Qt.GlobalColor.red)
            # info_type 列颜色
            color = INFO_COLORS.get(info_type, "")
            if color:
                from PySide6.QtGui import QColor

                item.setBackground(2, QColor(color))
                item.setForeground(2, QColor("white"))

    def _on_error(self, err: str) -> None:
        QMessageBox.warning(self, "错误", f"获取失败: {err}")

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        self.current_data = data
        self.restore_btn.setEnabled(data["action"] == "summarize")

        detail = f"""角色: {data['role']}
动作: {data['action'].upper()}
类型: {data.get('info_type', 'other')}
原因: {data['reason']}
原始 Token: {data['original_tokens']}
节省 Token: {data['saved_tokens']}

{'='*50}
原文内容:
{data['original']}
"""
        if data.get("summary"):
            detail += f"\n{'='*50}\n摘要版本:\n{data['summary']}"

        self.detail_text.setPlainText(detail)

    def _restore_original(self) -> None:
        if hasattr(self, "current_data") and self.current_data.get("summary"):
            self.detail_text.setPlainText(self.current_data["original"])
            self.restore_btn.setEnabled(False)

    def _copy_detail(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.detail_text.toPlainText())
        QMessageBox.information(self, "已复制", "详情已复制到剪贴板")

    def _clear(self) -> None:
        self.tree.clear()
        self.detail_text.clear()
        self.summary_label.setText("已清空")
