#!/usr/bin/env pwsh
<#
.SYNOPSIS
    AIOptimizer Windows 构建脚本
.DESCRIPTION
    使用 PyInstaller 打包单文件 exe，包含图标、版本信息、UPX 压缩
#>

param(
    [string]$Version = "0.1.0",
    [switch]$Clean,
    [switch]$NoUpx
)

$ErrorActionPreference = "Stop"

# 项目根目录
$RootDir = Split-Path $PSScriptRoot -Parent
$DistDir = Join-Path $RootDir "dist"
$BuildDir = Join-Path $RootDir "build"
$SpecFile = Join-Path $RootDir "AIOptimizer.spec"

# 清理
if ($Clean) {
    Write-Host "清理构建目录..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $DistDir -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $BuildDir -ErrorAction SilentlyContinue
    Remove-Item -Force $SpecFile -ErrorAction SilentlyContinue
}

# 检查依赖
Write-Host "检查依赖..." -ForegroundColor Cyan
$PyInstaller = Get-Command pyinstaller -ErrorAction SilentlyContinue
if (-not $PyInstaller) {
    Write-Host "安装 PyInstaller..." -ForegroundColor Yellow
    pip install pyinstaller
}

# 检查 UPX
$UseUpx = -not $NoUpx -and (Get-Command upx -ErrorAction SilentlyContinue)
if ($UseUpx) {
    Write-Host "发现 UPX，将启用压缩" -ForegroundColor Green
} else {
    Write-Host "未发现 UPX，跳过压缩" -ForegroundColor Yellow
    if (-not $NoUpx) {
        Write-Host "提示: 安装 UPX 可减小 30-50% 体积 (scoop install upx / choco install upx)" -ForegroundColor Yellow
    }
}

# 生成 spec 文件（如果不存在）
if (-not (Test-Path $SpecFile)) {
    Write-Host "生成 .spec 文件..." -ForegroundColor Cyan
    $specArgs = @(
        "main.py",
        "--name=AIOptimizer",
        "--onefile",
        "--windowed",
        "--icon=NUL",  # 占位，后面可替换为 .ico
        "--add-data=app;app",
        "--hidden-import=PySide6.QtCharts",
        "--hidden-import=PySide6.QtWebEngineWidgets",
        "--hidden-import=tiktoken_ext.openai_public",
        "--collect-all=tiktoken",
        "--collect-all=aiosqlite",
        "--collect-all=pydantic",
        "--collect-all=openai",
        "--collect-all=anthropic",
        "--collect-all=google.generativeai",
    )
    pyinstaller @specArgs
}

# 修改 spec 文件（添加版本信息、资源等）
$specContent = Get-Content $SpecFile -Raw
# 这里可以注入版本信息、图标等
$specContent = $specContent -replace 'version=.*?,', "version='$Version',"
Set-Content $SpecFile $specContent -Encoding UTF8

# 执行打包
Write-Host "开始打包..." -ForegroundColor Cyan
$buildArgs = @($SpecFile, "--clean", "--noconfirm")
if ($UseUpx) { $buildArgs += "--upx-dir=$(Split-Path (Get-Command upx).Source)" }
pyinstaller @buildArgs

# 验证输出
$ExePath = Join-Path $DistDir "AIOptimizer.exe"
if (Test-Path $ExePath) {
    $sizeMB = [math]::Round((Get-Item $ExePath).Length / 1MB, 1)
    Write-Host "✅ 打包成功: $ExePath ($sizeMB MB)" -ForegroundColor Green
} else {
    Write-Host "❌ 打包失败，未找到 exe" -ForegroundColor Red
    exit 1
}

# 生成 SHA256
$hash = Get-FileHash $ExePath -Algorithm SHA256
$hashFile = Join-Path $DistDir "AIOptimizer.exe.sha256"
Set-Content $hashFile $hash.Hash
Write-Host "SHA256: $($hash.Hash)" -ForegroundColor Cyan
Write-Host "已写入: $hashFile" -ForegroundColor Cyan