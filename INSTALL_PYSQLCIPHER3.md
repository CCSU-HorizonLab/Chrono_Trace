# pysqlcipher3 Windows 安装指南

## ⚠️ 前置条件

pysqlcipher3 是 C 扩展，需要编译。Windows 上需要以下组件：

---

## 📦 步骤 1：安装 OpenSSL

pysqlcipher3 依赖 OpenSSL 加密库。

### 方法 1：使用 Winget（推荐）

```powershell
# 安装 OpenSSL 开发版（包含头文件和库）
winget install ShiningLight.OpenSSL.Dev
```

安装后默认路径：`C:\Program Files\OpenSSL-Win64\`

### 方法 2：手动下载

1. 访问：https://slproweb.com/products/Win32OpenSSL.html
2. 下载 **Win64 OpenSSL v3.x.x** (完整版，不是 Light)
3. 安装到默认路径：`C:\Program Files\OpenSSL-Win64\`

---

## 📦 步骤 2：设置环境变量

pysqlcipher3 通过 `OPENSSL_CONF` 环境变量查找 OpenSSL。

### 临时设置（PowerShell）

```powershell
$env:OPENSSL_CONF = "C:\Program Files\OpenSSL-Win64\bin\openssl.cfg"
```

### 永久设置（系统环境变量）

```powershell
# 使用 PowerShell（需要管理员权限）
[System.Environment]::SetEnvironmentVariable('OPENSSL_CONF', 'C:\Program Files\OpenSSL-Win64\bin\openssl.cfg', 'User')
```

或手动设置：
1. 右键"此电脑" → 属性 → 高级系统设置 → 环境变量
2. 新建用户变量：
   - 变量名：`OPENSSL_CONF`
   - 变量值：`C:\Program Files\OpenSSL-Win64\bin\openssl.cfg`

---

## 📦 步骤 3：下载 SQLCipher Amalgamation

pysqlcipher3 需要 SQLCipher 的 amalgamation 版本（单文件源码）。

### 方法 1：从 SQLCipher 官方下载

```powershell
# 创建 amalgamation 目录
cd "d:\xunlei download\pysqlcipher3-1.2.0\pysqlcipher3-1.2.0"
mkdir amalgamation

# 下载 SQLCipher amalgamation（需要手动）
# 访问：https://www.zetetic.net/sqlcipher/open-source/
# 下载 sqlcipher-amalgamation-*.zip
# 解压 sqlite3.c 和 sqlite3.h 到 amalgamation 目录
```

### 方法 2：从 GitHub 构建（高级）

```bash
git clone https://github.com/sqlcipher/sqlcipher.git
cd sqlcipher
./configure --enable-tempstore=yes CFLAGS="-DSQLITE_HAS_CODEC"
make sqlite3.c
# 复制生成的 sqlite3.c 和 sqlite3.h 到 pysqlcipher3/amalgamation/
```

---

## 📦 步骤 4：安装 pysqlcipher3

### 方法 1：使用 amalgamation 编译

```powershell
cd "d:\xunlei download\pysqlcipher3-1.2.0\pysqlcipher3-1.2.0"

# 确保环境变量已设置
$env:OPENSSL_CONF = "C:\Program Files\OpenSSL-Win64\bin\openssl.cfg"

# 使用 amalgamation 构建
python setup.py build_amalgamation
python setup.py install
```

### 方法 2：系统库方式（需要预编译的 libsqlcipher）

```powershell
# 需要先编译或下载 libsqlcipher.lib（更复杂）
python setup.py build_ext --libraries=sqlcipher
python setup.py install
```

---

## ✅ 验证安装

```powershell
python -c "import pysqlcipher3; print('✅ 安装成功')"
```

---

## 🚨 常见问题

### 问题 1：找不到 OpenSSL

**错误信息**：
```
Fatal error: OpenSSL could not be detected!
```

**解决方案**：
```powershell
# 确认 OpenSSL 已安装
Test-Path "C:\Program Files\OpenSSL-Win64\bin\openssl.cfg"

# 设置环境变量
$env:OPENSSL_CONF = "C:\Program Files\OpenSSL-Win64\bin\openssl.cfg"
```

### 问题 2：缺少 amalgamation 文件

**错误信息**：
```
SQL Cipher amalgamation not found
```

**解决方案**：
确保 `amalgamation/sqlite3.c` 和 `amalgamation/sqlite3.h` 存在。

### 问题 3：编译器错误（转义序列）

**错误信息**：
```
error C2017: 非法的转义序列
```

**原因**：Windows 路径反斜杠问题（你当前遇到的问题）

**解决方案**：
这是 pysqlcipher3 本身的 bug（setup.py 第 69 行），需要修改源码：

```python
# 修改 setup.py 第 68-70 行
def quote_argument(arg):
    if sys.platform == 'win32':
        return '"' + arg.replace('\\', '\\\\') + '"'  # 转义反斜杠
    else:
        return '"' + arg + '"'
```

---

## 🎯 快速命令汇总

```powershell
# 1. 安装 OpenSSL
winget install ShiningLight.OpenSSL.Dev

# 2. 设置环境变量（重启 PowerShell 后生效）
[System.Environment]::SetEnvironmentVariable('OPENSSL_CONF', 'C:\Program Files\OpenSSL-Win64\bin\openssl.cfg', 'User')

# 3. 下载 SQLCipher amalgamation（手动）
# https://github.com/sqlcipher/sqlcipher/releases

# 4. 修复 setup.py bug（见上方）

# 5. 编译安装
cd "d:\xunlei download\pysqlcipher3-1.2.0\pysqlcipher3-1.2.0"
python setup.py build_amalgamation
python setup.py install
```

---

## 💡 推荐：使用预编译替代方案

如果以上步骤过于复杂，建议使用以下替代品：

1. **sqlcipher3**（预编译 wheel）
   ```bash
   pip install sqlcipher3
   ```

2. **pysqlcipher3-binary**（非官方预编译）
   ```bash
   pip install pysqlcipher3-binary
   ```

3. **纯 Python 解密方案**（我已为你准备好代码）
