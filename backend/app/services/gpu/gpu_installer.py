from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from ...runtime_overrides import (
    GPU_EMBEDDED_PYTHON_DIR_PATH,
    GPU_INSTALL_STATE_PATH,
    GPU_RUNTIME_ROOT_PATH,
    GPU_SITE_PACKAGES_PATH,
    clear_gpu_install_state,
    get_build_variant,
    get_gpu_install_state,
    save_gpu_install_state,
)

logger = logging.getLogger(__name__)


class GpuInstallerService:
    _instance = None
    _lock = threading.Lock()
    _default_torch_version = "2.5.1"
    _cuda_channel = "cu121"

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(GpuInstallerService, cls).__new__(cls)
                cls._instance._init()
        return cls._instance

    def _init(self):
        self.status = "idle"
        self.progress_percent = 0.0
        self.message = ""
        self.error = None
        self._thread = None

    @staticmethod
    def has_nvidia_gpu() -> bool:
        try:
            flags = 0
            if sys.platform == "win32":
                flags = subprocess.CREATE_NO_WINDOW

            result = subprocess.run(
                ["nvidia-smi"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=flags,
            )
            if result.returncode == 0 and "NVIDIA" in result.stdout:
                return True
        except Exception:
            pass

        if sys.platform == "win32":
            try:
                import wmi

                w = wmi.WMI()
                for controller in w.Win32_VideoController():
                    if "NVIDIA" in controller.Name:
                        return True
            except Exception:
                pass

        return False

    def start_install(self) -> dict[str, Any]:
        with self._lock:
            if self.status in {"downloading_runtime", "bootstrapping_pip", "installing_torch", "validating"}:
                return {"ok": False, "error": "安装任务正在进行中，请稍候"}

            self.status = "starting"
            self.progress_percent = 0.0
            self.message = "正在准备 GPU 运行时..."
            self.error = None

            self._thread = threading.Thread(target=self._run_install, daemon=True)
            self._thread.start()
            return {
                "ok": True,
                "message": "已开始安装",
                "target_dir": str(GPU_RUNTIME_ROOT_PATH),
                "build_variant": get_build_variant(),
            }

    def get_progress(self) -> dict[str, Any]:
        state = get_gpu_install_state()
        return {
            "ok": True,
            "status": self.status,
            "progress_percent": self.progress_percent,
            "message": self.message,
            "error": self.error,
            "target_dir": str(GPU_RUNTIME_ROOT_PATH),
            "overlay_site_packages": str(GPU_SITE_PACKAGES_PATH),
            "installed_torch_version": state.get("torch_version"),
            "installed_cuda_version": state.get("cuda_version"),
            "build_variant": get_build_variant(),
        }

    def _set_status(self, status: str, progress_percent: float, message: str):
        with self._lock:
            self.status = status
            self.progress_percent = max(0.0, min(100.0, float(progress_percent)))
            self.message = message

    def _python_version(self) -> str:
        return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    def _embedded_python_url(self) -> str:
        version = self._python_version()
        return f"https://www.python.org/ftp/python/{version}/python-{version}-embed-amd64.zip"

    def _get_pip_url(self) -> str:
        return "https://bootstrap.pypa.io/get-pip.py"

    def _embedded_python_exe(self) -> Path:
        return GPU_EMBEDDED_PYTHON_DIR_PATH / "python.exe"

    def _runtime_temp_dir(self) -> Path:
        return GPU_RUNTIME_ROOT_PATH / "temp"

    def _runtime_download_dir(self) -> Path:
        return GPU_RUNTIME_ROOT_PATH / "downloads"

    def _current_torch_base_version(self) -> str:
        try:
            import torch

            current = str(torch.__version__).split("+", 1)[0]
            if current == self._default_torch_version:
                return current
        except Exception:
            pass
        return self._default_torch_version

    def _download_file(self, url: str, target_path: Path, progress_start: float, progress_end: float, label: str):
        target_path.parent.mkdir(parents=True, exist_ok=True)
        self._set_status("downloading_runtime", progress_start, f"正在下载 {label}...")

        with urllib.request.urlopen(url) as response, target_path.open("wb") as output:
            content_length = response.headers.get("Content-Length")
            total = int(content_length) if content_length and content_length.isdigit() else 0
            downloaded = 0
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                output.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    ratio = downloaded / total
                    progress = progress_start + (progress_end - progress_start) * ratio
                    self._set_status("downloading_runtime", progress, f"正在下载 {label}...")

        self._set_status("downloading_runtime", progress_end, f"{label} 下载完成")

    def _ensure_embedded_python(self):
        python_exe = self._embedded_python_exe()
        if python_exe.exists():
            return python_exe

        download_dir = self._runtime_download_dir()
        temp_dir = self._runtime_temp_dir()
        archive_path = download_dir / f"python-{self._python_version()}-embed-amd64.zip"
        extract_dir = temp_dir / "python-embed-extract"

        self._download_file(
            self._embedded_python_url(),
            archive_path,
            5.0,
            30.0,
            "Python 运行时",
        )

        if extract_dir.exists():
            shutil.rmtree(extract_dir, ignore_errors=True)
        extract_dir.mkdir(parents=True, exist_ok=True)

        self._set_status("downloading_runtime", 32.0, "正在解压 Python 运行时...")
        with zipfile.ZipFile(archive_path, "r") as archive:
            archive.extractall(extract_dir)

        if GPU_EMBEDDED_PYTHON_DIR_PATH.exists():
            shutil.rmtree(GPU_EMBEDDED_PYTHON_DIR_PATH, ignore_errors=True)
        shutil.move(str(extract_dir), str(GPU_EMBEDDED_PYTHON_DIR_PATH))
        self._configure_embedded_python()
        self._set_status("downloading_runtime", 40.0, "Python 运行时已就绪")
        return python_exe

    def _configure_embedded_python(self):
        GPU_SITE_PACKAGES_PATH.mkdir(parents=True, exist_ok=True)
        pth_files = sorted(GPU_EMBEDDED_PYTHON_DIR_PATH.glob("python*._pth"))
        if not pth_files:
            raise RuntimeError("嵌入式 Python 缺少 python*._pth 配置文件")

        pth_file = pth_files[0]
        lines = pth_file.read_text(encoding="utf-8").splitlines()
        normalized = []
        has_site_packages = False
        has_import_site = False

        for line in lines:
            stripped = line.strip()
            if stripped == "import site" or stripped == "#import site":
                normalized.append("import site")
                has_import_site = True
                continue
            if stripped.replace("/", "\\") == "Lib\\site-packages":
                normalized.append("Lib\\site-packages")
                has_site_packages = True
                continue
            normalized.append(line)

        if not has_site_packages:
            normalized.append("Lib\\site-packages")
        if not has_import_site:
            normalized.append("import site")

        pth_file.write_text("\n".join(normalized) + "\n", encoding="utf-8")
        (GPU_EMBEDDED_PYTHON_DIR_PATH / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)

    def _run_command(self, cmd: list[str], status: str, progress_start: float, progress_end: float, start_message: str):
        self._set_status(status, progress_start, start_message)
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.CREATE_NO_WINDOW

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=flags,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        last_message = start_message
        for raw_line in iter(process.stdout.readline, ""):
            line = raw_line.strip()
            if not line:
                continue
            logger.info("[GPU Install] %s", line)
            if len(line) <= 180:
                last_message = line
                self._set_status(status, progress_end - 2.0, line)

        process.wait()
        if process.returncode != 0:
            raise RuntimeError(last_message or f"命令执行失败: {' '.join(cmd)}")

        self._set_status(status, progress_end, last_message)

    def _ensure_pip(self, python_exe: Path):
        try:
            self._run_command(
                [str(python_exe), "-m", "pip", "--version"],
                "bootstrapping_pip",
                42.0,
                44.0,
                "正在检查 pip...",
            )
            return
        except Exception:
            pass

        get_pip_path = self._runtime_download_dir() / "get-pip.py"
        self._download_file(self._get_pip_url(), get_pip_path, 44.0, 50.0, "pip 引导脚本")
        self._run_command(
            [str(python_exe), str(get_pip_path), "--no-warn-script-location"],
            "bootstrapping_pip",
            50.0,
            60.0,
            "正在初始化 pip...",
        )

    def _clear_previous_overlay_packages(self):
        GPU_SITE_PACKAGES_PATH.mkdir(parents=True, exist_ok=True)
        cleanup_prefixes = (
            "torch",
            "nvidia",
            "triton",
            "fbgemm",
            "functorch",
        )
        for child in GPU_SITE_PACKAGES_PATH.iterdir():
            name = child.name.lower()
            if not name.startswith(cleanup_prefixes):
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)

    def _install_gpu_torch(self, python_exe: Path):
        self._clear_previous_overlay_packages()
        torch_version = self._current_torch_base_version()
        cmd = [
            str(python_exe),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-warn-script-location",
            "--upgrade",
            "--force-reinstall",
            "--no-cache-dir",
            "--target",
            str(GPU_SITE_PACKAGES_PATH),
            "--index-url",
            f"https://download.pytorch.org/whl/{self._cuda_channel}",
            f"torch=={torch_version}",
        ]
        self._run_command(
            cmd,
            "installing_torch",
            62.0,
            90.0,
            "正在安装支持 CUDA 的 PyTorch 运行时...",
        )

    def _validate_overlay(self, python_exe: Path):
        validation_script = (
            "import json, sys; "
            f"sys.path.insert(0, {str(GPU_SITE_PACKAGES_PATH)!r}); "
            "import torch; "
            "print(json.dumps({"
            "'torch_version': torch.__version__, "
            "'cuda_version': torch.version.cuda, "
            "'cuda_available': bool(torch.cuda.is_available())"
            "}, ensure_ascii=False))"
        )

        self._set_status("validating", 92.0, "正在校验 GPU 运行时...")
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.CREATE_NO_WINDOW

        result = subprocess.run(
            [str(python_exe), "-c", validation_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "GPU 运行时校验失败")

        payload = json.loads(result.stdout.strip())
        if not payload.get("cuda_version"):
            raise RuntimeError("下载到的 PyTorch 不是 CUDA 版本")

        save_gpu_install_state(
            {
                "active": True,
                "provider": "embedded-python-overlay",
                "python_version": self._python_version(),
                "torch_version": payload.get("torch_version"),
                "cuda_version": payload.get("cuda_version"),
                "cuda_available_at_install": bool(payload.get("cuda_available")),
                "overlay_site_packages": str(GPU_SITE_PACKAGES_PATH),
            }
        )
        self._set_status("validating", 98.0, "GPU 运行时校验通过")

    def _run_install(self):
        try:
            GPU_RUNTIME_ROOT_PATH.mkdir(parents=True, exist_ok=True)
            clear_gpu_install_state()
            python_exe = self._ensure_embedded_python()
            self._ensure_pip(python_exe)
            self._install_gpu_torch(python_exe)
            self._validate_overlay(python_exe)
            self._set_status("completed", 100.0, "GPU 环境已就绪，重启应用后即可生效")
            logger.info("GPU overlay runtime installed successfully: %s", GPU_INSTALL_STATE_PATH)
        except Exception as exc:
            logger.error("安装 GPU 环境异常: %s", exc, exc_info=True)
            self.status = "failed"
            self.error = str(exc)
            self.message = "GPU 环境安装失败"
