"""
AIOptimizer 应用程序主入口
====================================

本文件是 AIOptimizer 桌面应用程序的启动入口，负责：
1. 启动后台 FastAPI 网关服务（在独立线程中运行）
2. 启动 PySide6 GUI 主窗口
3. 管理应用程序生命周期和资源清理

架构说明：
- 网关运行在后台守护线程中，提供 OpenAI 兼容的 API 代理服务
- GUI 运行在主线程中，提供用户交互界面
- 两者通过 HTTP 通信（GUI 调用网关的 /v1/* API）
"""

import sys
import threading
import time  # 用于等待网关启动

import uvicorn  # ASGI 服务器，用于运行 FastAPI 应用
from PySide6.QtWidgets import QApplication  # Qt 应用程序框架

from app.core.config import settings  # 全局配置对象
from app.ui.main_window import MainWindow  # 主窗口类


def run_gateway():
    """
    在后台线程中运行 FastAPI 网关服务
    
    使用 uvicorn 作为 ASGI 服务器启动 FastAPI 应用。
    网关监听配置指定的主机和端口，提供 OpenAI 兼容的 API 接口。
    
    配置参数：
    - host: 监听地址（默认 127.0.0.1）
    - port: 监听端口（默认 8000）
    - log_level: 日志级别，设为 warning 减少输出
    - access_log: 禁用访问日志以减少噪音
    """
    uvicorn.run(
        "app.core.gateway:app",  # FastAPI 应用导入路径
        host=settings.gateway_host,  # 从配置读取监听地址
        port=settings.gateway_port,  # 从配置读取监听端口
        log_level="warning",  # 只记录警告及以上级别日志
        access_log=False,  # 禁用 HTTP 访问日志
    )


def main():
    """
    应用程序主函数
    
    启动流程：
    1. 创建并启动网关后台线程
    2. 等待网关就绪（预留启动时间）
    3. 初始化 Qt 应用程序和主窗口
    4. 注册退出时的清理回调
    5. 进入 Qt 事件循环
    """
    # ===== 1. 启动网关后台线程 =====
    # daemon=True 表示主线程退出时该线程会被强制终止
    gateway_thread = threading.Thread(target=run_gateway, daemon=True)
    gateway_thread.start()

    # ===== 2. 等待网关启动完成 =====
    # 预留 1.5 秒让 uvicorn 完成启动和绑定端口
    # 注意：生产环境可改为轮询 /health 接口确认就绪
    time.sleep(1.5)

    # ===== 3. 初始化 Qt 应用程序 =====
    app = QApplication(sys.argv)
    app.setApplicationName("AIOptimizer")  # 应用名称（显示在任务栏等处）
    app.setOrganizationName("ph6977")  # 组织名称（用于设置存储路径）

    # 创建并显示主窗口
    window = MainWindow()
    window.show()

    # ===== 4. 注册退出清理回调 =====
    def on_exit():
        """
        应用退出时的清理工作：
        - 关闭所有 Provider 的 HTTP 连接池
        - 释放网络资源，避免连接泄漏
        """
        import asyncio

        from app.providers import ProviderFactory

        # 运行异步关闭方法，等待所有连接优雅关闭
        asyncio.run(ProviderFactory.close_all())

    # 连接 Qt 的 aboutToQuit 信号，确保退出时执行清理
    app.aboutToQuit.connect(on_exit)

    # ===== 5. 进入 Qt 主事件循环 =====
    # 这是阻塞调用，直到用户关闭窗口或调用 app.quit()
    sys.exit(app.exec())


if __name__ == "__main__":
    # 程序入口点：只有直接运行此文件时才执行 main()
    # 被导入时不会自动执行
    main()
