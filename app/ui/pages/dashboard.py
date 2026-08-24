"""用量面板页面"""

from typing import Any

import httpx
from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QLineSeries,
    QPieSeries,
    QValueAxis,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.config import settings


class StatsWorker(QThread):
    """后台获取统计数据"""

    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, days: int) -> None:
        super().__init__()
        self.days = days

    def run(self) -> None:
        try:
            url = (
                f"http://{settings.gateway_host}:{settings.gateway_port}/v1/usage/stats"
            )
            resp = httpx.get(url, params={"days": self.days}, timeout=5.0)
            if resp.status_code == 200:
                self.finished.emit(resp.json())
            else:
                self.error.emit(f"HTTP {resp.status_code}")
        except httpx.HTTPError as e:
            self.error.emit(str(e))


class DashboardPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.worker: StatsWorker | None = None
        self.cards: dict[str, QWidget] = {}
        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
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

        # 图表区域 - 第一行：趋势 + Provider 分布
        charts_layout_row1 = QHBoxLayout()

        # 每日趋势图
        self.daily_chart = self._create_line_chart("每日请求趋势")
        charts_layout_row1.addWidget(self.daily_chart)

        # Provider 分布饼图
        self.provider_chart = self._create_pie_chart("Provider 分布")
        charts_layout_row1.addWidget(self.provider_chart)

        layout.addLayout(charts_layout_row1, 1)

        # 图表区域 - 第二行：成本趋势 + 压缩节省
        charts_layout_row2 = QHBoxLayout()

        # 成本趋势图
        self.cost_chart = self._create_line_chart("每日成本趋势")
        charts_layout_row2.addWidget(self.cost_chart)

        # 压缩节省图
        self.savings_chart = self._create_bar_chart("压缩节省 Token")
        charts_layout_row2.addWidget(self.savings_chart)

        layout.addLayout(charts_layout_row2, 1)

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

    def _create_pie_chart(self, title: str) -> QChartView:
        chart = QChart()
        chart.setTitle(title)
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
        view = QChartView(chart)
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        view.setMinimumHeight(250)
        return view

    def refresh(self) -> None:
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

    def _reset_refresh_btn(self) -> None:
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("🔄 刷新")

    def _set_card_value(self, key: str, text: str) -> None:
        label = self.cards[key].findChild(QLabel, "value")
        if label is not None:
            label.setText(text)

    def _on_stats_ready(self, data: dict[str, Any]) -> None:
        # 更新概览卡片
        summary = data.get("summary", {})
        requests = summary.get("requests") or 0
        total_tokens = summary.get("total_tokens") or 0
        total_cost = summary.get("total_cost") or 0.0
        saved_tokens = summary.get("saved_tokens") or 0
        self._set_card_value("requests", str(requests))
        self._set_card_value("total_tokens", f"{total_tokens:,}")
        self._set_card_value("total_cost", f"{total_cost:.4f}")
        self._set_card_value("saved_tokens", f"{saved_tokens:,}")

        total = total_tokens
        saved = saved_tokens
        ratio = (saved / total * 100) if total > 0 else 0
        self._set_card_value("saved_ratio", f"{ratio:.1f}%")

        # 更新每日趋势图
        self._update_line_chart(data.get("daily", []))

        # 更新 Provider 分布
        self._update_bar_chart(data.get("by_provider", []))
        self._update_pie_chart(data.get("by_provider", []))

        # 更新成本趋势图
        self._update_cost_chart(data.get("daily", []))

        # 更新压缩节省图
        self._update_savings_chart(data.get("daily", []))

        # 更新模型分布
        by_model = data.get("by_model", [])
        if by_model:
            lines = [
                f"{m['model']}: {m['requests']}次, {m['tokens']:,} tokens, ${m['cost']:.4f}"
                for m in by_model[:10]
            ]
            self.model_label.setText("\n".join(lines))
        else:
            self.model_label.setText("暂无数据")

    def _on_stats_error(self, err: str) -> None:
        QMessageBox.warning(self, "统计失败", f"获取统计失败: {err}")

    def _update_line_chart(self, daily: list[dict[str, Any]]) -> None:
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

    def _update_bar_chart(self, by_provider: list[dict[str, Any]]) -> None:
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

    def _update_pie_chart(self, by_provider: list[dict[str, Any]]) -> None:
        chart = self.provider_chart.chart()
        chart.removeAllSeries()

        series = QPieSeries()
        for p in by_provider:
            slice_ = series.append(p.get("provider", ""), p.get("requests", 0))
            slice_.setLabel(f"{p.get('provider', '')}: {p.get('requests', 0)}")
            slice_.setLabelVisible(True)

        chart.addSeries(series)

    def _update_cost_chart(self, daily: list[dict[str, Any]]) -> None:
        chart = self.cost_chart.chart()
        chart.removeAllSeries()

        series = QLineSeries()
        series.setName("成本 ($)")
        for i, d in enumerate(daily):
            series.append(i, d.get("cost", 0.0))

        chart.addSeries(series)
        axis_x = QBarCategoryAxis()
        axis_x.append([d.get("day", "") for d in daily])
        axis_y = QValueAxis()
        axis_y.setTitleText("成本 ($)")
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)

    def _update_savings_chart(self, daily: list[dict[str, Any]]) -> None:
        chart = self.savings_chart.chart()
        chart.removeAllSeries()

        bar_set = QBarSet("节省 Token")
        categories = []
        for d in daily:
            bar_set.append(d.get("saved_tokens", 0))
            categories.append(d.get("day", ""))

        series = QBarSeries()
        series.append(bar_set)
        chart.addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append(categories)
        axis_y = QValueAxis()
        axis_y.setTitleText("节省 Token")
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)
