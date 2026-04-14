<template>
  <section class="home-page">
    <div class="home-section">
      <h2 class="section-title ct-page-title">
        <div style="display:flex;align-items:center; gap: 8px;">
          <span class="title-icon">⚙️</span>
          <span class="gradient-text">通用设置</span>
        </div>
        <div class="auto-save-status glass-pill" style="margin-left: auto;">
          <span v-if="saving" class="saving">
            <span class="spinner"></span> 保存中...
          </span>
          <span v-else-if="lastSaveTime" class="saved">✅ 已保存 {{ lastSaveTime }}</span>
          <span v-else class="idle">✨ 自动保存已启用</span>
        </div>
      </h2>

      <div class="grid">
      <!-- 模型配置（合并原通用配置 + LLM 模型管理） -->
      <CtCard title="🤖 模型配置">
        <div class="form">
          <div class="hint-box info">
            <p>💡 配置 LLM 模型后，AI 建议将使用大语言模型生成更智能的话术。支持远程 API（DeepSeek/OpenAI）和本地推理（Ollama/LM Studio）。</p>
          </div>

          <!-- 引擎固定为 LLM -->

          <!-- 模型列表 -->
          <div class="model-list">
            <div v-if="!llmModels.length" class="empty-models">
              暂无模型配置，点击下方按钮添加
            </div>
            <div v-for="m in llmModels" :key="m.id" class="model-card" :class="{ active: m.is_active }">
              <div class="model-header">
                <div class="model-info">
                  <span class="model-name">{{ m.name }}</span>
                  <span class="model-provider">{{ providerLabel(m.provider) }}</span>
                  <label class="ct-switch" title="点击切换激活状态">
                    <input type="checkbox" :checked="m.is_active" @click.stop @change="toggleModelActive(m)" />
                    <span class="slider"></span>
                    <span class="switch-label">{{ m.is_active ? '已激活' : '未激活' }}</span>
                  </label>
                </div>
                <div class="model-actions">
                  <button class="mini-btn" @click="editModel(m)">编辑</button>
                  <button class="mini-btn danger" @click="removeModel(m.id)">删除</button>
                </div>
              </div>
              <div class="model-detail">
                <span>模型: {{ m.model_id }}</span>
                <span>URL: {{ m.api_base_url }}</span>
                <span v-if="m.api_key_masked">Key: {{ m.api_key_masked }}</span>
              </div>
            </div>
          </div>

          <button class="add-model-btn dashed" @click.prevent="resetEditingModel(); showModelForm = true">
            <span class="add-icon">+</span> 添加新的模型配置
          </button>
        </div>
      </CtCard>

      <!-- 微信数据库路径配置 -->
      <CtCard title="微信数据库路径">
        <div class="form">
          <div class="hint-box info">
            <p>💡 <strong>提示:</strong>如果自动检测的微信路径不正确,可以在此手动指定数据库文件位置</p>
          </div>

          <label class="row">
            <div class="lab">数据库密钥</div>
            <CtField 
              v-model="form.wechat_db_key" 
              type="password"
              placeholder="输入64位hex密钥 (可保存以便下次使用)" 
            />
          </label>

          <label class="row">
            <div class="lab">使用自定义路径</div>
            <label class="ct-switch">
              <input v-model="form.wechat_use_custom_path" type="checkbox" />
              <span class="slider"></span>
            </label>
          </label>

          <template v-if="form.wechat_use_custom_path">
            <div class="row">
              <div class="lab">微信数据目录</div>
              <div class="path-input">
                <CtField 
                  v-model="form.wechat_data_dir" 
                  placeholder="例如: C:\Users\YourName\Documents\WeChat Files" 
                />
                <CtButton variant="ghost" :loading="scanning" @click.stop.prevent="selectWeChatDir">浏览并扫描</CtButton>
              </div>
            </div>

            <div class="row">
              <div class="lab">微信用户ID (wxid)</div>
              <CtField 
                v-model="form.wechat_user_wxid" 
                placeholder="例如: wxid_abc123def456 (浏览目录后自动填充)" 
              />
            </div>
          </template>
        </div>
      </CtCard>

      <CtCard title="🧰 杂项维护">
        <div class="form">
          <div class="hint-box info">
            <p>💡 首次导入微信数据时，联系人头像会自动同步。</p>
            <p style="margin-top: 8px;">这个入口只用于历史旧数据修复：重新扫描联系人库，把头像回填到已导入的联系人和会话，不会重新导入消息。</p>
          </div>

          <div class="maintenance-card">
            <div class="maintenance-copy">
              <div class="maintenance-title">补齐已导入联系人头像</div>
              <div class="maintenance-desc">适用于早期导入时还没有头像字段的历史数据。</div>
            </div>
            <CtButton
              :loading="avatarRefreshLoading"
              :disabled="!form.wechat_db_key.trim() || avatarRefreshLoading"
              @click.stop.prevent="refreshContactAvatars"
            >
              {{ avatarRefreshLoading ? '补齐中...' : '执行补齐' }}
            </CtButton>
          </div>

          <div v-if="avatarRefreshMessage" class="maintenance-feedback success">{{ avatarRefreshMessage }}</div>
          <div v-if="avatarRefreshError" class="maintenance-feedback error">{{ avatarRefreshError }}</div>
        </div>
      </CtCard>

      <!-- 计算设备设置 -->
      <CtCard title="⚡ 分析计算设备">
        <div class="form">
          <div class="hint-box info">
            <p>💡 选择历史分析使用的计算设备。GPU 加速可大幅提升分析速度，但需要安装支持 CUDA 的 PyTorch。</p>
          </div>

          <div class="device-mode-options">
            <label class="device-option" :class="{ active: form.analysis_device_mode === 'auto' }">
              <input type="radio" v-model="form.analysis_device_mode" value="auto" />
              <div class="device-option-body">
                <span class="device-option-icon">🔄</span>
                <div>
                  <div class="device-option-title">自动</div>
                  <div class="device-option-desc">每次分析前询问是否启用 GPU</div>
                </div>
              </div>
            </label>
            <label class="device-option" :class="{ active: form.analysis_device_mode === 'gpu' }">
              <input type="radio" v-model="form.analysis_device_mode" value="gpu" />
              <div class="device-option-body">
                <span class="device-option-icon">🚀</span>
                <div>
                  <div class="device-option-title">GPU 加速</div>
                  <div class="device-option-desc">始终使用 GPU，速度提升 5-10 倍</div>
                </div>
              </div>
            </label>
            <label class="device-option" :class="{ active: form.analysis_device_mode === 'cpu' }">
              <input type="radio" v-model="form.analysis_device_mode" value="cpu" />
              <div class="device-option-body">
                <span class="device-option-icon">💻</span>
                <div>
                  <div class="device-option-title">CPU 模式</div>
                  <div class="device-option-desc">仅使用 CPU，兼容性最好</div>
                </div>
              </div>
            </label>
          </div>

          <div class="gpu-status-card">
            <div class="gpu-status-header">当前 GPU 检测状态</div>
            <div v-if="gpuInfoLoading" class="gpu-status-loading">
              <span class="spinner"></span> 正在检测...
            </div>
            <div v-else-if="gpuInfo.cuda_available" class="gpu-status-detail">
              <div class="gpu-status-row"><span class="gpu-label">GPU</span><span class="gpu-value">{{ gpuInfo.gpu_name }}</span></div>
              <div class="gpu-status-row"><span class="gpu-label">CUDA</span><span class="gpu-value">{{ gpuInfo.cuda_version }}</span></div>
              <div class="gpu-status-row"><span class="gpu-label">显存</span><span class="gpu-value">{{ (gpuInfo.gpu_memory_total_mb / 1024).toFixed(1) }} GB</span></div>
              <div class="gpu-status-row"><span class="gpu-label">PyTorch</span><span class="gpu-value">{{ gpuInfo.torch_version }}</span></div>
              <div class="gpu-status-badge available">✅ GPU 可用</div>
            </div>
            <div v-else class="gpu-status-detail">
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
            </div>
          </div>
        </div>
      </CtCard>

      </div>
    </div>

    <!-- 模型表单弹窗（放在根级别，避免 CtCard 内定位闪烁） -->
    <Teleport to="body">
      <div v-if="showModelForm" class="ct-modal-overlay" @click.self="showModelForm = false">
        <div class="ct-modal-dialog">
          <h3>{{ editingModel.id ? '编辑模型' : '添加模型' }}</h3>
          <div class="form">
            <label class="row">
              <div class="lab">名称</div>
              <input v-model="editingModel.name" class="ct-field" placeholder="如: DeepSeek V3" />
            </label>
            <label class="row">
              <div class="lab">供应商</div>
              <select v-model="editingModel.provider" class="ct-field">
                <option value="" disabled hidden>请选择供应商...</option>
                <option value="deepseek">DeepSeek</option>
                <option value="openai">OpenAI</option>
                <option value="zhipu">智谱 GLM</option>
                <option value="moonshot">Kimi (月之暗面)</option>
                <option value="minimax">MiniMax</option>
                <option value="ollama">Ollama（本地）</option>
                <option value="custom">自定义</option>
              </select>
            </label>
            <label class="row">
              <div class="lab">模型 ID</div>
              <div style="display: flex; gap: var(--ct-space-xs); align-items: stretch; flex: 1; position: relative;" @click.stop>
                <input 
                  v-model="editingModel.model_id" 
                  class="ct-field" 
                  :placeholder="modelIdPlaceholder" 
                  style="flex: 1;" 
                  @focus="showModelDropdown = true"
                  @click="showModelDropdown = true"
                />
                <button class="ct-btn" @click.stop.prevent="fetchAvailableModels" :disabled="fetchingModels" title="从接口获取可用模型列表" style="white-space: nowrap; padding: 0 12px; font-size: 13px;">
                  {{ fetchingModels ? '获取中...' : '获取列表' }}
                </button>
                
                <!-- 自定义下拉列表 -->
                <ul v-show="showModelDropdown && availableModels.length > 0" class="ct-custom-dropdown">
                  <li 
                    v-for="m in availableModels" 
                    :key="m" 
                    @click="selectModel(m)"
                    class="dropdown-item"
                  >
                    {{ m }}
                  </li>
                </ul>
              </div>
            </label>
            <label class="row">
              <div class="lab">API Base URL</div>
              <input v-model="editingModel.api_base_url" class="ct-field" :placeholder="apiUrlPlaceholder" />
            </label>
            <label class="row">
              <div class="lab">API Key</div>
              <input v-model="editingModel.api_key" class="ct-field" type="password" placeholder="本地推理可留空" />
            </label>
            <label class="row">
              <div class="lab">温度</div>
              <input v-model.number="editingModel.temperature" class="ct-field" type="number" min="0" max="2" step="0.1" />
            </label>
            <label class="row">
              <div class="lab">Max Tokens</div>
              <input v-model.number="editingModel.max_tokens" class="ct-field" type="number" min="64" step="64" />
            </label>
          </div>
          <div class="form-actions">
            <button class="ct-btn" @click="showModelForm = false">取消</button>
            <button class="ct-btn primary" @click="saveModel" :disabled="!editingModel.name || !editingModel.provider || !editingModel.model_id || !editingModel.api_base_url">保存</button>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted, watch, computed, onUnmounted } from 'vue'
import { bridgeReady, api, type AnalysisDeviceMode } from '@/api/bridge'
import CtCard from '@/components/base/CtCard.vue'
import CtField from '@/components/base/CtField.vue'
import CtButton from '@/components/base/CtButton.vue'
import { showDialog, showConfirm } from '@/utils/dialog'

const loading = ref(false)
const saving = ref(false)
const scanning = ref(false)
const avatarRefreshLoading = ref(false)
const avatarRefreshMessage = ref('')
const avatarRefreshError = ref('')
const autoSaveTimer = ref<number | null>(null)
const lastSaveTime = ref<string>('')

const form = reactive<{ 
  wechat_use_custom_path: boolean
  wechat_data_dir: string
  wechat_user_wxid: string
  wechat_db_key: string
  analysis_device_mode: AnalysisDeviceMode
}>({
  wechat_use_custom_path: false,
  wechat_data_dir: '',
  wechat_user_wxid: '',
  wechat_db_key: '',
  analysis_device_mode: 'auto',
})

// GPU 检测状态
const gpuInfo = reactive<{
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

const gpuInfoLoading = ref(false)

async function loadGpuInfo() {
  gpuInfoLoading.value = true
  try {
    await bridgeReady()
    const status = await api.check_gpu_status()
    if (status) {
      gpuInfo.cuda_available = Boolean(status.cuda_available)
      gpuInfo.has_nvidia_gpu = Boolean(status.has_nvidia_gpu)
      gpuInfo.gpu_name = status.gpu_name ?? null
      gpuInfo.torch_version = status.torch_version ?? 'unknown'
      gpuInfo.cuda_version = status.cuda_version ?? null
      gpuInfo.gpu_memory_total_mb = status.gpu_memory_total_mb ?? 0
      gpuInfo.gpu_memory_free_mb = status.gpu_memory_free_mb ?? 0
    }
  } catch (e) {
    console.error('GPU 检测失败:', e)
  } finally {
    gpuInfoLoading.value = false
  }
}

async function onLoad() {
  loading.value = true
  try {
    await bridgeReady()
    const s = await api.get_settings()
    console.log('[DEBUG] 从后端加载的设置:', s)
    
    if (s && typeof s === 'object') {
      // 微信路径配置
      form.wechat_use_custom_path = Boolean(s.wechat_use_custom_path ?? false)
      form.wechat_data_dir = s.wechat_data_dir ?? ''
      form.wechat_user_wxid = s.wechat_user_wxid ?? ''
      form.wechat_db_key = s.wechat_db_key ?? ''
      // 计算设备模式
      const dm = s.analysis_device_mode
      form.analysis_device_mode = (dm === 'gpu' || dm === 'cpu' || dm === 'auto') ? dm : 'auto'
    }
  } catch (e) {
    console.error('加载设置失败:', e)
  } finally {
    loading.value = false
  }
}

// 自动保存（防抖）
async function autoSave() {
  // 清除之前的定时器
  if (autoSaveTimer.value) {
    clearTimeout(autoSaveTimer.value)
  }
  
  // 500ms 后自动保存
  autoSaveTimer.value = window.setTimeout(async () => {
    await onSave()
  }, 500)
}

async function onSave() {
  // 如果正在保存，跳过
  if (saving.value) return
  
  saving.value = true
  try {
    await bridgeReady()
    
    const settingsToSave = {
      wechat_use_custom_path: form.wechat_use_custom_path,
      wechat_data_dir: form.wechat_data_dir,
      wechat_user_wxid: form.wechat_user_wxid,
      wechat_db_key: form.wechat_db_key,
      analysis_device_mode: form.analysis_device_mode,
    }
    
    console.log('[DEBUG] 自动保存设置:', settingsToSave)
    
    const result = await api.set_settings(settingsToSave)
    console.log('[DEBUG] 保存结果:', result)
    
    // 更新保存时间
    const now = new Date()
    lastSaveTime.value = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`
  } catch (e) {
    console.error('保存设置失败:', e)
  } finally {
    saving.value = false
  }
}

// 文件选择功能
async function selectWeChatDir() {
  // 防止重复点击
  if (scanning.value) {
    console.log('[DEBUG] 扫描进行中，忽略重复点击')
    return
  }

  scanning.value = true

  try {
    await bridgeReady()
    console.log('[DEBUG] 调用 select_directory API')
    const result = await api.select_directory('选择微信数据目录 (WeChat Files)')
    console.log('[DEBUG] select_directory 返回:', result)
    
    if (result && result.path) {
      form.wechat_data_dir = result.path
      console.log('[DEBUG] 已设置微信数据目录:', result.path)
      
      // 自动扫描该目录下的wxid
      await scanWeChatDirectory(result.path)
    } else if (result && result.error) {
      showDialog('选择目录失败：' + result.error)
    } else {
      console.log('[DEBUG] 用户取消选择或未选择')
    }
  } catch (e) {
    console.error('选择目录异常:', e)
    showDialog('选择目录出错：' + (e as Error).message)
  } finally {
    scanning.value = false
  }
}

// 扫描微信目录
async function scanWeChatDirectory(wechatDir: string) {
  try {
    console.log('[DEBUG] 开始扫描微信目录:', wechatDir)
    const scanResult = await api.scan_wechat_directory(wechatDir)
    console.log('[DEBUG] 扫描结果:', scanResult)
    
    if (!scanResult.ok) {
      showDialog('扫描失败：' + (scanResult.error || '未知错误'))
      return
    }
    
    // 如果找到wxid，自动填充第一个
    if (scanResult.wxids && scanResult.wxids.length > 0) {
      const firstWxid = scanResult.wxids[0]
      form.wechat_user_wxid = firstWxid
      console.log('[DEBUG] 自动设置wxid:', firstWxid)
      
      showDialog(`扫描成功！
找到 ${scanResult.wxids.length} 个微信账号
已自动设置第一个账号：${firstWxid}
数据库将在导入时自动检测`)
    } else {
      showDialog('未在该目录下找到微信数据（wxid_ 开头的文件夹）')
    }
  } catch (e) {
    console.error('扫描异常:', e)
    showDialog('扫描出错：' + (e as Error).message)
  }
}

function getPreferredWechatPaths() {
  if (!form.wechat_data_dir.trim() || !form.wechat_user_wxid.trim()) {
    return undefined
  }
  return {
    wechat_dir: form.wechat_data_dir.trim(),
    current_user: form.wechat_user_wxid.trim(),
  }
}

async function refreshContactAvatars() {
  if (avatarRefreshLoading.value) return
  if (!form.wechat_db_key.trim()) {
    avatarRefreshError.value = '请先填写数据库密钥。'
    avatarRefreshMessage.value = ''
    return
  }

  avatarRefreshLoading.value = true
  avatarRefreshMessage.value = ''
  avatarRefreshError.value = ''

  try {
    await bridgeReady()
    const res = await api.refresh_wechat_contact_avatars(
      form.wechat_db_key.trim(),
      getPreferredWechatPaths()
    )

    if (!res?.ok) {
      avatarRefreshError.value = res?.error || '头像补齐失败。'
      return
    }

    const stats = res.stats || {}
    avatarRefreshMessage.value = `头像补齐完成：扫描 ${stats.scanned || 0}，联系人更新 ${stats.contact_updates || 0}，会话更新 ${stats.conversation_updates || 0}，空头像跳过 ${stats.skipped_empty || 0}。`
  } catch (e) {
    console.error('补齐联系人头像失败:', e)
    avatarRefreshError.value = '头像补齐异常：' + ((e as Error).message || '未知错误')
  } finally {
    avatarRefreshLoading.value = false
  }
}

// 监听表单变化，自动保存
watch(form, () => {
  autoSave()
}, { deep: true })

// ========== LLM 模型管理 ==========
const llmModels = ref<any[]>([])
const showModelForm = ref(false)
const editingModel = reactive({
  id: null as number | null,
  name: '',
  provider: '',
  model_id: '',
  api_base_url: '',
  api_key: '',
  is_active: false,
  temperature: 0.7,
  max_tokens: 512,
})

const fetchingModels = ref(false)
const availableModels = ref<string[]>([])
const showModelDropdown = ref(false)

function selectModel(m: string) {
  editingModel.model_id = m
  showModelDropdown.value = false
}

function handleDropdownClickOutside() {
  if (showModelDropdown.value) {
    showModelDropdown.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleDropdownClickOutside)
})

// ========== 常量定义（避免重复编码） ==========
const PROVIDER_CONFIG = {
  deepseek: {
    label: 'DeepSeek',
    apiUrl: 'https://api.deepseek.com/v1',
    modelId: 'deepseek-chat',
  },
  openai: {
    label: 'OpenAI',
    apiUrl: 'https://api.openai.com/v1',
    modelId: 'gpt-5.2',
  },
  zhipu: {
    label: '智谱 GLM',
    apiUrl: 'https://open.bigmodel.cn/api/paas/v4',
    modelId: 'glm-4.7',
  },
  moonshot: {
    label: 'Kimi',
    apiUrl: 'https://api.moonshot.cn/v1',
    modelId: 'moonshot-v2',
  },
  minimax: {
    label: 'MiniMax',
    apiUrl: 'https://api.minimax.com/v1',
    modelId: 'MiniMax-M2.5',
  },
  ollama: {
    label: 'Ollama',
    apiUrl: 'http://localhost:11434/v1',
    modelId: 'qwen2.5:7b',
  },
  custom: {
    label: '自定义',
    apiUrl: '',
    modelId: '',
  },
} as const

onUnmounted(() => {
  document.removeEventListener('click', handleDropdownClickOutside)
})

const modelIdPlaceholder = computed(() => {
  const provider = editingModel.provider
  if (!provider) return '请先选择供应商'
  if (provider === 'custom') return '模型标识'
  return PROVIDER_CONFIG[provider as keyof typeof PROVIDER_CONFIG]?.modelId || '模型标识'
})

const apiUrlPlaceholder = computed(() => {
  const provider = editingModel.provider
  if (!provider) return '请先选择供应商'
  if (provider === 'custom') return 'https://your-api.com/v1'
  return PROVIDER_CONFIG[provider as keyof typeof PROVIDER_CONFIG]?.apiUrl || 'https://api.example.com/v1'
})

function providerLabel(p: string) {
  return PROVIDER_CONFIG[p as keyof typeof PROVIDER_CONFIG]?.label || p
}

async function loadLLMModels() {
  try {
    await bridgeReady()
    const r = await api.get_llm_models()
    if (r.ok) llmModels.value = r.models || []
  } catch (e) {
    console.error('加载模型列表失败:', e)
  }
}

async function fetchAvailableModels() {
  if (!editingModel.api_base_url) {
    showDialog('请先输入 API Base URL')
    return
  }
  fetchingModels.value = true
  try {
    await bridgeReady()
    const r = await api.fetch_provider_models(editingModel.api_base_url, editingModel.api_key || '')
    if (r.ok) {
      availableModels.value = r.models || []
      if (availableModels.value.length === 0) {
        showDialog('获取成功，但该地址没有返回任何模型列表')
      } else {
        if (!editingModel.model_id) {
          editingModel.model_id = availableModels.value[0]
        }
      }
    } else {
      showDialog('获取失败: ' + (r.error || '未知错误'))
    }
  } catch (e) {
    console.error('获取模型列表失败:', e)
    showDialog('请求异常: ' + (e as Error).message)
  } finally {
    fetchingModels.value = false
  }
}

function editModel(m: any) {
  availableModels.value = []
  editingModel.id = m.id
  editingModel.name = m.name
  editingModel.provider = m.provider
  editingModel.model_id = m.model_id
  editingModel.api_base_url = m.api_base_url
  editingModel.api_key = '' // 编辑时不回显密钥
  editingModel.is_active = !!m.is_active
  editingModel.temperature = m.temperature ?? 0.7
  editingModel.max_tokens = m.max_tokens ?? 512
  showModelForm.value = true
}

function resetEditingModel() {
  availableModels.value = []
  editingModel.id = null
  editingModel.name = ''
  editingModel.provider = ''
  editingModel.model_id = ''
  editingModel.api_base_url = ''
  editingModel.api_key = ''
  editingModel.temperature = 0.7
  editingModel.max_tokens = 512
}

async function saveModel() {
  try {
    await bridgeReady()
    const r = await api.save_llm_model({ ...editingModel })
    if (r.ok) {
      showModelForm.value = false
      resetEditingModel()
      await loadLLMModels()
    } else {
      showDialog('保存失败: ' + (r.error || '未知错误'))
    }
  } catch (e) {
    console.error('保存模型失败:', e)
  }
}

async function toggleModelActive(m: any) {
  try {
    await bridgeReady()
    // 反转当前的激活状态
    await api.save_llm_model({ ...m, is_active: !m.is_active })
    await loadLLMModels()
  } catch (e) {
    console.error('切换激活状态失败:', e)
  }
}

async function removeModel(id: number) {
  const confirmed = await showConfirm('确定删除此模型配置？')
  if (!confirmed) return
  try {
    await bridgeReady()
    const r = await api.delete_llm_model(id)
    if (r.ok) await loadLLMModels()
  } catch (e) {
    console.error('删除模型失败:', e)
  }
}

// 监听供应商变化，自动填充 URL 和模型ID
watch(() => editingModel.provider, (p) => {
  if (!editingModel.id) {
    // 新建时自动填充，使用统一的常量配置
    const config = PROVIDER_CONFIG[p as keyof typeof PROVIDER_CONFIG]
    if (config) {
      editingModel.api_base_url = config.apiUrl
      editingModel.model_id = config.modelId
    }
  }
})

onMounted(() => {
  onLoad()
  loadLLMModels()
  loadGpuInfo()
})
</script>

<style scoped>
/* 整体布局 */
.grid { 
  display: grid; 
  grid-template-columns: repeat(2, 1fr); 
  gap: 32px; 
  max-width: 1400px; 
  margin: 0 auto; 
  align-items: stretch;
}

@media (max-width: 1024px) {
  .grid {
    grid-template-columns: 1fr;
    max-width: 900px;
  }
}

.form { display: flex; flex-direction: column; gap: 20px; }
.row { display: grid; grid-template-columns: 180px 1fr; gap: 16px; align-items: center; }
@media (max-width: 768px) {
  .row { grid-template-columns: 1fr; gap: 8px; }
}
.lab { color: var(--ct-text-secondary); font-weight: 500; }

/* 页面标题 & 渐变 */
.ct-page-title {
  margin-bottom: 24px;
  border-bottom: none;
}
.title-icon {
  font-size: 24px;
  filter: drop-shadow(0 2px 4px rgba(0,0,0,0.1));
}
.gradient-text {
  background: linear-gradient(135deg, var(--ct-color-primary, #646cff), var(--ct-color-purple-light, #9c27b0));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  font-weight: 800;
  letter-spacing: 0.5px;
}

/* 自动保存 - 胶囊 */
.glass-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  padding: 6px 16px;
  border-radius: 100px;
  background: rgba(var(--ct-bg-rgb, 255, 255, 255), 0.6);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid rgba(120, 120, 120, 0.1);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
  transition: all 0.3s ease;
}
.auto-save-status .saving {
  color: var(--ct-color-primary, #646cff);
  display: flex;
  align-items: center;
  gap: 6px;
}
.auto-save-status .saved {
  color: var(--ct-color-success, #4caf50);
}
.auto-save-status .idle {
  color: var(--ct-text-tertiary);
}
.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(100, 108, 255, 0.2);
  border-top-color: var(--ct-color-primary, #646cff);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Hint Box */
.hint-box.info {
  background: rgba(24, 144, 255, 0.08);
  border: 1px solid rgba(24, 144, 255, 0.15);
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 8px;
  color: #0056b3;
}
.hint-box p { margin: 0; font-size: 14px; line-height: 1.5; }

.maintenance-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px;
  border-radius: 14px;
  border: 1px solid var(--ct-border-color);
  background: var(--ct-bg-secondary);
}

.maintenance-copy {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.maintenance-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--ct-text-primary);
}

.maintenance-desc {
  font-size: 13px;
  color: var(--ct-text-secondary);
  line-height: 1.5;
}

.maintenance-feedback {
  border-radius: 12px;
  padding: 12px 14px;
  font-size: 13px;
  line-height: 1.5;
}

.maintenance-feedback.success {
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.2);
  color: #0f8f63;
}

.maintenance-feedback.error {
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.2);
  color: #c24141;
}

@media (max-width: 768px) {
  .maintenance-card {
    flex-direction: column;
    align-items: flex-start;
  }
}

/* Switch Toggle 组件 */
.ct-switch {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
}
.ct-switch input {
  opacity: 0;
  width: 0;
  height: 0;
  position: absolute;
}
.ct-switch .slider {
  position: relative;
  width: 44px;
  height: 24px;
  background-color: var(--ct-bg-tertiary, #e0e0e0);
  border-radius: 24px;
  transition: .3s cubic-bezier(0.4, 0.0, 0.2, 1);
  box-shadow: inset 0 1px 3px rgba(0,0,0,0.1);
}
.ct-switch .slider:before {
  position: absolute;
  content: "";
  height: 18px;
  width: 18px;
  left: 3px;
  bottom: 3px;
  background-color: white;
  border-radius: 50%;
  transition: .3s cubic-bezier(0.4, 0.0, 0.2, 1);
  box-shadow: 0 2px 4px rgba(0,0,0,0.2);
}
.ct-switch input:checked + .slider {
  background-color: var(--ct-color-success, #10b981);
}
.ct-switch input:checked + .slider:before {
  transform: translateX(20px);
}
.switch-label {
  font-size: 13px;
  color: var(--ct-text-secondary);
  font-weight: 500;
}
.ct-switch input:checked ~ .switch-label {
  color: var(--ct-color-success, #10b981);
}

/* 模型列表 */
.model-list { 
  display: flex; 
  flex-direction: column; 
  gap: 16px; 
  margin-bottom: 8px; 
  max-height: 380px; 
  overflow-y: auto; 
  padding-right: 6px; 
}

/* 内部内容超出时的滚动条美化 */
.model-list::-webkit-scrollbar {
  width: 6px;
}
.model-list::-webkit-scrollbar-thumb {
  background: var(--ct-border-color, #e0e0e0);
  border-radius: 4px;
}
.model-list::-webkit-scrollbar-track {
  background: transparent;
}
.empty-models { 
  color: var(--ct-text-tertiary); 
  text-align: center; 
  padding: 40px 20px; 
  font-size: 14px;
  background: var(--ct-bg-secondary);
  border-radius: 12px;
  border: 1px dashed var(--ct-border-color);
}

.model-card {
  position: relative;
  flex-shrink: 0;
  border: 1px solid var(--ct-border-color);
  background: var(--ct-bg-1, #ffffff);
  border-radius: 14px;
  padding: 16px 20px;
  transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
  box-shadow: 0 2px 6px rgba(0,0,0,0.02);
  overflow: hidden;
}
.model-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 24px rgba(0,0,0,0.06);
  border-color: rgba(100, 108, 255, 0.3);
}
.model-card.active {
  border-color: var(--ct-color-primary, #646cff);
  background: linear-gradient(to right, rgba(100, 108, 255, 0.03), transparent);
}
.model-card.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  background: var(--ct-color-primary, #646cff);
}

.model-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.model-info { display: flex; align-items: center; gap: 12px; }
.model-name { font-weight: 600; font-size: 16px; color: var(--ct-text-primary); }
.model-provider { 
  font-size: 12px; 
  color: var(--ct-text-secondary); 
  background: var(--ct-bg-secondary); 
  padding: 4px 10px; 
  border-radius: 12px; 
  font-weight: 500;
}

.model-actions { display: flex; gap: 8px; }
.mini-btn {
  border: none;
  background: transparent;
  color: var(--ct-text-secondary);
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}
.mini-btn:hover { background: var(--ct-bg-secondary); color: var(--ct-text-primary); }
.mini-btn.danger:hover { background: rgba(255, 77, 79, 0.1); color: var(--ct-color-error, #ff4d4f); }

.model-detail { 
  display: flex; 
  flex-wrap: wrap; 
  gap: 16px; 
  font-size: 13px; 
  color: var(--ct-text-tertiary); 
  background: var(--ct-bg-secondary);
  padding: 10px 14px;
  border-radius: 8px;
  margin-top: 8px;
}
.model-detail span { display: flex; align-items: center; gap: 4px; }

/* 虚线添加模型按钮 */
.add-model-btn.dashed {
  width: 100%;
  background: transparent;
  border: 2px dashed var(--ct-border-color);
  color: var(--ct-text-secondary);
  padding: 16px;
  border-radius: 14px;
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: all 0.2s;
}
.add-model-btn.dashed .add-icon {
  font-size: 18px;
  font-weight: 400;
}
.add-model-btn.dashed:hover {
  border-color: var(--ct-color-primary, #646cff);
  color: var(--ct-color-primary, #646cff);
  background: rgba(100, 108, 255, 0.04);
}

/* 微信路径输入栏 */
.path-input { display: flex; gap: 12px; align-items: center; }
.path-input .ct-field { flex: 1; }

/* Modal 模糊遮罩 */
.ct-modal-overlay {
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  animation: fadeIn 0.3s ease;
}
@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* 弹窗样式 */
.ct-modal-dialog {
  border-radius: 20px;
  box-shadow: 0 24px 48px rgba(0, 0, 0, 0.2);
  padding: 32px;
  animation: popIn 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  border: 1px solid rgba(255,255,255,0.1);
  background: var(--ct-bg-1, #ffffff);
}
@keyframes popIn {
  from { opacity: 0; transform: scale(0.95) translateY(10px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

.ct-modal-dialog h3 {
  margin-top: 0;
  margin-bottom: 24px;
  font-size: 20px;
  font-weight: 600;
  background: linear-gradient(135deg, var(--ct-color-primary, #646cff), var(--ct-color-purple-light, #9c27b0));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.ct-modal-dialog .form-actions {
  margin-top: 32px;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

/* 下拉菜单美化 */
.ct-custom-dropdown {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  width: 100%;
  max-height: 240px;
  overflow-y: auto;
  background-color: var(--ct-bg-1, #ffffff);
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: 12px;
  padding: 6px;
  margin: 0;
  list-style: none;
  z-index: 99999;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
  animation: dropIn 0.2s ease;
}
@keyframes dropIn {
  from { opacity: 0; transform: translateY(-5px); }
  to { opacity: 1; transform: translateY(0); }
}
.ct-custom-dropdown::-webkit-scrollbar { width: 6px; }
.ct-custom-dropdown::-webkit-scrollbar-thumb { background-color: var(--ct-border-color); border-radius: 3px; }

.ct-custom-dropdown .dropdown-item {
  padding: 10px 14px;
  font-size: 14px;
  color: var(--ct-text-primary);
  cursor: pointer;
  border-radius: 8px;
  transition: all 0.2s;
  margin-bottom: 2px;
}
.ct-custom-dropdown .dropdown-item:last-child { margin-bottom: 0; }
.ct-custom-dropdown .dropdown-item:hover {
  background-color: rgba(100, 108, 255, 0.08);
  color: var(--ct-color-primary, #646cff);
}

/* 计算设备设置 */
.device-mode-options {
  display: flex;
  gap: 12px;
}
@media (max-width: 768px) {
  .device-mode-options { flex-direction: column; }
}
.device-option {
  flex: 1;
  cursor: pointer;
  position: relative;
}
.device-option input[type="radio"] {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}
.device-option-body {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border-radius: 14px;
  border: 2px solid var(--ct-border-color, #e0e0e0);
  background: var(--ct-bg-1, #ffffff);
  transition: all 0.25s cubic-bezier(0.25, 0.8, 0.25, 1);
}
.device-option:hover .device-option-body {
  border-color: rgba(100, 108, 255, 0.35);
  box-shadow: 0 4px 12px rgba(100, 108, 255, 0.08);
}
.device-option.active .device-option-body {
  border-color: var(--ct-color-primary, #646cff);
  background: linear-gradient(135deg, rgba(100, 108, 255, 0.06), rgba(156, 39, 176, 0.04));
  box-shadow: 0 4px 16px rgba(100, 108, 255, 0.12);
}
.device-option-icon {
  font-size: 24px;
  flex-shrink: 0;
}
.device-option-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--ct-text-primary);
  margin-bottom: 2px;
}
.device-option-desc {
  font-size: 12px;
  color: var(--ct-text-tertiary);
  line-height: 1.4;
}

.gpu-status-card {
  background: var(--ct-bg-secondary, #f8f9fa);
  border-radius: 12px;
  padding: 16px;
  border: 1px solid var(--ct-border-subtle, rgba(0,0,0,0.06));
}
.gpu-status-header {
  font-size: 13px;
  font-weight: 600;
  color: var(--ct-text-secondary);
  margin-bottom: 12px;
}
.gpu-status-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--ct-text-tertiary);
  font-size: 13px;
}
.gpu-status-detail {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.gpu-status-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
}
.gpu-label {
  color: var(--ct-text-tertiary);
  font-weight: 500;
}
.gpu-value {
  color: var(--ct-text-primary);
  font-weight: 500;
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 12px;
}
.gpu-status-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 12px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  width: fit-content;
}
.gpu-status-badge.available {
  background: rgba(16, 185, 129, 0.1);
  color: #059669;
}
.gpu-status-badge.unavailable {
  background: rgba(239, 68, 68, 0.1);
  color: #dc2626;
}
</style>
