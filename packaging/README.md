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

默认变体为 `cpu`。

## 打包环境

打包脚本会按变体复用仓库根目录下的专用 venv，避免系统 Python 的杂项依赖污染 PyInstaller 分析结果。

- `cpu` 变体使用 `.venv-packaging`
- `gpu` 变体使用 `.venv-packaging-gpu`

只初始化或刷新打包环境：

```powershell
.\build_release.ps1 -BootstrapPackagingEnv
.\build_release.ps1 -BootstrapPackagingEnv -RefreshPackagingEnv
.\build_release.ps1 -BootstrapPackagingEnv -Variant gpu
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

选择构建变体：

```powershell
.\build_release.ps1 -Variant cpu
.\build_release.ps1 -Variant gpu
.\build_release.ps1 -Variant both
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
.\build_release.ps1 -Fast -Variant both -IncludeInstaller
```

## 产物位置

PyInstaller 目录版输出到：

```text
release\pyinstaller\Chrono Trace\
release\pyinstaller-gpu\Chrono Trace\
```

安装包输出到：

```text
release\installer\
```

正式交付时，优先使用安装包：

```text
release\installer\ChronoTraceSetup-版本号.exe
release\installer\ChronoTraceSetup-版本号-GPU.exe
```

不要直接分发：

```text
release\build\
```

那是 PyInstaller 中间产物。

## 推荐用法

- CPU 正式发布：`.\build_release.ps1`
- GPU 正式发布：`.\build_release.ps1 -Variant gpu`
- 同时生成两个版本：`.\build_release.ps1 -Variant both`
- 生产环境测试回归：`.\build_release.ps1 -Fast`
- 快速模式需要两个安装包：`.\build_release.ps1 -Fast -Variant both -IncludeInstaller`

## GPU 运行时说明

CPU 安装包默认内置 CPU 版 PyTorch。

如果目标机器具备 NVIDIA GPU，应用内的“一键配置 GPU 运行时”会：

1. 下载独立的嵌入式 Python 运行时到 `%LOCALAPPDATA%\Chrono Trace\runtime\gpu`
2. 下载并安装支持 CUDA 的 PyTorch 到外部 overlay 目录
3. 重启应用后优先使用这个 overlay 运行时

这样不会直接修改安装目录中的 PyInstaller 主环境，更适合生产测试分发。

## 可选：自动补装 WebView2

如果希望安装包在目标机器缺少 WebView2 Runtime 时自动补装，请将下面这个文件放到：

```text
packaging\third_party\MicrosoftEdgeWebview2Setup.exe
```

Inno Setup 脚本会自动检测并接入安装流程。
