#!/usr/bin/env bash
# 根目录壳脚本（对齐 build_release.bat 的角色）：透传参数到 packaging/build_release_linux.sh
cd "$(dirname "$0")"
exec bash packaging/build_release_linux.sh "$@"
