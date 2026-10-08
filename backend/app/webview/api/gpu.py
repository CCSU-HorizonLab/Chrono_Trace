"""GPU 检测与运行时安装——从 bridge.py 拆出（步骤 3 mixin）。

Bridge 继承此 Mixin，方法名不变、前端 API 面与测试零破坏。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class GpuApiMixin:
    """GPU 检测与运行时安装"""

    def check_gpu_status(self) -> dict[str, Any]:
        """检测 GPU 加速可用性（ONNX 为主通道：DML/CUDA providers；torch 可选）。"""
        try:
            from ...services.gpu.gpu_installer import GpuInstallerService
            from ...runtime_overrides import get_build_variant, get_gpu_install_state, has_gpu_overlay

            overlay_state = get_gpu_install_state()
            overlay_installed = has_gpu_overlay()

            torch_version = ""       # torch 已移出运行栈（字段保留兼容前端）
            cuda_version = None

            # ONNX providers 是 GPU 真通道（DirectML=Windows 免 CUDA / CUDA=Linux）
            onnx_providers: list[str] = []
            onnx_version = ""
            dml_available = False
            onnx_cuda_available = False
            try:
                import onnxruntime as ort

                onnx_version = getattr(ort, "__version__", "") or ""
                onnx_providers = list(ort.get_available_providers())
                dml_available = "DmlExecutionProvider" in onnx_providers
                onnx_cuda_available = "CUDAExecutionProvider" in onnx_providers
            except Exception:
                pass

            gpu_available = bool(dml_available or onnx_cuda_available)
            if dml_available:
                accelerator_label = "DirectML (Windows 原生 GPU 加速)"
            elif onnx_cuda_available:
                accelerator_label = "CUDA (NVIDIA GPU 加速)"
            else:
                accelerator_label = "CPU (ONNX 多核推理)"

            gpu_name = None
            gpu_memory_total_mb = 0
            try:
                import subprocess as _sp

                proc = _sp.run(
                    ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0),
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    first_line = proc.stdout.strip().splitlines()[0]
                    parts = [p.strip() for p in first_line.split(",")]
                    if parts:
                        gpu_name = parts[0]
                    if len(parts) > 1 and parts[1].isdigit():
                        gpu_memory_total_mb = int(parts[1])
            except Exception:
                pass

            build_variant = get_build_variant()
            result = {
                "ok": True,
                "cuda_available": gpu_available,
                "gpu_available": gpu_available,
                "has_nvidia_gpu": GpuInstallerService.has_nvidia_gpu(),
                "gpu_name": gpu_name,
                "torch_version": f"ONNX Runtime {onnx_version}".strip() if onnx_version else "ONNX Runtime",
                "onnx_version": onnx_version or "已就绪",
                "accelerator_label": accelerator_label,
                "cuda_version": "DirectML" if dml_available else ("CUDA" if onnx_cuda_available else None),
                "gpu_memory_total_mb": gpu_memory_total_mb,
                "gpu_memory_free_mb": 0,
                "build_variant": build_variant,
                "gpu_overlay_installed": overlay_installed,
                "gpu_overlay_torch_version": overlay_state.get("torch_version"),
                "gpu_overlay_cuda_version": overlay_state.get("cuda_version"),
                "restart_required": False,
                # ONNX 通道（阶段 B 起 GPU 主路径）
                "onnx_providers": onnx_providers,
                "directml_available": dml_available,
                "onnx_cuda_available": onnx_cuda_available,
            }
            return result

        except Exception as e:
            logger.error(f"[Bridge] GPU 检测失败: {e}")
            from ...services.gpu.gpu_installer import GpuInstallerService
            from ...runtime_overrides import get_build_variant, get_gpu_install_state, has_gpu_overlay

            overlay_state = get_gpu_install_state()
            build_variant = get_build_variant()
            return {
                "ok": False,
                "cuda_available": False,
                "has_nvidia_gpu": getattr(GpuInstallerService, "has_nvidia_gpu", lambda: False)(),
                "gpu_name": None,
                "torch_version": "unknown",
                "cuda_version": None,
                "gpu_memory_total_mb": 0,
                "gpu_memory_free_mb": 0,
                "build_variant": build_variant,
                "gpu_overlay_installed": has_gpu_overlay(),
                "gpu_overlay_torch_version": overlay_state.get("torch_version"),
                "gpu_overlay_cuda_version": overlay_state.get("cuda_version"),
                "restart_required": bool(build_variant != "dev" and has_gpu_overlay()),
                "error": str(e)
            }

    def start_gpu_install(self) -> dict[str, Any]:
        """开始异步安装 GPU 环境"""
        try:
            from ...services.gpu.gpu_installer import GpuInstallerService
            service = GpuInstallerService()
            return service.start_install()
        except Exception as e:
            logger.error(f"[Bridge] 开始安装 GPU 环境失败: {e}")
            return {"ok": False, "error": str(e)}

    def get_gpu_install_progress(self) -> dict[str, Any]:
        """获取 GPU 环境安装进度"""
        try:
            from ...services.gpu.gpu_installer import GpuInstallerService
            service = GpuInstallerService()
            return service.get_progress()
        except Exception as e:
            logger.error(f"[Bridge] 获取 GPU 环境安装进度失败: {e}")
            return {"ok": False, "error": str(e)}

