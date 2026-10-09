"""GPU 加速状态检测——从 bridge.py 拆出（步骤 3 mixin）。

torch 时代的「运行时下载 CUDA PyTorch overlay」安装链路已随 ONNX/
DirectML 单后端移除：onnxruntime-directml 免 CUDA 免 torch，有卡自动
走 DML(Windows)/CUDA(Linux N 卡)、无卡回退 CPU，安装包单变体通吃——
本 Mixin 只剩状态检测。
"""
from __future__ import annotations

import logging
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)


def _probe_nvidia_gpu() -> Tuple[Optional[str], int]:
    """nvidia-smi 探测显卡名与显存（MB）；无卡/无命令返回 (None, 0)。"""
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
            parts = [p.strip() for p in proc.stdout.strip().splitlines()[0].split(",")]
            name = parts[0] or None
            mem = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            return name, mem
    except Exception:
        pass
    return None, 0


class GpuApiMixin:
    """GPU 加速状态检测（ONNX providers 为唯一真通道）"""

    def check_gpu_status(self) -> dict[str, Any]:
        """检测 GPU 加速可用性：DML(Windows 免 CUDA) / CUDA(Linux N 卡) → CPU 回退。"""
        try:
            from ...runtime_overrides import get_build_variant

            onnx_version = ""
            onnx_providers: list[str] = []
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

            gpu_name, gpu_memory_total_mb = _probe_nvidia_gpu()

            return {
                "ok": True,
                "cuda_available": gpu_available,
                "gpu_available": gpu_available,
                "has_nvidia_gpu": gpu_name is not None,
                "gpu_name": gpu_name,
                # torch_version 为历史字段名，前端沿用——实际承载 ONNX 版本
                "torch_version": f"ONNX Runtime {onnx_version}".strip() if onnx_version else "ONNX Runtime",
                "onnx_version": onnx_version or "已就绪",
                "accelerator_label": accelerator_label,
                "cuda_version": "DirectML" if dml_available else ("CUDA" if onnx_cuda_available else None),
                "gpu_memory_total_mb": gpu_memory_total_mb,
                "gpu_memory_free_mb": 0,
                "build_variant": get_build_variant(),
                "onnx_providers": onnx_providers,
                "directml_available": dml_available,
                "onnx_cuda_available": onnx_cuda_available,
            }
        except Exception as e:
            logger.error(f"[Bridge] GPU 检测失败: {e}")
            try:
                from ...runtime_overrides import get_build_variant

                build_variant = get_build_variant()
            except Exception:
                build_variant = "dev"
            return {
                "ok": False,
                "cuda_available": False,
                "has_nvidia_gpu": False,
                "gpu_name": None,
                "torch_version": "unknown",
                "cuda_version": None,
                "gpu_memory_total_mb": 0,
                "gpu_memory_free_mb": 0,
                "build_variant": build_variant,
                "error": str(e),
            }
