"""用量面板页面"""
import httpx
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QGridLayout, QGroupBox, QProgressBar, QPushButton
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QBarSet, QBarSeries, QValueAxis, QBarCategoryAxis
from PySide6.QtGui import QPainter

from app.core.config import settings


class StatsWorker(QThread):
    """后台获取统计数据"""
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, days: int):
        super().__init__()
        self.days = days

    def run(self):
        try:
            url = f"http://{settings.gateway_host}:{settings.gateway_port}/v1/usage/stats"
            resp = httpx.get(url, params={"days": self.days}, timeout=5.0)
            if resp.status_code == 200:
                self.finished.emit(resp.json())
            else:
                self.error.emit(f"HTTP {resp.status_code}")
        except Exception as e:
            self.error.emit(str(e))


class DashboardPage(QWidget):
    def __init__(self):
        super().__init__()
        self.worker = None
        self._init_ui()
        self.refresh()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 顶部控制栏
        control_bar = QHBoxLayout()
        control_bar.addWidget(QLabel("统计周期:"))
        self.period_combo = QComboBox()
        self.period_combo.addItems(["7 天", "30 天", "90 天"])
        self.period_combo.currentTextChanged.connect(self.refresh)
        control_bar.addWidget(self.period_combo)
        control_bar.addStretch()

        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.clicked.connect(self.refresh)
        control_bar.addWidget(self.refresh_btn)
        layout.addLayout(control_bar)

        # 概览卡片
        overview_group = QGroupBox("概览")
        overview_layout = QGridLayout(overview_group)
        self.cards = {}
        card_items = [
            ("总请求数", "requests", "0"),
            ("总 Token", "total_tokens", "0"),
            ("总成本 ($)", "total_cost", "0.00"),
            ("节省 Token", "saved_tokens", "0"),
            ("节省率", "saved_ratio", "0%"),
        ]
        for i, (label, key, default) in enumerate(card_items):
            card = self._create_card(label, default)
            self.cards[key] = card
            overview_layout.addWidget(card, i // 3, i % 3)
        layout.addWidget(overview_group)

        # 图表区域
        charts_layout = QHBoxLayout()

        # 每日趋势图
        self.daily_chart = self._create_line_chart("每日请求趋势")
        charts_layout.addWidget(self.daily_chart)

        # Provider 分布饼图（用柱状图代替）
        self.provider_chart = self._create_bar_chart("Provider 分布")
        charts_layout.addWidget(self.provider_chart)

        layout.addLayout(charts_layout, 1)

        # 底部模型分布表
        model_group = QGroupBox("模型分布")
        model_layout = QVBoxLayout(model_group)
        self.model_label = QLabel("暂无数据")
        self.model_label.setWordWrap(True)
        model_layout.addWidget(self.model_label)
        layout.addWidget(model_group)

    def _create_card(self, title: str, value: str) -> QWidget:
        card = QWidget()
        card.setStyleSheet("""
            QWidget { background: #f5f5f5; border-radius: 8px; padding: 12px; }
            QLabel { color: #333; }
        """)
        layout = QVBoxLayout(card)
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("font-size: 12px; color: #666;")
        lbl_value = QLabel(value)
        lbl_value.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")
        lbl_value.setObjectName("value")
        layout.addWidget(lbl_title)
        layout.addWidget(lbl_value)
        return card

    def _create_line_chart(self, title: str) -> QChartView:
        chart = QChart()
        chart.setTitle(title)
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        chart.legend().setVisible(False)
        view = QChartView(chart)
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        view.setMinimumHeight(250)
        return view

    def _create_bar_chart(self, title: str) -> QChartView:
        chart = QChart()
        chart.setTitle(title)
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
        view = QChartView(chart)
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        view.setMinimumHeight(250)
        return view

    def refresh(self):
        days = 7
        text = self.period_combo.currentText()
        if "30" in text:
            days = 30
        elif "90" in text:
            days = 90

        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("刷新中...")

        self.worker = StatsWorker(days)
        self.worker.finished.connect(self._on_stats_ready)
        self.worker.error.connect(self._on_stats_error)
        self.worker.finished.connect(lambda _: self._reset_refresh_btn())
        self.worker.start()

    def _reset_refresh_btn(self):
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("🔄 刷新")

    def _on_stats_ready(self, data: dict):
        # 更新概览卡片
        summary = data.get("summary", {})
        self.cards["requests"].findChild(QLabel, "value").setText(str(summary.get("requests", 0)))
        self.cards["total_tokens"].findChild(QLabel, "value").setText(f"{summary.get('total_tokens', 0):,}")
        self.cards["total_cost"].findChild(QLabel, "value").setText(f"{summary.get('total_cost', 0):.4f}")
        self.cards["saved_tokens"].findChild(QLabel, "value").setText(f"{summary.get('saved_tokens', 0):,}")

        total = summary.get("total_tokens", 0)
        saved = summary.get("saved_tokens", 0)
        ratio = (saved / total * 100) if total > 0 else 0
        self.cards["saved_ratio"].findChild(QLabel, "value").setText(f"{ratio:.1f}%")

        # 更新每日趋势图
        self._update_line_chart(data.get("daily", []))

        # 更新 Provider 分布
        self._update_bar_chart(data.get("by_provider", []))

        # 更新模型分布
        by_model = data.get("by_model", [])
        if by_model:
            lines = [f"{m['model']}: {m['requests']}次, {m['tokens']:,} tokens, ${m['cost']:.4f}" for m in by_model[:10]]
            self.model_label.setText("\n".join(lines))
        else:
            self.model_label.setText("暂无数据")

    def _on_stats_error(self, err: str):
        self.statusBar().showMessage(f"获取统计失败: {err}")

    def _update_line_chart(self, daily: list):
        chart = self.daily_chart.chart()
        chart.removeAllSeries()

        series = QLineSeries()
        series.setName("请求数")
        for i, d in enumerate(daily):
            series.append(i, d.get("requests", 0))

        chart.addSeries(series)
        axis_x = QBarCategoryAxis()
        axis_x.append([d.get("day", "") for d in daily])
        axis_y = QValueAxis()
        axis_y.setTitleText("请求数")
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)

    def _update_bar_chart(self, by_provider: list):
        chart = self.provider_chart.chart()
        chart.removeAllSeries()

        bar_set = QBarSet("请求数")
        categories = []
        for p in by_provider:
            bar_set.append(p.get("requests", 0))
            categories.append(p.get("provider", ""))

        series = QBarSeries()
        series.append(bar_set)
        chart.addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append(categories)
        axis_y = QValueAxis()
        axis_y.setTitleText("请求数")
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)