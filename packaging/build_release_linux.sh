#!/usr/bin/env bash
# Chrono Trace Linux 打包编排（对齐 packaging/build_release.ps1 的职责划分）
#
# 用法：./build_release_linux.sh [-f|--fast] [-v|--version <版本号>] [--skip-frontend-install]
# 流程：前端 npm 构建 → .venv-packaging-linux 自举/复用 → PyInstaller onedir → tar.gz + .desktop
# 产物：release/pyinstaller-linux/Chrono Trace/ 与 release/chrono-trace-<版本>-linux.tar.gz
#
# 与 Windows 链路差异：无 Inno Setup / 注册表 / WebView2 引导；无 cpu/gpu 变体
# （Linux 暂只出 CPU 轮子，GPU runtime 下载机制未接入 Linux）。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV_DIR=".venv-packaging-linux"
SPEC_PATH="packaging/chrono_trace_linux.spec"
REQUIREMENTS_PATH="packaging/requirements-packaging-linux.txt"
BUILD_INFO_PATH="packaging/generated/build_info.json"
RELEASE_ROOT="release"
BUILD_MODE="release"

FAST=0
SKIP_FRONTEND_INSTALL=0
VERSION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -f|--fast)
      FAST=1
      BUILD_MODE="test-fast"
      shift
      ;;
    --skip-frontend-install)
      SKIP_FRONTEND_INSTALL=1
      shift
      ;;
    -v|--version)
      VERSION="${2:-}"
      shift 2
      ;;
    *)
      if [[ -z "$VERSION" && "$1" != -* ]]; then
        VERSION="$1"
        shift
      else
        echo "未知参数: $1" >&2
        exit 2
      fi
      ;;
  esac
done

log() { printf '\033[1;36m[build_linux]\033[0m %s\n' "$*"; }

# ---------- 版本号解析：参数 > packaging/VERSION > frontend/package.json > 0.1.0 ----------
resolve_version() {
  if [[ -n "$VERSION" ]]; then
    echo "$VERSION"
    return
  fi
  if [[ -f packaging/VERSION ]]; then
    tr -d '\r\n' < packaging/VERSION
    return
  fi
  if command -v node >/dev/null 2>&1; then
    node -p "require('./frontend/package.json').version" 2>/dev/null && return
  fi
  echo "0.1.0"
}
VERSION="$(resolve_version)"
log "版本: ${VERSION}（模式: ${BUILD_MODE}）"

command -v npm >/dev/null 2>&1 || { echo "需要 npm（Node.js 18+）构建前端" >&2; exit 1; }

# ---------- 前端构建（只做一次） ----------
if [[ ! -f frontend/webdist/index.html || $FAST -eq 0 ]]; then
  log "构建前端…"
  if [[ $SKIP_FRONTEND_INSTALL -eq 0 && ! -d frontend/node_modules ]]; then
    (cd frontend && npm ci)
  fi
  (cd frontend && npm run build)
else
  log "跳过前端构建（fast 且产物已存在）"
fi
[[ -f frontend/webdist/index.html ]] || { echo "frontend/webdist 缺失" >&2; exit 1; }

# ---------- 打包环境自举/复用 ----------
setup_venv() {
  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    log "创建 $VENV_DIR…"
    python3 -m venv "$VENV_DIR"
  fi
  local requirements_hash
  requirements_hash="$(sha256sum "$REQUIREMENTS_PATH" | cut -d' ' -f1)"
  local hash_file="$VENV_DIR/.requirements-packaging.sha256"
  local need_install=0
  if [[ ! -f "$hash_file" || "$(cat "$hash_file" 2>/dev/null)" != "$requirements_hash" ]]; then
    need_install=1
  fi
  if ! "$VENV_DIR/bin/python" -m PyInstaller --version >/dev/null 2>&1; then
    need_install=1
  fi
  if [[ $need_install -eq 1 ]]; then
    log "安装打包依赖（torch 用 CPU 轮子）…"
    "$VENV_DIR/bin/python" -m pip install --upgrade pip
    # 先装 CPU torch：requirements 中的 torch==pin 随后命中已装版本，避免先拉 CUDA 巨包
    "$VENV_DIR/bin/python" -m pip install \
      --index-url https://download.pytorch.org/whl/cpu torch==2.5.1
    "$VENV_DIR/bin/python" -m pip install -r "$REQUIREMENTS_PATH"
    echo "$requirements_hash" > "$hash_file"
  else
    log "打包环境未变化，复用 $VENV_DIR"
  fi
}
setup_venv

# ---------- build_info（变体标识进产物，runtime_overrides 读取） ----------
mkdir -p packaging/generated release
printf '{"variant": "linux", "build_mode": "%s", "generated_at": %d}\n' \
  "$BUILD_MODE" "$(date +%s)" > "$BUILD_INFO_PATH"

# ---------- PyInstaller ----------
log "PyInstaller 打包…"
CLEAN_FLAG=()
if [[ $FAST -eq 0 ]]; then
  CLEAN_FLAG=(--clean)
fi
"$VENV_DIR/bin/python" -m PyInstaller --noconfirm \
  --workpath "$RELEASE_ROOT/build-linux" \
  --distpath "$RELEASE_ROOT/pyinstaller-linux" \
  "${CLEAN_FLAG[@]}" \
  "$SPEC_PATH"

DIST_DIR="$RELEASE_ROOT/pyinstaller-linux/Chrono Trace"
[[ -d "$DIST_DIR" ]] || { echo "打包产物目录缺失: $DIST_DIR" >&2; exit 1; }

# ---------- tar.gz + .desktop ----------
log "生成 tar.gz 与 .desktop…"
TARBALL="$RELEASE_ROOT/chrono-trace-${VERSION}-linux.tar.gz"
tar -czf "$TARBALL" -C "$RELEASE_ROOT/pyinstaller-linux" "Chrono Trace"

cat > "$RELEASE_ROOT/chrono-trace.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Chrono Trace
Comment=微信聊天记录本地分析与实时辅助（数据不出本机）
Exec=%APPPATH% --no-sandbox
Terminal=false
Categories=Utility;
DESKTOP
log "已生成 $RELEASE_ROOT/chrono-trace.desktop（安装时把 %APPPATH% 替换为 Chrono Trace 可执行文件绝对路径）"

log "完成：$DIST_DIR"
log "归档：$TARBALL"
