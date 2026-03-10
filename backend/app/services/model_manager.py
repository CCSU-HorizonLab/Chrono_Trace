"""模型版本管理器

负责管理本地模型的版本检测与云端更新：
- 启动时纯本地加载模型（零延迟）
- 后台线程检查云端 HuggingFace 仓库是否有更新
- 有更新则下载到临时目录，验证后替换本地模型
- 下次启动时加载新版本

设计目标：
- 彻底消除运行时的远程 HuggingFace 拉取
- 避免 accelerate 的 meta tensor 延迟初始化在多线程下的调度冲突
"""

import os
import json
import shutil
import logging
import threading
from pathlib import Path
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# 版本信息文件名
VERSION_FILE = "model_version.json"

# 全局追踪已经启动更新检查的 repo，避免不同实例重复发请求
_global_update_started = set()


class ModelManager:
    """模型版本管理器
    
    管理本地模型文件，并在后台检查云端更新。
    
    使用方式:
        manager = ModelManager(
            model_dir="path/to/local/model",
            repo_id="tingting11/chrono-trace-sentiment",
            mirror_endpoint="https://hf-mirror.com"  # 可选
        )
        
        # 检查本地模型是否可用
        if manager.ensure_model_exists():
            model = AutoModel.from_pretrained(manager.model_dir)
        
        # 后台检查更新（不阻塞）
        manager.check_and_update_async()
    """
    
    def __init__(
        self,
        model_dir: str,
        repo_id: str,
        mirror_endpoint: Optional[str] = "https://hf-mirror.com"
    ):
        """初始化模型管理器
        
        Args:
            model_dir: 本地模型目录的绝对路径
            repo_id: HuggingFace 仓库 ID（如 'tingting11/chrono-trace-sentiment'）
            mirror_endpoint: HuggingFace 镜像站地址（中国大陆推荐）
        """
        self.model_dir = Path(model_dir)
        self.repo_id = repo_id
        self.mirror_endpoint = mirror_endpoint
        self._update_thread: Optional[threading.Thread] = None
        self._updating = False
    
    def ensure_model_exists(self) -> bool:
        """检查本地模型是否存在且可用
        
        Returns:
            True 表示本地模型可用，False 表示不可用
        """
        # 检查模型目录和关键文件是否存在
        config_file = self.model_dir / "config.json"
        if not self.model_dir.exists() or not config_file.exists():
            logger.warning(f"[模型管理] 本地模型不存在: {self.model_dir}")
            logger.warning(f"[模型管理] 请先运行训练脚本或手动放置模型文件")
            return False
        
        # 检查是否有权重文件（safetensors 或 bin 格式）
        has_weights = any(
            self.model_dir.glob("*.safetensors")
        ) or any(
            self.model_dir.glob("*.bin")
        )
        
        if not has_weights:
            logger.warning(f"[模型管理] 本地模型目录缺少权重文件: {self.model_dir}")
            return False
        
        logger.debug(f"[模型管理] 本地模型可用: {self.model_dir}")
        return True
    
    def get_local_version(self) -> Optional[str]:
        """获取本地模型的版本信息（commit SHA）
        
        Returns:
            版本字符串（commit SHA），或 None 表示未记录版本
        """
        version_file = self.model_dir / VERSION_FILE
        if not version_file.exists():
            return None
        
        try:
            with open(version_file, "r", encoding="utf-8") as f:
                version_info = json.load(f)
            return version_info.get("commit_sha")
        except Exception as e:
            logger.error(f"[模型管理] 读取版本文件失败: {e}")
            return None
    
    def _save_local_version(self, commit_sha: str):
        """保存版本信息到本地
        
        Args:
            commit_sha: 模型的 commit SHA
        """
        version_file = self.model_dir / VERSION_FILE
        version_info = {
            "commit_sha": commit_sha,
            "repo_id": self.repo_id,
            "updated_at": datetime.now().isoformat(),
        }
        
        try:
            with open(version_file, "w", encoding="utf-8") as f:
                json.dump(version_info, f, ensure_ascii=False, indent=2)
            logger.debug(f"[模型管理] 版本信息已保存: {commit_sha[:8]}...")
        except Exception as e:
            logger.error(f"[模型管理] 保存版本文件失败: {e}")
    
    def check_and_update_async(self):
        """在后台线程中检查云端更新并下载
        
        不阻塞主线程。如果已有更新任务在运行，则跳过。
        更新完成后，新模型在下次启动时生效。
        """
        global _global_update_started
        if self._updating or self.repo_id in _global_update_started:
            logger.debug("[模型管理] 已有更新任务在运行，跳过")
            return
            
        _global_update_started.add(self.repo_id)
        
        self._update_thread = threading.Thread(
            target=self._check_and_update,
            name="ModelUpdateChecker",
            daemon=True  # 守护线程，主程序退出时自动结束
        )
        self._update_thread.start()
    
    def _check_and_update(self):
        """检查云端更新并下载（在后台线程中执行）"""
        self._updating = True
        try:
            self._do_check_and_update()
        except Exception as e:
            logger.error(f"[模型管理] 后台更新检查失败: {e}")
        finally:
            self._updating = False
            global _global_update_started
            if self.repo_id in _global_update_started:
                _global_update_started.remove(self.repo_id)
    
    def _do_check_and_update(self):
        """执行实际的更新检查和下载逻辑"""
        try:
            from huggingface_hub import model_info, snapshot_download
        except ImportError:
            logger.warning("[模型管理] huggingface_hub 未安装，跳过更新检查")
            return
        
        # 设置镜像站环境变量（仅在此线程内使用）
        old_endpoint = os.environ.get("HF_ENDPOINT")
        if self.mirror_endpoint:
            os.environ["HF_ENDPOINT"] = self.mirror_endpoint
        
        try:
            # 1. 获取云端最新版本信息
            logger.debug(f"[模型管理] 正在检查云端更新: {self.repo_id}")
            info = model_info(self.repo_id)
            remote_sha = info.sha
            
            if not remote_sha:
                logger.debug("[模型管理] 无法获取云端版本信息")
                return
            
            # 2. 与本地版本比较
            local_sha = self.get_local_version()
            
            if local_sha == remote_sha:
                logger.debug(f"[模型管理] 模型已是最新版本: {remote_sha[:8]}...")
                return
            
            if local_sha:
                logger.info(f"[模型管理] 发现新版本: {local_sha[:8]}... → {remote_sha[:8]}...")
            else:
                logger.info(f"[模型管理] 首次记录版本: {remote_sha[:8]}...")
                # 如果本地模型存在但没有版本记录，先记录当前版本
                if self.ensure_model_exists():
                    self._save_local_version(remote_sha)
                    return
            
            # 3. 下载新版本到临时目录
            temp_dir = self.model_dir.parent / f"{self.model_dir.name}_update_temp"
            logger.info(f"[模型管理] 正在下载新版本模型...")
            
            try:
                snapshot_download(
                    self.repo_id,
                    local_dir=str(temp_dir),
                    local_dir_use_symlinks=False,
                )
            except Exception as e:
                logger.error(f"[模型管理] 下载失败: {e}")
                # 清理临时目录
                if temp_dir.exists():
                    shutil.rmtree(temp_dir, ignore_errors=True)
                return
            
            # 4. 验证下载的模型
            temp_config = temp_dir / "config.json"
            if not temp_config.exists():
                logger.error("[模型管理] 下载的模型缺少 config.json，放弃更新")
                shutil.rmtree(temp_dir, ignore_errors=True)
                return
            
            # 5. 替换本地模型
            backup_dir = self.model_dir.parent / f"{self.model_dir.name}_backup"
            
            try:
                # 备份旧模型
                if self.model_dir.exists():
                    if backup_dir.exists():
                        shutil.rmtree(backup_dir, ignore_errors=True)
                    shutil.move(str(self.model_dir), str(backup_dir))
                
                # 移入新模型
                shutil.move(str(temp_dir), str(self.model_dir))
                
                # 保存版本信息
                self._save_local_version(remote_sha)
                
                logger.info(f"[模型管理] ✅ 模型已更新至 {remote_sha[:8]}...，下次启动生效")
                
                # 清理备份
                if backup_dir.exists():
                    shutil.rmtree(backup_dir, ignore_errors=True)
                    
            except Exception as e:
                logger.error(f"[模型管理] 替换模型失败: {e}")
                # 尝试恢复备份
                if backup_dir.exists() and not self.model_dir.exists():
                    shutil.move(str(backup_dir), str(self.model_dir))
                    logger.info("[模型管理] 已从备份恢复旧模型")
                # 清理临时目录
                if temp_dir.exists():
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    
        finally:
            # 恢复环境变量
            if old_endpoint is not None:
                os.environ["HF_ENDPOINT"] = old_endpoint
            elif "HF_ENDPOINT" in os.environ:
                del os.environ["HF_ENDPOINT"]
