"""压缩透明页：展示每条压缩决策的详情，可展开/恢复"""
import httpx
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QSplitter, QTextEdit,
    QGroupBox, QComboBox, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont

from app.core.config import settings


class TransparencyWorker(QThread):
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, limit: int = 50):
        super().__init__()
        self.limit = limit

    def run(self):
        try:
            url = f"http://{settings.gateway_host}:{settings.gateway_port}/v1/usage/stats"
            resp = httpx.get(url, params={"days": 1}, timeout=10.0)
            if resp.status_code == 200:
                # 简化：返回空，实际需要专门的压缩详情 API
                self.finished.emit([])
            else:
                self.error.emit(f"HTTP {resp.status_code}")
        except Exception as e:
            self.error.emit(str(e))


class TransparencyPage(QWidget):
    def __init__(self):
        super().__init__()
        self._init_ui()

    def _init_ui(self):
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
        self.tree.setHeaderLabels(["消息", "动作", "原因", "Token", "节省"])
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(1, 80)
        self.tree.setColumnWidth(2, 150)
        self.tree.setColumnWidth(3, 80)
        self.tree.setColumnWidth(4, 80)
        self.tree.itemClicked.connect(self._on_item_clicked)
        left_layout.addWidget(self.tree)

        # 统计摘要
        self.summary_label = QLabel("总计: 0 条, 保留: 0, 摘要: 0, 丢弃: 0, 节省: 0 tokens")
        self.summary_label.setStyleSheet("color: #666; padding: 8px; background: #f5f5f5; border-radius: 4px;")
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

        self.current_items = []

    def refresh(self):
        self.worker = TransparencyWorker()
        self.worker.finished.connect(self._on_data_ready)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_data_ready(self, data: list):
        # 这里简化：生成演示数据
        self._load_demo_data()

    def _on_error(self, err: str):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "错误", f"获取失败: {err}")

    def _load_demo_data(self):
        """加载演示数据（实际应从 API 获取压缩详情）"""
        self.tree.clear()
        self.current_items = []

        demo_decisions = [
            ("system", "keep", "系统提示词", 156, 0, "You are a helpful assistant..."),
            ("user", "keep", "包含代码关键词", 89, 0, "请帮我写一个 Python 函数计算斐波那契数列"),
            ("assistant", "keep", "包含代码", 234, 0, "def fib(n):\n    if n <= 1: return n\n    return fib(n-1) + fib(n-2)"),
            ("user", "summarize", "长文本非关键", 567, 423, "这是一段很长的对话内容，主要讨论了项目架构、技术选型、团队分工等非核心技术细节..."),
            ("assistant", "summarize", "长文本非关键", 445, 312, "建议采用微服务架构，使用 Docker 容器化部署，CI/CD 流水线..."),
            ("user", "drop", "纯寒暄", 12, 12, "好的，谢谢！"),
            ("assistant", "drop", "纯确认", 8, 8, "不客气！"),
        ]

        kept = summarized = dropped = saved_total = 0

        for role, action, reason, tokens, saved, content in demo_decisions:
            item = QTreeWidgetItem([
                f"[{role}] {content[:60]}{'...' if len(content) > 60 else ''}",
                action.upper(),
                reason,
                str(tokens),
                f"+{saved}" if saved else "0",
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, {
                "role": role,
                "action": action,
                "reason": reason,
                "tokens": tokens,
                "saved": saved,
                "original": content,
                "summary": f"[摘要] {content[:200]}..." if action == "summarize" else None,
            })
            self.tree.addTopLevelItem(item)
            self.current_items.append(item)

            if action == "keep":
                kept += 1
            elif action == "summarize":
                summarized += 1
            elif action == "drop":
                dropped += 1
            saved_total += saved

        self.summary_label.setText(
            f"总计: {len(demo_decisions)} 条, 保留: {kept}, 摘要: {summarized}, 丢弃: {dropped}, 节省: {saved_total} tokens"
        )

        # 颜色标记
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            action = item.text(1)
            if action == "KEEP":
                item.setBackground(1, Qt.GlobalColor.green)
            elif action == "SUMMARIZE":
                item.setBackground(1, Qt.GlobalColor.yellow)
            elif action == "DROP":
                item.setBackground(1, Qt.GlobalColor.red)

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        self.current_data = data
        self.restore_btn.setEnabled(data["action"] == "summarize")

        detail = f"""角色: {data['role']}
动作: {data['action'].upper()}
原因: {data['reason']}
Token: {data['tokens']}
节省: {data['saved']}

{'='*50}
原文内容:
{data['original']}
"""
        if data.get("summary"):
            detail += f"\n{'='*50}\n摘要版本:\n{data['summary']}"

        self.detail_text.setPlainText(detail)

    def _restore_original(self):
        if hasattr(self, 'current_data') and self.current_data.get("summary"):
            self.detail_text.setPlainText(self.current_data["original"])
            self.restore_btn.setEnabled(False)

    def _copy_detail(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.detail_text.toPlainText())
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "已复制", "详情已复制到剪贴板")

    def _clear(self):
        self.tree.clear()
        self.detail_text.clear()
        self.summary_label.setText("已清空")