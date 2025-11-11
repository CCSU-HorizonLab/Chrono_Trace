# pysqlcipher3 Windows 安装指南

本项目的微信数据库解密功能依赖 `pysqlcipher3`，该库在 Windows 上需要手动编译安装。

---

## 📋 快速检查

运行以下命令检查是否已安装：

```powershell
python -c "import pysqlcipher3; print('✅ 已安装')"
```

如果提示 `ModuleNotFoundError`，请继续以下步骤。

---

## 🚀 方式一：一键安装（推荐）

将以下内容保存为 `install_pysqlcipher3.ps1`，然后运行：

```powershell
powershell -ExecutionPolicy Bypass -File install_pysqlcipher3.ps1
```

<details>
<summary>点击查看完整脚本内容</summary>

```powershell
# pysqlcipher3 一键安装脚本
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "pysqlcipher3 自动安装脚本" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 检查是否已安装
try {
    python -c "import pysqlcipher3" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ pysqlcipher3 已安装" -ForegroundColor Green
        exit 0
    }
} catch {}

# 检查 OpenSSL
$opensslPath = "C:\Program Files\OpenSSL-Win64\bin\openssl.cfg"
if (-not (Test-Path $opensslPath)) {
    Write-Host "❌ 未检测到 OpenSSL，正在安装..." -ForegroundColor Yellow
    winget install ShiningLight.OpenSSL
    
    # 设置环境变量
    [System.Environment]::SetEnvironmentVariable('OPENSSL_CONF', $opensslPath, 'User')
    Write-Host "⚠️  已安装 OpenSSL 并设置环境变量" -ForegroundColor Yellow
    Write-Host "⚠️  请重启 PowerShell 后重新运行此脚本" -ForegroundColor Yellow
    exit 1
}

# 验证环境变量
if (-not $env:OPENSSL_CONF) {
    Write-Host "⚠️  检测到 OPENSSL_CONF 环境变量未生效" -ForegroundColor Yellow
    $env:OPENSSL_CONF = $opensslPath
}

Write-Host "✅ OpenSSL 已就绪: $env:OPENSSL_CONF" -ForegroundColor Green

# 创建临时目录
$tempDir = "$env:TEMP\pysqlcipher3-install-$(Get-Random)"
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
Write-Host "📁 临时目录: $tempDir" -ForegroundColor Gray

try {
    Set-Location $tempDir
    
    # 下载源码
    Write-Host "📥 正在下载 pysqlcipher3 源码..." -ForegroundColor Cyan
    $downloadUrl = "https://github.com/rigglemania/pysqlcipher3/archive/refs/tags/v1.2.0.zip"
    Invoke-WebRequest -Uri $downloadUrl -OutFile "pysqlcipher3.zip"
    Expand-Archive -Path "pysqlcipher3.zip" -DestinationPath "." -Force
    Set-Location "pysqlcipher3-1.2.0"
    
    # 创建 amalgamation 目录
    New-Item -ItemType Directory -Force -Path "amalgamation\sqlcipher" | Out-Null
    
    # 下载 SQLCipher amalgamation
    Write-Host "📥 正在下载 SQLCipher amalgamation..." -ForegroundColor Cyan
    $baseUrl = "https://raw.githubusercontent.com/geekbrother/sqlcipher-amalgamation/main/src"
    Invoke-WebRequest -Uri "$baseUrl/sqlite3.c" -OutFile "amalgamation\sqlite3.c"
    Invoke-WebRequest -Uri "$baseUrl/sqlite3.h" -OutFile "amalgamation\sqlite3.h"
    Copy-Item "amalgamation\sqlite3.h" -Destination "amalgamation\sqlcipher\sqlite3.h"
    
    Write-Host "✅ SQLCipher amalgamation 文件已下载" -ForegroundColor Green
    
    # 修改 setup.py（适配新版 OpenSSL）
    Write-Host "🔧 正在修改 setup.py（适配 OpenSSL 3.x）..." -ForegroundColor Cyan
    $setupContent = Get-Content "setup.py" -Raw -Encoding UTF8
    
    # 替换库名
    $setupContent = $setupContent -replace 'ext\.extra_link_args\.append\("libeay32\.lib"\)', 'ext.extra_link_args.append("libcrypto.lib")'
    
    # 替换库路径
    $setupContent = $setupContent -replace "ext\.extra_link_args\.append\('/LIBPATH:' \+ openssl_lib_path\)", "ext.extra_link_args.append('/LIBPATH:' + openssl_lib_path + r'\\VC\\x64\\MD')"
    
    Set-Content "setup.py" -Value $setupContent -Encoding UTF8
    Write-Host "✅ setup.py 已修改" -ForegroundColor Green
    
    # 编译
    Write-Host "🔨 正在编译..." -ForegroundColor Cyan
    python setup.py build_amalgamation
    if ($LASTEXITCODE -ne 0) {
        throw "编译失败"
    }
    
    # 安装
    Write-Host "📦 正在安装..." -ForegroundColor Cyan
    python setup.py install
    if ($LASTEXITCODE -ne 0) {
        throw "安装失败"
    }
    
    # 验证
    Write-Host "🧪 正在验证安装..." -ForegroundColor Cyan
    python -c "import pysqlcipher3.dbapi2 as sqlite; print('验证成功')"
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Green
        Write-Host "✅ pysqlcipher3 安装成功！" -ForegroundColor Green
        Write-Host "========================================" -ForegroundColor Green
    } else {
        throw "导入测试失败"
    }
    
} catch {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "❌ 安装失败: $_" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "请查看上方错误信息，或尝试手动安装（见文档）" -ForegroundColor Yellow
    exit 1
} finally {
    # 清理临时目录
    Set-Location $env:TEMP
    try {
        Remove-Item -Recurse -Force $tempDir -ErrorAction SilentlyContinue
        Write-Host "🧹 已清理临时文件" -ForegroundColor Gray
    } catch {}
}
```

</details>

---

## 🔧 方式二：手动安装

### **步骤 1：安装 Visual Studio Build Tools**

确保已安装 C++ 构建工具：

```powershell
# 检查是否已安装
where cl.exe
```

如果未安装，下载并安装：https://visualstudio.microsoft.com/visual-cpp-build-tools/

勾选 **"使用 C++ 的桌面开发"**

---

### **步骤 2：安装 OpenSSL**

```powershell
# 使用 winget 安装（推荐）
winget install ShiningLight.OpenSSL
```

或手动下载：https://slproweb.com/products/Win32OpenSSL.html  
下载 **Win64 OpenSSL v3.x.x**（完整版，不是 Light）

---

### **步骤 3：设置环境变量**

**永久设置**（推荐）：
```powershell
[System.Environment]::SetEnvironmentVariable('OPENSSL_CONF', 'C:\Program Files\OpenSSL-Win64\bin\openssl.cfg', 'User')
```

⚠️ **设置后必须重启 PowerShell 才能生效！**

验证：
```powershell
echo $env:OPENSSL_CONF
# 应该输出: C:\Program Files\OpenSSL-Win64\bin\openssl.cfg
```

---

### **步骤 4：下载 pysqlcipher3 源码**

```powershell
# 方式 A：使用 pip 下载
pip download pysqlcipher3 --no-binary :all:
tar -xzf pysqlcipher3-1.2.0.tar.gz
cd pysqlcipher3-1.2.0

# 方式 B：从 GitHub 下载
Invoke-WebRequest -Uri "https://github.com/rigglemania/pysqlcipher3/archive/refs/tags/v1.2.0.zip" -OutFile "pysqlcipher3.zip"
Expand-Archive pysqlcipher3.zip
cd pysqlcipher3-1.2.0
```

---

### **步骤 5：下载 SQLCipher Amalgamation 文件**

```powershell
# 创建目录
mkdir amalgamation
mkdir amalgamation\sqlcipher

# 下载文件
$baseUrl = "https://raw.githubusercontent.com/geekbrother/sqlcipher-amalgamation/main/src"
Invoke-WebRequest -Uri "$baseUrl/sqlite3.c" -OutFile "amalgamation\sqlite3.c"
Invoke-WebRequest -Uri "$baseUrl/sqlite3.h" -OutFile "amalgamation\sqlite3.h"

# 复制到 sqlcipher 子目录
Copy-Item "amalgamation\sqlite3.h" -Destination "amalgamation\sqlcipher\sqlite3.h"
```

验证：
```powershell
Test-Path "amalgamation\sqlite3.c"           # 应返回 True
Test-Path "amalgamation\sqlite3.h"           # 应返回 True
Test-Path "amalgamation\sqlcipher\sqlite3.h" # 应返回 True
```

---

### **步骤 6：修改 setup.py**

打开 `setup.py`，找到约第 137-138 行：

```python
# 原代码：
ext.extra_link_args.append("libeay32.lib")
ext.extra_link_args.append('/LIBPATH:' + openssl_lib_path)
```

修改为：
```python
# 新代码：
ext.extra_link_args.append("libcrypto.lib")
ext.extra_link_args.append('/LIBPATH:' + openssl_lib_path + r"\VC\x64\MD")
```

**原因**：OpenSSL 3.x 使用 `libcrypto.lib` 替代了旧版的 `libeay32.lib`

---

### **步骤 7：编译并安装**

```powershell
# 编译
python setup.py build_amalgamation

# 安装
python setup.py install
```

---

### **步骤 8：验证安装**

```powershell
python -c "import pysqlcipher3.dbapi2 as sqlite; print('✅ 安装成功！')"
```

---

## 🚨 常见问题

### ❌ 问题 1：`Fatal error: OpenSSL could not be detected!`

**原因**：环境变量 `OPENSSL_CONF` 未设置或未生效

**解决方案**：
```powershell
# 检查 OpenSSL 是否存在
Test-Path "C:\Program Files\OpenSSL-Win64\bin\openssl.cfg"

# 设置环境变量（永久）
[System.Environment]::SetEnvironmentVariable('OPENSSL_CONF', 'C:\Program Files\OpenSSL-Win64\bin\openssl.cfg', 'User')

# ⚠️ 重启 PowerShell 后生效
```

---

### ❌ 问题 2：`SQL Cipher amalgamation not found`

**原因**：缺少 SQLCipher 源文件

**解决方案**：
确保 `amalgamation` 目录包含以下文件：
- `sqlite3.c`
- `sqlite3.h`
- `sqlcipher/sqlite3.h`

重新执行步骤 5。

---

### ❌ 问题 3：`LINK : fatal error LNK1181: 无法打开输入文件 "libeay32.lib"`

**原因**：OpenSSL 3.x 不再使用 `libeay32.lib`

**解决方案**：
按照步骤 6 修改 `setup.py`，将 `libeay32.lib` 改为 `libcrypto.lib`

---

### ❌ 问题 4：`fatal error C1083: 无法打开包括文件: "sqlcipher/sqlite3.h"`

**原因**：缺少 `sqlcipher` 子目录

**解决方案**：
```powershell
mkdir amalgamation\sqlcipher
Copy-Item amalgamation\sqlite3.h amalgamation\sqlcipher\
```

---

### ❌ 问题 5：`error: Microsoft Visual C++ 14.0 or greater is required`

**原因**：未安装 Visual Studio Build Tools

**解决方案**：
下载并安装：https://visualstudio.microsoft.com/visual-cpp-build-tools/

勾选 **"使用 C++ 的桌面开发"**，然后重启终端。

---

## 💡 替代方案（不推荐）

如果编译持续失败，可以考虑使用 `sqlcipher3` 库（不同的包）：

```powershell
pip install sqlcipher3-wheels
```

**注意**：此库 API 与 `pysqlcipher3` 略有不同，可能需要修改代码。

---

## 📝 关键文件说明

| 文件 | 用途 |
|------|------|
| `sqlite3.c` | SQLCipher 核心实现（C 源码） |
| `sqlite3.h` | SQLCipher 头文件 |
| `sqlcipher/sqlite3.h` | setup.py 编译时引用的头文件副本 |
| `libcrypto.lib` | OpenSSL 3.x 的加密库（位于 `OpenSSL-Win64\lib\VC\x64\MD\` 下） |

---

## 📚 参考资源

- **pysqlcipher3 GitHub**: https://github.com/rigglemania/pysqlcipher3
- **SQLCipher Amalgamation**: https://github.com/geekbrother/sqlcipher-amalgamation
- **OpenSSL for Windows**: https://slproweb.com/products/Win32OpenSSL.html
- **Visual Studio Build Tools**: https://visualstudio.microsoft.com/visual-cpp-build-tools/

---

## 🔍 技术原理

`pysqlcipher3` 是 SQLCipher 的 Python 绑定，用于处理加密的 SQLite 数据库（微信数据库使用此加密方式）。

**编译流程**：
1. `setup.py` 读取 `amalgamation/sqlite3.c` 源码
2. 使用 Visual Studio 编译器（cl.exe）编译 C 代码
3. 链接 OpenSSL 的 `libcrypto.lib` 库
4. 生成 Python 扩展模块（`.pyd` 文件）

---

**最后更新**: 2025-11-11  
**测试环境**: Windows 11, Python 3.11, OpenSSL 3.4.0
