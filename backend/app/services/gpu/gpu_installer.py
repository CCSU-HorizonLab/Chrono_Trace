import os
import sys
import subprocess
import threading
import logging
import re
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class GpuInstallerService:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(GpuInstallerService, cls).__new__(cls)
                cls._instance._init()
        return cls._instance

    def _init(self):
        self.status = "idle" # idle, downloading, installing, completed, failed
        self.progress_percent = 0.0
        self.message = ""
        self.error = None
        self._thread = None

    @staticmethod
    def has_nvidia_gpu() -> bool:
        """检测系统是否存在 NVIDIA GPU"""
        try:
            # 使用 creationflags=subprocess.CREATE_NO_WINDOW 隐藏控制台窗口
            flags = 0
            if sys.platform == "win32":
                flags = subprocess.CREATE_NO_WINDOW
            
            result = subprocess.run(
                ["nvidia-smi"], 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                creationflags=flags
            )
            if result.returncode == 0 and "NVIDIA" in result.stdout:
                return True
        except Exception:
            pass
            
        # 另一种方法 (Windows wmi)
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
        
    def start_install(self) -> Dict[str, Any]:
        """开始异步安装 GPU 环境"""
        with self._lock:
            if self.status in ["downloading", "installing"]:
                return {"ok": False, "error": "安装任务正在进行中，请稍候"}
                
            self.status = "downloading"
            self.progress_percent = 0.0
            self.message = "正在准备安装环境..."
            self.error = None
            
            self._thread = threading.Thread(target=self._run_install, daemon=True)
            self._thread.start()
            
            return {"ok": True, "message": "已开始安装"}
            
    def get_progress(self) -> Dict[str, Any]:
        """获取安装进度"""
        return {
            "ok": True,
            "status": self.status,
            "progress_percent": self.progress_percent,
            "message": self.message,
            "error": self.error
        }
        
    def _run_install(self):
        try:
            # 定义安装命令
            cmd = [
                sys.executable, "-m", "pip", "install", 
                "torch", "torchvision", "torchaudio", 
                "--index-url", "https://download.pytorch.org/whl/cu121",
                "--progress-bar", "off"
            ]
            
            self.message = "正在启动下载 (PyTorch 体积较大，可能需要几分钟的时间)..."
            logger.info(f"GPU Installer starting with cmd: {' '.join(cmd)}")
            
            flags = 0
            if sys.platform == "win32":
                flags = subprocess.CREATE_NO_WINDOW
                
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, # 合并stderr到stdout以便读取
                text=True,
                creationflags=flags,
                encoding="utf-8",
                errors="replace",
                bufsize=1 # line buffered
            )
            
            # 解析 pip 进度
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                    
                line = line.strip()
                if not line:
                    continue
                    
                logger.debug(f"[GPU Install] {line}")
                    
                if "Downloading" in line or "Collecting" in line:
                    self.status = "downloading"
                    # 这里截断过长的 pip 输出避免前端闪烁
                    self.message = line if len(line) < 80 else line[:80] + "..."
                elif "Installing collected packages" in line:
                    self.status = "installing"
                    self.message = "环境依赖下载完成，正在安装..."
                    self.progress_percent = 90.0
                elif "Successfully installed" in line:
                    self.message = "环境依赖安装完成！"
                    self.progress_percent = 100.0
                else:
                    match = re.search(r'(\d+)%', line)
                    if match:
                        val = float(match.group(1))
                        # 下载阶段进度映射到 0~80%
                        if self.status == "downloading":
                            self.progress_percent = min(80.0, val * 0.8)
                    else:
                        if len(line) < 80 and not line.startswith("│") and not line.startswith("━"):
                            self.message = line
                            
            if process.returncode == 0:
                self.status = "completed"
                self.progress_percent = 100.0
                self.message = "安装成功！请重启应用程序以启用 GPU 加速。"
                logger.info("GPU environment installed successfully.")
            else:
                self.status = "failed"
                self.error = f"安装失败 (退出码 {process.returncode})，原因: {self.message}"
                logger.error(self.error)
                
        except Exception as e:
            logger.error(f"安装 GPU 环境异常: {e}")
            self.status = "failed"
            self.error = str(e)
            self.message = "安装过程中出现系统错误"
