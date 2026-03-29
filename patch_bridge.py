import sys
import re

file_path = 'd:/时痕/Chrono_Trace/backend/app/webview/bridge.py'
with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

out_lines = []
skip = False
for i, line in enumerate(lines):
    if 'def check_gpu_status(self) -> dict[str, Any]:' in line:
        out_lines.append(line)
        out_lines.append('        \"\"\"检测 GPU 加速可用性。\"\"\"\n')
        out_lines.append('        try:\n')
        out_lines.append('            import torch\n')
        out_lines.append('            from ..services.gpu.gpu_installer import GpuInstallerService\n\n')
        out_lines.append('            result = {\n')
        out_lines.append('                \"ok\": True,\n')
        out_lines.append('                \"cuda_available\": torch.cuda.is_available(),\n')
        out_lines.append('                \"has_nvidia_gpu\": GpuInstallerService.has_nvidia_gpu(),\n')
        out_lines.append('                \"gpu_name\": None,\n')
        out_lines.append('                \"torch_version\": torch.__version__,\n')
        out_lines.append('                \"cuda_version\": None,\n')
        out_lines.append('                \"gpu_memory_total_mb\": 0,\n')
        out_lines.append('                \"gpu_memory_free_mb\": 0,\n')
        out_lines.append('            }\n\n')
        out_lines.append('            if result[\"cuda_available\"]:\n')
        out_lines.append('                result[\"gpu_name\"] = torch.cuda.get_device_name(0)\n')
        out_lines.append('                result[\"cuda_version\"] = torch.version.cuda\n\n')
        out_lines.append('                mem_total = torch.cuda.get_device_properties(0).total_memory\n')
        out_lines.append('                try:\n')
        out_lines.append('                    mem_free, mem_total_runtime = torch.cuda.mem_get_info(0)\n')
        out_lines.append('                    result[\"gpu_memory_total_mb\"] = int(mem_total_runtime / 1024 / 1024)\n')
        out_lines.append('                    result[\"gpu_memory_free_mb\"] = int(mem_free / 1024 / 1024)\n')
        out_lines.append('                except Exception:\n')
        out_lines.append('                    mem_free = mem_total - torch.cuda.memory_allocated(0)\n')
        out_lines.append('                    result[\"gpu_memory_total_mb\"] = int(mem_total / 1024 / 1024)\n')
        out_lines.append('                    result[\"gpu_memory_free_mb\"] = int(mem_free / 1024 / 1024)\n\n')
        out_lines.append('            return result\n\n')
        out_lines.append('        except Exception as e:\n')
        out_lines.append('            logger.error(f\"[Bridge] GPU 检测失败: {e}\")\n')
        out_lines.append('            from ..services.gpu.gpu_installer import GpuInstallerService\n')
        out_lines.append('            return {\n')
        out_lines.append('                \"ok\": False,\n')
        out_lines.append('                \"cuda_available\": False,\n')
        out_lines.append('                \"has_nvidia_gpu\": getattr(GpuInstallerService, \"has_nvidia_gpu\", lambda: False)(),\n')
        out_lines.append('                \"gpu_name\": None,\n')
        out_lines.append('                \"torch_version\": \"unknown\",\n')
        out_lines.append('                \"cuda_version\": None,\n')
        out_lines.append('                \"gpu_memory_total_mb\": 0,\n')
        out_lines.append('                \"gpu_memory_free_mb\": 0,\n')
        out_lines.append('                \"error\": str(e)\n')
        out_lines.append('            }\n\n')
        out_lines.append('    def start_gpu_install(self) -> dict[str, Any]:\n')
        out_lines.append('        \"\"\"开始异步安装 GPU 环境\"\"\"\n')
        out_lines.append('        try:\n')
        out_lines.append('            from ..services.gpu.gpu_installer import GpuInstallerService\n')
        out_lines.append('            service = GpuInstallerService()\n')
        out_lines.append('            return service.start_install()\n')
        out_lines.append('        except Exception as e:\n')
        out_lines.append('            logger.error(f\"[Bridge] 开始安装 GPU 环境失败: {e}\")\n')
        out_lines.append('            return {\"ok\": False, \"error\": str(e)}\n\n')
        out_lines.append('    def get_gpu_install_progress(self) -> dict[str, Any]:\n')
        out_lines.append('        \"\"\"获取 GPU 环境安装进度\"\"\"\n')
        out_lines.append('        try:\n')
        out_lines.append('            from ..services.gpu.gpu_installer import GpuInstallerService\n')
        out_lines.append('            service = GpuInstallerService()\n')
        out_lines.append('            return service.get_progress()\n')
        out_lines.append('        except Exception as e:\n')
        out_lines.append('            logger.error(f\"[Bridge] 获取 GPU 环境安装进度失败: {e}\")\n')
        out_lines.append('            return {\"ok\": False, \"error\": str(e)}\n\n')
        
        skip = True
        continue
        
    if skip and 'def check_analysis_model_status' in line:
        skip = False
        
    if not skip:
        out_lines.append(line)

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(out_lines)

print('Success')
