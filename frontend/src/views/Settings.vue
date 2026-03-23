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
import { bridgeReady, api } from '@/api/bridge'
import CtCard from '@/components/base/CtCard.vue'
import CtField from '@/components/base/CtField.vue'
import CtButton from '@/components/base/CtButton.vue'
import { showDialog, showConfirm } from '@/utils/dialog'

const loading = ref(false)
const saving = ref(false)
const scanning = ref(false)
const autoSaveTimer = ref<number | null>(null)
const lastSaveTime = ref<string>('')

const form = reactive<{ 
  wechat_use_custom_path: boolean
  wechat_data_dir: string
  wechat_user_wxid: string
  wechat_db_key: string
}>({
  wechat_use_custom_path: false,
  wechat_data_dir: '',
  wechat_user_wxid: '',
  wechat_db_key: '',
})

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
      
      console.log('[DEBUG] 设置已加载到表单')
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
</style>
