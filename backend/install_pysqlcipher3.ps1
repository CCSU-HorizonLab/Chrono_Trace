# pysqlcipher3 一键安装脚本
# 适用于 Windows 平台
# 使用方法: powershell -ExecutionPolicy Bypass -File install_pysqlcipher3.ps1

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  pysqlcipher3 自动安装脚本" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 检查是否已安装
Write-Host "🔍 检查 pysqlcipher3 安装状态..." -ForegroundColor Gray
try {
    $null = python -c "import pysqlcipher3" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ pysqlcipher3 已安装" -ForegroundColor Green
        python -c "import pysqlcipher3; print(f'   版本: {pysqlcipher3.version}')"
        Write-Host ""
        exit 0
    }
} catch {}

Write-Host "⚠️  pysqlcipher3 未安装，开始安装流程..." -ForegroundColor Yellow
Write-Host ""

# 检查 Python
Write-Host "🔍 检查 Python..." -ForegroundColor Gray
try {
    $pythonVersion = python --version 2>&1
    Write-Host "   $pythonVersion" -ForegroundColor Gray
} catch {
    Write-Host "❌ 未检测到 Python，请先安装 Python 3.7+" -ForegroundColor Red
    exit 1
}

# 检查 Visual Studio Build Tools
Write-Host "🔍 检查 Visual Studio Build Tools..." -ForegroundColor Gray
$clPath = where.exe cl.exe 2>$null
if ($clPath) {
    Write-Host "   ✅ 已安装" -ForegroundColor Green
} else {
    Write-Host "   ⚠️  未检测到 cl.exe，请确保已安装 Visual Studio Build Tools" -ForegroundColor Yellow
    Write-Host "   下载地址: https://visualstudio.microsoft.com/visual-cpp-build-tools/" -ForegroundColor Gray
    $continue = Read-Host "   是否继续？(y/n)"
    if ($continue -ne 'y') {
        exit 1
    }
}

# 检查 OpenSSL
Write-Host "🔍 检查 OpenSSL..." -ForegroundColor Gray
$opensslPath = "C:\Program Files\OpenSSL-Win64\bin\openssl.cfg"

if (-not (Test-Path $opensslPath)) {
    Write-Host "   ❌ 未检测到 OpenSSL" -ForegroundColor Yellow
    Write-Host "   正在安装 OpenSSL..." -ForegroundColor Cyan
    
    try {
        winget install ShiningLight.OpenSSL.Light --accept-source-agreements --accept-package-agreements
        
        if (Test-Path $opensslPath) {
            Write-Host "   ✅ OpenSSL 安装成功" -ForegroundColor Green
        } else {
            Write-Host "   ⚠️  自动安装失败，请手动安装" -ForegroundColor Yellow
            Write-Host "   下载地址: https://slproweb.com/products/Win32OpenSSL.html" -ForegroundColor Gray
            exit 1
        }
    } catch {
        Write-Host "   ❌ 安装失败: $_" -ForegroundColor Red
        Write-Host "   请手动下载安装: https://slproweb.com/products/Win32OpenSSL.html" -ForegroundColor Gray
        exit 1
    }
    
    # 设置环境变量
    [System.Environment]::SetEnvironmentVariable('OPENSSL_CONF', $opensslPath, 'User')
    Write-Host "   ✅ 已设置 OPENSSL_CONF 环境变量" -ForegroundColor Green
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Yellow
    Write-Host "⚠️  请重启 PowerShell 后重新运行此脚本" -ForegroundColor Yellow
    Write-Host "========================================" -ForegroundColor Yellow
    exit 0
} else {
    Write-Host "   ✅ 已安装: $opensslPath" -ForegroundColor Green
}

# 验证环境变量
if (-not $env:OPENSSL_CONF) {
    Write-Host "   ⚠️  OPENSSL_CONF 环境变量未生效，临时设置中..." -ForegroundColor Yellow
    $env:OPENSSL_CONF = $opensslPath
}

Write-Host "   OPENSSL_CONF = $env:OPENSSL_CONF" -ForegroundColor Gray
Write-Host ""

# 创建临时目录
$tempDir = "$env:TEMP\pysqlcipher3-install-$(Get-Random)"
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
Write-Host "📁 创建临时目录: $tempDir" -ForegroundColor Gray
Write-Host ""

try {
    Set-Location $tempDir
    
    # 下载 pysqlcipher3 源码
    Write-Host "📥 正在下载 pysqlcipher3 源码..." -ForegroundColor Cyan
    $downloadUrl = "https://github.com/rigglemania/pysqlcipher3/archive/refs/tags/v1.2.0.zip"
    
    try {
        Invoke-WebRequest -Uri $downloadUrl -OutFile "pysqlcipher3.zip" -TimeoutSec 60
        Write-Host "   ✅ 下载完成" -ForegroundColor Green
    } catch {
        Write-Host "   ❌ 下载失败: $_" -ForegroundColor Red
        Write-Host "   请检查网络连接或手动下载: $downloadUrl" -ForegroundColor Gray
        throw
    }
    
    Expand-Archive -Path "pysqlcipher3.zip" -DestinationPath "." -Force
    Set-Location "pysqlcipher3-1.2.0"
    Write-Host ""
    
    # 创建 amalgamation 目录
    New-Item -ItemType Directory -Force -Path "amalgamation\sqlcipher" | Out-Null
    
    # 下载 SQLCipher amalgamation
    Write-Host "📥 正在下载 SQLCipher amalgamation 文件..." -ForegroundColor Cyan
    $baseUrl = "https://raw.githubusercontent.com/geekbrother/sqlcipher-amalgamation/main/src"
    
    try {
        Invoke-WebRequest -Uri "$baseUrl/sqlite3.c" -OutFile "amalgamation\sqlite3.c" -TimeoutSec 60
        Invoke-WebRequest -Uri "$baseUrl/sqlite3.h" -OutFile "amalgamation\sqlite3.h" -TimeoutSec 60
        Copy-Item "amalgamation\sqlite3.h" -Destination "amalgamation\sqlcipher\sqlite3.h"
        Write-Host "   ✅ 下载完成" -ForegroundColor Green
    } catch {
        Write-Host "   ❌ 下载失败: $_" -ForegroundColor Red
        throw
    }
    Write-Host ""
    
    # 修改 setup.py（适配新版 OpenSSL）
    Write-Host "🔧 正在修改 setup.py（适配 OpenSSL 3.x）..." -ForegroundColor Cyan
    $setupContent = Get-Content "setup.py" -Raw -Encoding UTF8
    
    # 替换库名：libeay32.lib -> libcrypto.lib
    $setupContent = $setupContent -replace 'ext\.extra_link_args\.append\("libeay32\.lib"\)', 'ext.extra_link_args.append("libcrypto.lib")'
    
    # 替换库路径：添加 \VC\x64\MD 子目录
    $setupContent = $setupContent -replace "ext\.extra_link_args\.append\('/LIBPATH:' \+ openssl_lib_path\)", "ext.extra_link_args.append('/LIBPATH:' + openssl_lib_path + r'\\VC\\x64\\MD')"
    
    Set-Content "setup.py" -Value $setupContent -Encoding UTF8
    Write-Host "   ✅ setup.py 已修改" -ForegroundColor Green
    Write-Host ""
    
    # 编译
    Write-Host "🔨 正在编译 pysqlcipher3..." -ForegroundColor Cyan
    Write-Host "   (这可能需要几分钟，请耐心等待)" -ForegroundColor Gray
    Write-Host ""
    
    python setup.py build_amalgamation 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   ❌ 编译失败" -ForegroundColor Red
        Write-Host "   尝试显示详细错误信息..." -ForegroundColor Gray
        python setup.py build_amalgamation
        throw "编译失败，请查看上方错误信息"
    }
    Write-Host "   ✅ 编译完成" -ForegroundColor Green
    Write-Host ""
    
    # 安装
    Write-Host "📦 正在安装 pysqlcipher3..." -ForegroundColor Cyan
    python setup.py install 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   ❌ 安装失败" -ForegroundColor Red
        python setup.py install
        throw "安装失败，请查看上方错误信息"
    }
    Write-Host "   ✅ 安装完成" -ForegroundColor Green
    Write-Host ""
    
    # 验证安装
    Write-Host "🧪 正在验证安装..." -ForegroundColor Cyan
    $testResult = python -c "import pysqlcipher3.dbapi2 as sqlite; print('验证成功')" 2>&1
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Green
        Write-Host "✅ pysqlcipher3 安装成功！" -ForegroundColor Green
        Write-Host "========================================" -ForegroundColor Green
        Write-Host ""
        Write-Host "测试导入：" -ForegroundColor Gray
        python -c "import pysqlcipher3.dbapi2 as sqlite; print(f'  版本: {sqlite.version}'); print(f'  SQLite: {sqlite.sqlite_version}')"
        Write-Host ""
    } else {
        throw "导入测试失败：$testResult"
    }
    
} catch {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "❌ 安装失败" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "错误信息: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "请尝试以下操作：" -ForegroundColor Yellow
    Write-Host "1. 检查是否安装了 Visual Studio Build Tools" -ForegroundColor Gray
    Write-Host "2. 确认 OPENSSL_CONF 环境变量已设置" -ForegroundColor Gray
    Write-Host "3. 重启 PowerShell 后重试" -ForegroundColor Gray
    Write-Host "4. 查看详细安装文档: backend\INSTALL_PYSQLCIPHER3.md" -ForegroundColor Gray
    Write-Host ""
    
    $exitCode = 1
} finally {
    # 清理临时目录
    Set-Location $env:TEMP
    try {
        Remove-Item -Recurse -Force $tempDir -ErrorAction SilentlyContinue
        Write-Host "🧹 已清理临时文件" -ForegroundColor Gray
        Write-Host ""
    } catch {}
    
    if ($exitCode -eq 1) {
        exit 1
    }
}
