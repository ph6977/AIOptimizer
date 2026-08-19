"""设置页面"""

from typing import Any, cast

import httpx
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.config import ProviderConfig, settings


class ProviderRowData:
    def __init__(
        self, name: str, display_name: str, api_key: str, base_url: str, models: str
    ) -> None:
        self.name = name
        self.display_name = display_name
        self.api_key = api_key
        self.base_url = base_url
        self.models = models
        self.enabled = True


class SettingsPage(QWidget):
    config_saved = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.provider_rows: list[int] = []
        self._init_ui()
        self.load_config()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        self.form_layout = QVBoxLayout(content)
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        # 网关设置
        gateway_group = QGroupBox("网关设置")
        gateway_form = QFormLayout(gateway_group)
        self.host_edit = QLineEdit()
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        gateway_form.addRow("监听地址:", self.host_edit)
        gateway_form.addRow("监听端口:", self.port_spin)
        self.form_layout.addWidget(gateway_group)

        # 压缩设置
        compress_group = QGroupBox("上下文压缩")
        compress_form = QFormLayout(compress_group)
        self.compress_enabled = QCheckBox("启用压缩")
        self.aggressiveness = QDoubleSpinBox()
        self.aggressiveness.setRange(0.0, 1.0)
        self.aggressiveness.setSingleStep(0.1)
        self.aggressiveness.setDecimals(1)
        self.max_context = QSpinBox()
        self.max_context.setRange(1024, 100000)
        self.max_context.setSingleStep(1024)
        self.target_context = QSpinBox()
        self.target_context.setRange(512, 50000)
        self.target_context.setSingleStep(512)
        compress_form.addRow(self.compress_enabled)
        compress_form.addRow("压缩激进度 (0-1):", self.aggressiveness)
        compress_form.addRow("最大上下文:", self.max_context)
        compress_form.addRow("目标上下文:", self.target_context)
        self.form_layout.addWidget(compress_group)

        # 路由设置
        route_group = QGroupBox("智能路由")
        route_form = QFormLayout(route_group)
        self.route_enabled = QCheckBox("启用路由")
        self.quality_cost = QDoubleSpinBox()
        self.quality_cost.setRange(0.0, 1.0)
        self.quality_cost.setSingleStep(0.1)
        self.quality_cost.setDecimals(1)
        route_form.addRow(self.route_enabled)
        route_form.addRow("质量/成本偏好 (0=省钱, 1=质量):", self.quality_cost)
        self.form_layout.addWidget(route_group)

        # 提示词增强
        prompt_group = QGroupBox("提示词增强")
        prompt_form = QFormLayout(prompt_group)
        self.prompt_enabled = QCheckBox("启用提示词增强")
        prompt_form.addRow(self.prompt_enabled)
        self.form_layout.addWidget(prompt_group)

        # Provider 管理
        provider_group = QGroupBox("Provider 管理 (API Keys)")
        provider_layout = QVBoxLayout(provider_group)

        # 表格
        self.provider_table = QTableWidget()
        self.provider_table.setColumnCount(6)
        self.provider_table.setHorizontalHeaderLabels(
            ["名称", "显示名", "API Key", "Base URL", "模型(逗号分隔)", "启用"]
        )
        self.provider_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        provider_layout.addWidget(self.provider_table)

        # 按钮行
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ 添加 Provider")
        add_btn.clicked.connect(self._add_provider_row)
        remove_btn = QPushButton("🗑️ 删除选中")
        remove_btn.clicked.connect(self._remove_provider_row)
        test_btn = QPushButton("🔍 测试连接")
        test_btn.clicked.connect(self._test_provider)
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(remove_btn)
        btn_layout.addWidget(test_btn)
        btn_layout.addStretch()
        provider_layout.addLayout(btn_layout)

        self.form_layout.addWidget(provider_group)

        # 底部保存按钮
        save_layout = QHBoxLayout()
        save_layout.addStretch()
        save_btn = QPushButton("💾 保存配置 (运行时生效)")
        save_btn.clicked.connect(self.save_config)
        save_btn.setStyleSheet("font-size: 14px; padding: 8px 24px;")
        save_layout.addWidget(save_btn)
        self.form_layout.addLayout(save_layout)

        self.form_layout.addStretch()

    def load_config(self) -> None:
        self.host_edit.setText(settings.gateway_host)
        self.port_spin.setValue(settings.gateway_port)
        self.compress_enabled.setChecked(settings.compression_enabled)
        self.aggressiveness.setValue(settings.compression_aggressiveness)
        self.max_context.setValue(settings.max_context_tokens)
        self.target_context.setValue(settings.target_context_tokens)
        self.route_enabled.setChecked(settings.routing_enabled)
        self.quality_cost.setValue(settings.quality_vs_cost)
        self.prompt_enabled.setChecked(settings.prompt_enhancement_enabled)

        # 加载 Provider
        providers = settings.get_providers()
        for p in providers:
            self._add_provider_row(
                ProviderRowData(
                    name=p.name,
                    display_name=p.display_name,
                    api_key=p.api_key,
                    base_url=p.base_url,
                    models=",".join(p.models),
                )
            )

        if not providers:
            # 默认添加几个常见的
            defaults = [
                (
                    "openai",
                    "OpenAI",
                    "",
                    "https://api.openai.com/v1",
                    "gpt-4o,gpt-4o-mini",
                ),
                (
                    "deepseek",
                    "DeepSeek",
                    "",
                    "https://api.deepseek.com",
                    "deepseek-chat,deepseek-reasoner",
                ),
                (
                    "glm",
                    "Zhipu GLM",
                    "",
                    "https://open.bigmodel.cn/api/paas/v4",
                    "glm-4,glm-4v",
                ),
                (
                    "qwen",
                    "Alibaba Qwen",
                    "",
                    "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "qwen-max,qwen-plus,qwen-turbo",
                ),
                (
                    "kimi",
                    "Moonshot Kimi",
                    "",
                    "https://api.moonshot.cn/v1",
                    "moonshot-v1-8k,moonshot-v1-32k,moonshot-v1-128k",
                ),
                (
                    "ollama",
                    "Ollama (本地)",
                    "",
                    "http://localhost:11434/v1",
                    "llama3.1,qwen2.5,deepseek-r1",
                ),
            ]
            for d in defaults:
                self._add_provider_row(ProviderRowData(*d))

    def _add_provider_row(self, data: ProviderRowData | None = None) -> None:
        row = self.provider_table.rowCount()
        self.provider_table.insertRow(row)

        cols = ["name", "display_name", "api_key", "base_url", "models", "enabled"]
        for col, key in enumerate(cols):
            if key == "enabled":
                chk = QCheckBox()
                chk.setChecked(data.enabled if data else True)
                self.provider_table.setCellWidget(row, col, chk)
            elif key == "api_key":
                edit = QLineEdit()
                edit.setEchoMode(QLineEdit.EchoMode.Password)
                edit.setText(data.api_key if data else "")
                edit.setPlaceholderText("点击填入 Key")
                self.provider_table.setCellWidget(row, col, edit)
            else:
                item = QTableWidgetItem(getattr(data, key, "") if data else "")
                self.provider_table.setItem(row, col, item)

        self.provider_rows.append(row)

    def _remove_provider_row(self) -> None:
        rows = {item.row() for item in self.provider_table.selectedItems()}
        for row in sorted(rows, reverse=True):
            self.provider_table.removeRow(row)
            if row in self.provider_rows:
                self.provider_rows.remove(row)

    def _test_provider(self) -> None:
        row = self.provider_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选择一行")
            return

        name_item = self.provider_table.item(row, 0)
        key_widget = self.provider_table.cellWidget(row, 2)
        url_item = self.provider_table.item(row, 3)

        if not name_item or not key_widget:
            return

        api_key = cast(QLineEdit, key_widget).text()
        base_url = url_item.text() if url_item else ""

        if not api_key:
            QMessageBox.warning(self, "提示", "请先填入 API Key")
            return

        # 简单测试：发起 /models 请求
        import asyncio

        async def test() -> tuple[bool, str]:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    headers = {"Authorization": f"Bearer {api_key}"}
                    url = (base_url or "https://api.openai.com/v1").rstrip(
                        "/"
                    ) + "/models"
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        return (
                            True,
                            f"连接成功，发现 {len(resp.json().get('data', []))} 个模型",
                        )
                    else:
                        return False, f"HTTP {resp.status_code}: {resp.text}"
            except httpx.HTTPError as e:
                return False, str(e)

        # 简化：同步运行
        try:
            loop = asyncio.new_event_loop()
            ok, msg = loop.run_until_complete(test())
            loop.close()
            if ok:
                QMessageBox.information(self, "测试结果", f"✅ {msg}")
            else:
                QMessageBox.warning(self, "测试结果", f"❌ {msg}")
        except (OSError, RuntimeError) as e:
            QMessageBox.critical(self, "错误", str(e))

    def save_config(self) -> None:
        # 更新基础设置
        settings.gateway_host = self.host_edit.text() or "127.0.0.1"
        settings.gateway_port = self.port_spin.value()
        settings.compression_enabled = self.compress_enabled.isChecked()
        settings.compression_aggressiveness = self.aggressiveness.value()
        settings.max_context_tokens = self.max_context.value()
        settings.target_context_tokens = self.target_context.value()
        settings.routing_enabled = self.route_enabled.isChecked()
        settings.quality_vs_cost = self.quality_cost.value()
        settings.prompt_enhancement_enabled = self.prompt_enabled.isChecked()

        # 收集 Provider
        providers_list: list[dict[str, Any]] = []
        for row in range(self.provider_table.rowCount()):
            name_item = self.provider_table.item(row, 0)
            display_item = self.provider_table.item(row, 1)
            key_widget = self.provider_table.cellWidget(row, 2)
            url_item = self.provider_table.item(row, 3)
            models_item = self.provider_table.item(row, 4)
            enabled_widget = self.provider_table.cellWidget(row, 5)

            if not name_item or not name_item.text().strip():
                continue

            providers_list.append(
                {
                    "name": name_item.text().strip(),
                    "display_name": (
                        display_item.text().strip()
                        if display_item
                        else name_item.text().strip()
                    ),
                    "api_key": cast(QLineEdit, key_widget).text() if key_widget else "",
                    "base_url": url_item.text().strip() if url_item else "",
                    "models": (
                        [m.strip() for m in models_item.text().split(",")]
                        if models_item and models_item.text()
                        else []
                    ),
                    "enabled": (
                        cast(QCheckBox, enabled_widget).isChecked()
                        if enabled_widget
                        else True
                    ),
                    "priority": 0,
                }
            )

        settings.set_providers([ProviderConfig(**p) for p in providers_list])
        self.config_saved.emit()
        QMessageBox.information(self, "成功", "配置已保存（运行时生效，重启后丢失）")
