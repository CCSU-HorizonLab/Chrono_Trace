import re

file_path = 'd:/时痕/Chrono_Trace/frontend/src/views/Analytics.vue'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Patch Analytics.vue logic
target_start_global = '''                try {
                const gpuStatus = await api.check_gpu_status()
                if (gpuStatus.ok && gpuStatus.cuda_available) {'''

rep_start_global = '''                try {
                const gpuStatus = await api.check_gpu_status()
                if (gpuStatus.ok && gpuStatus.cuda_available) {'''

# Actually I just need to replace the `else { await showDialog({ title: 'CPU 模式'...`
target_else = '''                } else {
                    await showDialog({
                        title: 'CPU 模式',
                        message:
                            'GPU 加速不可用，将使用 CPU 模式进行分析。\\n' +
                            '如需启用 GPU，请安装支持 CUDA 的 PyTorch 版本。\\n\\n' +
                            '💡 此选项可随时在「通用设置」页面修改。'
                    })
                    await api.set_settings({ analysis_device_mode: 'cpu' })
                    applyAnalysisDeviceMode('cpu')
                }'''

rep_else = '''                } else if (gpuStatus.ok && gpuStatus.has_nvidia_gpu) {
                    const doInstall = await showConfirm({
                        title: '检测到 GPU 硬件',
                        message:
                            '检测到您的计算机配备了 NVIDIA GPU，但当前未安装支持 CUDA 的环境依赖，导致无法启用 GPU 加速。\\n\\n' +
                            '是否现在进行【一键配置】？这将自动下载和安装所需的 PyTorch 环境（通常需要几分钟，会在后台执行）。'
                    })
                    if (doInstall) {
                        try {
                            const installRes = await api.start_gpu_install()
                            if (installRes.ok) {
                                await showDialog({
                                    title: '开始配置',
                                    message: 'GPU 环境配置已在后台启动，您可以随时前往「通用设置」页面查看实时安装进度。\\n本次分析将暂时使用 CPU 模式进行，安装完成后下次可使用 GPU 加速。'
                                })
                            } else {
                                await showDialog({ title: '安装启动失败', message: installRes.error || '未知错误' })
                            }
                        } catch(e) {}
                    } else {
                        await showDialog({
                            title: 'CPU 模式',
                            message: '将使用 CPU 模式进行分析。'
                        })
                    }
                    await api.set_settings({ analysis_device_mode: 'cpu' })
                    applyAnalysisDeviceMode('cpu')
                } else {
                    await showDialog({
                        title: 'CPU 模式',
                        message:
                            'GPU 加速不可用，将使用 CPU 模式进行分析。\\n' +
                            '如需启用 GPU，请安装支持 CUDA 的 PyTorch 版本。\\n\\n' +
                            '💡 此选项可随时在「通用设置」页面修改。'
                    })
                    await api.set_settings({ analysis_device_mode: 'cpu' })
                    applyAnalysisDeviceMode('cpu')
                }'''

if target_else in content:
    content = content.replace(target_else, rep_else)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Success patched Analytics.vue")
else:
    print("Failed to find target in Analytics.vue")
