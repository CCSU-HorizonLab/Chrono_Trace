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

## 产物位置

PyInstaller 目录版输出到：

```text
release\pyinstaller\Chrono Trace\
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

## 可选：自动补装 WebView2

如果希望安装包在目标机器缺少 WebView2 Runtime 时自动补装，请将下面这个文件放到：

```text
packaging\third_party\MicrosoftEdgeWebview2Setup.exe
```

Inno Setup 脚本会自动检测并接入安装流程。
