# Chrono Trace 打包说明

## 打包流程

当前正式打包链路分三步：

1. 将前端构建到 `frontend/webdist`
2. 使用 `packaging/chrono_trace.spec` 通过 PyInstaller 打包 `app.py`
3. 使用 `packaging/ChronoTrace.iss` 通过 Inno Setup 生成安装包

## 一键打包

推荐直接在项目根目录运行：

```powershell
.\build_release.ps1
```

如果你习惯双击脚本，也可以直接运行：

```text
build_release.bat
```

上面两个入口最终都会调用：

```text
packaging\build_release.ps1
```

默认命令保持正式发布语义不变，会执行：

1. 复用或初始化仓库内 `.venv-packaging`
2. 前端构建
3. PyInstaller 全量 clean 构建
4. Inno Setup 安装包输出

单一安装包（ONNX + DirectML 免 CUDA 免 torch，一个包通吃 CPU/GPU；torch 时代的 cpu/gpu 双变体已移除）。

## 打包环境

打包脚本复用仓库根目录下的专用 venv `.venv-packaging`，避免系统 Python 的杂项依赖污染 PyInstaller 分析结果。

只初始化或刷新打包环境：

```powershell
.\build_release.ps1 -BootstrapPackagingEnv
.\build_release.ps1 -BootstrapPackagingEnv -RefreshPackagingEnv
```

## 常用参数

只生成 PyInstaller 目录版，不生成安装器：

```powershell
.\build_release.ps1 -SkipInstaller
```

跳过前端 `npm ci`：

```powershell
.\build_release.ps1 -SkipFrontendInstall
```

手动指定版本号：

```powershell
.\build_release.ps1 -Version 0.1.1
```

生产环境测试用快速打包：

```powershell
.\build_release.ps1 -Fast
```

`-Fast` 的默认行为是：

- 跳过 `npm ci`
- 复用 `.venv-packaging`
- 不删除 `release\build`
- PyInstaller 不传 `--clean`
- 默认不生成安装器

如果快速模式也要补打安装包：

```powershell
.\build_release.ps1 -Fast -IncludeInstaller
```

## 产物位置

PyInstaller 目录版输出到：

```text
release\pyinstaller\ChronoTrace\
```

安装包输出到：

```text
release\installer\
```

正式交付时，优先使用安装包：

```text
release\installer\ChronoTraceSetup-版本号.exe
```

不要直接分发：

```text
release\build\
```

那是 PyInstaller 中间产物。

## 包体积构成（当前：模型内置）

推理栈切换 ONNX 后，安装包**内置 fp16 模型**（约 409MB 原始 / ~300MB 压缩后），换取新装机开箱即用：

| 项 | 旧 torch 版 | 当前 ONNX 版 |
|---|---|---|
| 安装包 | ~190MB（不含模型） | ~400MB（含模型） |
| 首次运行 | 需下载 1.17GB 模型 | 无下载，直接可用 |
| 用户总获取量 | ~1.36GB | ~400MB |

### 备选：小安装包方案（未实施，视需求启用）

若更在意安装包体积，可改为「首次运行时只下载 ONNX 产物」：

1. 把 `backend/data/models/<name>/onnx/` 两个目录上传到对应 ModelScope 仓库
   （`tingting0514/text2vec-base-chinese`、`tingting0514/chrono-trace-sentiment`）
2. 打包侧：删掉两个 spec 里的 onnx datas（安装包回到 ~100-150MB）
3. 运行时：`ensure_models_for_export.py` 的下载逻辑改为应用内触发，
   `snapshot_download(..., allow_patterns=["onnx/*"])` 只拉 ~409MB（避免整仓库 1.2GB）
4. 回退开关：ModelScope 下载失败时仍可手动放置 onnx 目录

## 推荐用法

- 正式发布：`.\build_release.ps1`
- 生产环境测试回归：`.\build_release.ps1 -Fast`
- 快速模式补安装包：`.\build_release.ps1 -Fast -IncludeInstaller`

## GPU 加速说明

运行时依赖为 `onnxruntime-directml`：免 CUDA、免 torch，有 N/AMD 卡自动走
DirectML，无卡回退 CPU——单一安装包通吃，无「GPU 运行时下载/一键配置」
流程（torch 时代的外部 overlay 机制已随 ONNX 单后端移除）。

## 可选：自动补装 WebView2

如果希望安装包在目标机器缺少 WebView2 Runtime 时自动补装，请将下面这个文件放到：

```text
packaging\third_party\MicrosoftEdgeWebview2Setup.exe
```

Inno Setup 脚本会自动检测并接入安装流程。

## Linux 打包

Linux 链路（`packaging/build_release_linux.sh`，根目录 `build_release_linux.sh` 透传）与 Windows 职责对齐：前端 npm 构建 → `.venv-packaging-linux` 自举（推理栈为 ONNX 无 torch，torch 仅存在于独立导出环境，不进产物；依赖哈希不变则复用）→ PyInstaller onedir（`chrono_trace_linux.spec`，去 wx_key/win32）→ `release/pyinstaller-linux/ChronoTrace/` + `release/chrono-trace-<版本>-linux.tar.gz` + `.desktop` 模板。

```bash
./build_release_linux.sh              # 完整打包
./build_release_linux.sh --fast       # 快速模式（不 clean、前端产物复用）
./build_release_linux.sh -v 1.2.0     # 指定版本号
```

与 Windows 差异：无 Inno Setup/注册表/WebView2 引导；无 cpu/gpu 变体（仅 CPU 轮子）；`.desktop` 中的 `%APPPATH%` 安装时替换为可执行文件绝对路径。AppImage/deb 为后续可选。

### tar.gz 产物使用

```bash
tar -xzf release/chrono-trace-<版本>-linux.tar.gz
cd ChronoTrace
./ChronoTrace          # onedir 自带 Python/Qt（推理栈 ONNX 无 torch），glibc>=2.34 即可运行
```

桌面集成：将 `release/chrono-trace.desktop` 的 `%APPPATH%` 替换为可执行文件绝对路径后放入 `~/.local/share/applications/`。密钥捕获仍需系统 `gdb`（见主 README「获取微信数据库密钥」）。
