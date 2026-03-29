import re

file_path = 'd:/时痕/Chrono_Trace/frontend/src/views/Settings.vue'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Patch 1: The UI
target_ui = '''            <div v-else class="gpu-status-detail">
              <div class="gpu-status-badge unavailable">❌ GPU 不可用</div>
              <div class="gpu-status-row"><span class="gpu-label">PyTorch</span><span class="gpu-value">{{ gpuInfo.torch_version || '未知' }}</span></div>
            </div>'''

rep_ui = '''            <div v-else class="gpu-status-detail">
              <div class="gpu-status-badge unavailable">❌ GPU 不可用</div>
              <div class="gpu-status-row"><span class="gpu-label">PyTorch</span><span class="gpu-value">{{ gpuInfo.torch_version || '未知' }}</span></div>
              <div v-if="gpuInfo.has_nvidia_gpu && !gpuInfo.cuda_available" class="gpu-installer-box" style="margin-top: 12px; padding: 12px; background: rgba(255,152,0,0.1); border: 1px solid rgba(255,152,0,0.3); border-radius: 8px;">
                <p style="margin: 0 0 8px 0; font-size: 13px; color: #d87c00;">
                  ✨ 检测到系统包含 NVIDIA GPU 硬件，但缺少支持 CUDA 的环境依赖导致无法加速。
                </p>
                <div v-if="installStatus === 'idle'">
                  <CtButton style="font-size: 13px; margin-top: 5px; width: 100%; border: 1px solid #d87c00;" @click.prevent="startGpuInstall">⚡一键配置支持 CUDA 的 GPU 环境</CtButton>
                </div>
                <div v-else>
                  <div style="font-size: 12px; margin-bottom: 4px; color: var(--ct-text-secondary);">
                    状态: {{ installStatus }} ({{ installProgress.toFixed(1) }}%)
                  </div>
                  <div style="width: 100%; height: 6px; background: var(--ct-bg-tertiary); border-radius: 3px; overflow: hidden; margin-bottom: 8px;">
                    <div :style="{ width: installProgress + '%', height: '100%', background: 'var(--ct-color-primary)', transition: 'width 0.3s ease' }"></div>
                  </div>
                  <div style="font-size: 11px; color: var(--ct-text-tertiary); font-family: monospace; background: rgba(0,0,0,0.05); padding: 4px; border-radius: 4px;">
                    {{ installMessage }}
                  </div>
                  <div v-if="installError" style="color: red; font-size: 12px; margin-top: 4px;">{{ installError }}</div>
                </div>
              </div>
            </div>'''

content = content.replace(target_ui, rep_ui)

# Patch 2: gpuInfo dict
target_gpu_info = '''const gpuInfo = reactive<{
  cuda_available: boolean
  gpu_name: string | null
  torch_version: string
  cuda_version: string | null
  gpu_memory_total_mb: number
  gpu_memory_free_mb: number
}>({
  cuda_available: false,
  gpu_name: null,
  torch_version: 'unknown',
  cuda_version: null,
  gpu_memory_total_mb: 0,
  gpu_memory_free_mb: 0,
})'''

rep_gpu_info = '''const gpuInfo = reactive<{
  cuda_available: boolean
  has_nvidia_gpu: boolean
  gpu_name: string | null
  torch_version: string
  cuda_version: string | null
  gpu_memory_total_mb: number
  gpu_memory_free_mb: number
}>({
  cuda_available: false,
  has_nvidia_gpu: false,
  gpu_name: null,
  torch_version: 'unknown',
  cuda_version: null,
  gpu_memory_total_mb: 0,
  gpu_memory_free_mb: 0,
})

const installStatus = ref('idle')
const installProgress = ref(0)
const installMessage = ref('')
const installError = ref('')
let installTimer: number | null = null

async function startGpuInstall() {
  try {
    installStatus.value = 'starting...'
    installProgress.value = 0
    installMessage.value = '正在请求安装...'
    installError.value = ''
    
    await bridgeReady()
    const res = await api.start_gpu_install()
    if (!res.ok) {
      installError.value = res.error || '请求失败'
      installStatus.value = 'idle'
      return
    }
    
    installTimer = window.setInterval(pollGpuInstall, 1000)
  } catch (e: any) {
    installError.value = e.message || '系统异常'
    installStatus.value = 'idle'
  }
}

async function pollGpuInstall() {
  try {
    const res = await api.get_gpu_install_progress()
    if (res.ok) {
      installStatus.value = res.status
      installProgress.value = res.progress_percent || 0
      installMessage.value = res.message || ''
      if (res.status === 'completed' || res.status === 'failed') {
        if (installTimer) clearInterval(installTimer)
        if (res.status === 'completed') {
          showDialog('GPU 环境安装成功！为保证生效，强烈建议重启应用程序。')
          loadGpuInfo()
        } else {
          installError.value = res.error || '安装失败未知原因'
        }
      }
    }
  } catch (e) {
    console.error('Polling error', e)
  }
}
'''
if target_gpu_info in content:
    content = content.replace(target_gpu_info, rep_gpu_info)

# Patch 3: loadGpuInfo logic
target_load = '''      gpuInfo.cuda_available = Boolean(status.cuda_available)'''
rep_load = '''      gpuInfo.cuda_available = Boolean(status.cuda_available)
      gpuInfo.has_nvidia_gpu = Boolean(status.has_nvidia_gpu)'''
if target_load in content:
    content = content.replace(target_load, rep_load, 1)

# Patch 4: Cleanup Interval
if 'if (installTimer) clearInterval(installTimer)' not in content:
    content = content.replace('onUnmounted(() => {\n  document.removeEventListener', 'onUnmounted(() => {\n  if (installTimer) clearInterval(installTimer)\n  document.removeEventListener')

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Success patched Settings.vue")
