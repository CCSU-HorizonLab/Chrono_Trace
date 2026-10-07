#!/usr/bin/env bash
# Chrono Trace Linux 打包编排（对齐 packaging/build_release.ps1 的职责划分）
#
# 用法：./build_release_linux.sh [-f|--fast] [-v|--version <版本号>] [--skip-frontend-install]
# 流程：前端 npm 构建 → .venv-packaging-linux 自举/复用 → PyInstaller onedir → tar.gz + .desktop
# 产物：release/pyinstaller-linux/ChronoTrace/ 与 release/chrono-trace-<版本>-linux.tar.gz
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
    log "安装打包依赖（推理栈为 ONNX，无 torch）…"
    # 清华镜像：默认 PyPI 在弱网下实测 87KB/s（116MB 轮子要 20 分钟+），
    # 与模型导出环境（ensure_onnx_models）保持同源
    local pip_index=(-i https://pypi.tuna.tsinghua.edu.cn/simple)
    "$VENV_DIR/bin/python" -m pip install "${pip_index[@]}" --upgrade pip
    "$VENV_DIR/bin/python" -m pip install "${pip_index[@]}" -r "$REQUIREMENTS_PATH"
    echo "$requirements_hash" > "$hash_file"
  else
    log "打包环境未变化，复用 $VENV_DIR"
  fi
}
# ---------- ONNX 模型导出（打包前置：产物缺失时用独立 export 环境生成） ----------
ensure_onnx_models() {
  echo "==> ONNX 模型（首次构建自动从 ModelScope 下载源模型并导出）"
  local models_root="backend/data/models"
  # 与 spec 内置清单对齐：Linux 只打 bge + sentiment（text2vec 不进包）
  if [ -f "$models_root/bge_small_zh_v15/onnx/model.onnx" ] && \
     [ -f "$models_root/sentiment_3class/onnx/model.fp16.onnx" ]; then
    echo "ONNX 产物已存在，跳过下载与导出。"
    return
  fi

  # torch 仅作导出工具（独立环境，不进产物）；modelscope 按需下载源模型
  local export_venv=".venv-model-export"
  if [ ! -x "$export_venv/bin/python" ]; then
    echo "创建模型导出环境 ($export_venv)..."
    python3 -m venv "$export_venv"
    "$export_venv/bin/pip" install --quiet -i https://pypi.tuna.tsinghua.edu.cn/simple torch --extra-index-url https://download.pytorch.org/whl/cpu
    "$export_venv/bin/pip" install --quiet -i https://pypi.tuna.tsinghua.edu.cn/simple "transformers>=4.30" "onnx>=1.15" "onnxruntime>=1.17" onnxconverter-common "modelscope>=1.17"
  fi
  "$export_venv/bin/python" backend/scripts/ensure_models_for_export.py --with-export
}

ensure_onnx_models

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

DIST_DIR="$RELEASE_ROOT/pyinstaller-linux/ChronoTrace"
[[ -d "$DIST_DIR" ]] || { echo "打包产物目录缺失: $DIST_DIR" >&2; exit 1; }

# ---------- 选择性 strip（瘦身）----------
# spec 内全量 strip 会打坏 scipy OpenBLAS 的 ELF 布局（load 对齐校验失败），
# 故只对大体积、耐裁的 .so 手工裁符号：torch/Qt 主力收益在此。
# 排除 scipy*/numpy* 的 vendored 库与其余小文件。
log "选择性 strip 大体积 .so…"
find "$DIST_DIR/_internal" -type f -name "*.so*" -size +5M \
  ! -path "*scipy*" ! -path "*numpy*" ! -path "*OpenBLAS*" ! -path "*openblas*" \
  -exec strip --strip-unneeded {} \; 2>/dev/null || true

# ---------- tar.gz + .desktop ----------
log "生成 tar.gz 与 .desktop…"
FILE_VERSION="${VERSION// /-}"  # 文件名不含空格（显示版本不变）
TARBALL="$RELEASE_ROOT/chrono-trace-${FILE_VERSION}-linux.tar.gz"
tar -czf "$TARBALL" -C "$RELEASE_ROOT/pyinstaller-linux" "ChronoTrace"

cat > "$RELEASE_ROOT/chrono-trace.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Chrono Trace
Comment=微信聊天记录本地分析与实时辅助（数据不出本机）
Exec=%APPPATH% --no-sandbox
Terminal=false
Categories=Utility;
DESKTOP
log "已生成 $RELEASE_ROOT/chrono-trace.desktop（安装时把 %APPPATH% 替换为 ChronoTrace 可执行文件绝对路径）"

log "完成：$DIST_DIR"
log "归档：$TARBALL"
