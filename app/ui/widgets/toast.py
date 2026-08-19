"""Toast 通知管理器"""
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect
from PySide6.QtGui import QColor, QPainter, QBrush, QPen


class Toast(QWidget):
    def __init__(self, message: str, duration: int = 3000, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)

        self.label = QLabel(message)
        self.label.setStyleSheet("color: white; font-size: 13px;")
        self.label.setWordWrap(True)
        layout.addWidget(self.label)

        self.setFixedWidth(320)
        self.adjustSize()

        # 动画
        self.fade_in = QPropertyAnimation(self, b"windowOpacity")
        self.fade_in.setDuration(200)
        self.fade_in.setStartValue(0.0)
        self.fade_in.setEndValue(1.0)
        self.fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.fade_out = QPropertyAnimation(self, b"windowOpacity")
        self.fade_out.setDuration(300)
        self.fade_out.setStartValue(1.0)
        self.fade_out.setEndValue(0.0)
        self.fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self.fade_out.finished.connect(self.close)

        # 自动关闭定时器
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._start_fade_out)
        self.timer.start(duration)

    def _start_fade_out(self):
        self.fade_out.start()

    def showEvent(self, event):
        super().showEvent(event)
        self.fade_in.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setBrush(QBrush(QColor(40, 40, 40, 230)))
        painter.setPen(QPen(QColor(80, 80, 80), 1))
        painter.drawRoundedRect(rect, 8, 8)


class ToastManager:
    def __init__(self, parent=None):
        self.parent = parent
        self.toasts = []
        self.spacing = 10

    def show(self, message: str, duration: int = 3000):
        toast = Toast(message, duration, self.parent)
        self.toasts.append(toast)
        self._reposition()
        toast.show()

        # 移除时清理列表
        def on_finished():
            if toast in self.toasts:
                self.toasts.remove(toast)
            self._reposition()

        toast.fade_out.finished.connect(on_finished)

    def _reposition(self):
        if not self.parent:
            return

        # 右下角堆叠
        x = self.parent.width() - 340
        y = self.parent.height() - 40

        for toast in reversed(self.toasts):
            y -= toast.height() + self.spacing
            toast.move(x, y)