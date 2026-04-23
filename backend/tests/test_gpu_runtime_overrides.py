import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))


from app import runtime_overrides


def test_activate_gpu_overlay_requires_install_state_file():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        site_packages = root / "site-packages"
        site_packages.mkdir(parents=True, exist_ok=True)
        (site_packages / "torch").mkdir()
        install_state = root / "install_state.json"

        with patch.object(runtime_overrides, "GPU_RUNTIME_ROOT_PATH", root), \
             patch.object(runtime_overrides, "GPU_SITE_PACKAGES_PATH", site_packages), \
             patch.object(runtime_overrides, "GPU_INSTALL_STATE_PATH", install_state):
            assert runtime_overrides.activate_gpu_overlay_path() is False


def test_activate_gpu_overlay_inserts_overlay_site_packages_first():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        site_packages = root / "site-packages"
        site_packages.mkdir(parents=True, exist_ok=True)
        (site_packages / "torch").mkdir()
        install_state = root / "install_state.json"
        install_state.write_text('{"active": true}', encoding="utf-8")

        original_sys_path = list(sys.path)
        try:
            with patch.object(runtime_overrides, "GPU_RUNTIME_ROOT_PATH", root), \
                 patch.object(runtime_overrides, "GPU_SITE_PACKAGES_PATH", site_packages), \
                 patch.object(runtime_overrides, "GPU_INSTALL_STATE_PATH", install_state):
                assert runtime_overrides.activate_gpu_overlay_path() is True
                assert sys.path[0] == str(site_packages)
        finally:
            sys.path[:] = original_sys_path
