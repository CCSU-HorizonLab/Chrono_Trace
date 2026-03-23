<template>
  <section class="home-page">
    <div class="home-section">
      <h2 class="section-title">
        <div style="display:flex;align-items:center;">
          <span class="dot purple"></span>设置
        </div>
        <div class="auto-save-status" style="margin-left: auto;">
          <span v-if="saving" class="saving">💾 保存中...</span>
          <span v-else-if="lastSaveTime" class="saved">✅ 已保存 {{ lastSaveTime }}</span>
          <span v-else class="idle">⚙️ 自动保存已启用</span>
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
                  <button 
                    class="badge toggle-badge" 
                    :class="{ active: m.is_active }"
                    @click="toggleModelActive(m)"
                    title="点击切换激活状态"
                  >
                    {{ m.is_active ? '✅ 已激活' : '未激活' }}
                  </button>
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

          <button class="ct-btn primary add-model-btn" @click.prevent="resetEditingModel(); showModelForm = true">
            + 添加模型
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
            <input v-model="form.wechat_use_custom_path" type="checkbox" />
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

      <!-- 消息抓取与监听 -->
      <CtCard title="消息抓取与监听">
        <div class="form">
          <label class="row">
            <div class="lab">抓取间隔（分钟）</div>
            <input v-model.number="form.interval_minutes" type="number" min="1" step="1" class="ct-field" placeholder="如：15" />
          </label>

          <label class="row">
            <div class="lab">每次最大抓取条数</div>
            <input v-model.number="form.batch_size" type="number" min="10" step="10" class="ct-field" placeholder="如：100" />
          </label>

          <label class="row">
            <div class="lab">启用实时监听</div>
            <input v-model="form.realtime_enabled" type="checkbox" />
          </label>
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
import { showDialog } from '@/utils/dialog'

const loading = ref(false)
const saving = ref(false)
const scanning = ref(false)
const autoSaveTimer = ref<number | null>(null)
const lastSaveTime = ref<string>('')

const form = reactive<{ 
  interval_minutes: number
  batch_size: number
  realtime_enabled: boolean
  wechat_use_custom_path: boolean
  wechat_data_dir: string
  wechat_user_wxid: string
  wechat_db_key: string
}>({
  interval_minutes: 15,
  batch_size: 100,
  realtime_enabled: true,
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
      form.interval_minutes = Number(s.interval_minutes ?? form.interval_minutes)
      form.batch_size = Number(s.batch_size ?? form.batch_size)
      form.realtime_enabled = Boolean(s.realtime_enabled ?? form.realtime_enabled)
      
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
      interval_minutes: form.interval_minutes,
      batch_size: form.batch_size,
      realtime_enabled: form.realtime_enabled,
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
  if (!confirm('确定删除此模型配置？')) return
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
/* 自动保存状态 */
.auto-save-status {
  display: flex;
  align-items: center;
  gap: var(--ct-space-sm);
  font-size: var(--ct-text-sm);
  padding: 6px var(--ct-space-md);
  border-radius: var(--ct-radius-sm);
  background: var(--ct-bg-secondary);
}
.auto-save-status .saving {
  color: var(--ct-color-info);
  animation: pulse 1.5s var(--ct-ease-in-out) infinite;
}
.auto-save-status .saved {
  color: var(--ct-color-success);
}
.auto-save-status .idle {
  color: var(--ct-text-secondary);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.grid { display: grid; grid-template-columns: 1fr; gap: var(--ct-space-lg); }
.form { display: flex; flex-direction: column; gap: var(--ct-space-md); }
.row { display: grid; grid-template-columns: 160px 1fr; gap: var(--ct-space-md); align-items: center; }
.lab { color: var(--ct-text-secondary); }
.hint { color: var(--ct-text-secondary); }

.hint-box.info {
  background: var(--ct-color-info-light);
  border-left: 3px solid var(--ct-color-info);
  padding: var(--ct-space-md);
  margin-bottom: var(--ct-space-sm);
  border-radius: var(--ct-radius-sm);
}
.hint-box p { margin: var(--ct-space-xs) 0; font-size: var(--ct-text-sm); }
.path-input { display: flex; gap: var(--ct-space-sm); align-items: center; }
.path-input .ct-field { flex: 1; }



/* 模型列表 */
.model-list { display: flex; flex-direction: column; gap: var(--ct-space-sm); }
.empty-models { color: var(--ct-text-tertiary); text-align: center; padding: var(--ct-space-lg); font-size: var(--ct-text-sm); }

.model-card {
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  padding: var(--ct-space-md);
  transition: all var(--ct-transition-fast);
}
.model-card.active {
  border-color: var(--ct-color-primary);
  background: var(--ct-color-primary-light);
}
.model-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--ct-space-xs);
}
.model-info { display: flex; align-items: center; gap: var(--ct-space-sm); }
.model-name { font-weight: var(--ct-font-semibold); }
.model-provider { font-size: var(--ct-text-xs); color: var(--ct-text-secondary); background: var(--ct-bg-tertiary); padding: 2px 6px; border-radius: var(--ct-radius-sm); }
.badge.toggle-badge { 
  font-size: var(--ct-text-xs); 
  padding: 2px 8px; 
  border-radius: var(--ct-radius-sm); 
  border: 1px solid var(--ct-border-color);
  background: var(--ct-bg-secondary);
  color: var(--ct-text-secondary);
  cursor: pointer;
  transition: all var(--ct-transition-fast);
}
.badge.toggle-badge:hover {
  background: var(--ct-bg-tertiary);
}
.badge.toggle-badge.active { 
  background: var(--ct-color-success-light, #e8f5e9); 
  color: var(--ct-color-success, #4caf50); 
  border-color: var(--ct-color-success, #4caf50);
}
.model-actions { display: flex; gap: var(--ct-space-xs); }
.mini-btn {
  border: 1px solid var(--ct-border-color);
  background: transparent;
  color: var(--ct-text-secondary);
  padding: 3px 8px;
  border-radius: var(--ct-radius-sm);
  font-size: var(--ct-text-xs);
  cursor: pointer;
  transition: all var(--ct-transition-fast);
}
.mini-btn:hover { background: var(--ct-bg-tertiary); color: var(--ct-text-primary); }
.mini-btn.danger:hover { background: var(--ct-color-error-light); color: var(--ct-color-error); border-color: var(--ct-color-error); }
.model-detail { display: flex; flex-wrap: wrap; gap: var(--ct-space-sm); font-size: var(--ct-text-xs); color: var(--ct-text-tertiary); }

.add-model-btn { align-self: flex-start; }

.ct-custom-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  width: 100%;
  max-height: 200px;
  overflow-y: auto;
  background-color: var(--ct-bg-1, #ffffff);
  border: 1px solid var(--ct-border);
  border-radius: var(--ct-radius-md);
  padding: 0;
  margin: 0;
  list-style: none;
  z-index: 99999;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.ct-custom-dropdown::-webkit-scrollbar {
  width: 6px;
}
.ct-custom-dropdown::-webkit-scrollbar-track {
  background: transparent;
}
.ct-custom-dropdown::-webkit-scrollbar-thumb {
  background-color: var(--ct-border);
  border-radius: 3px;
}

.ct-custom-dropdown .dropdown-item {
  padding: 8px 12px;
  font-size: 14px;
  color: var(--ct-text-1);
  cursor: pointer;
  transition: all 0.2s ease;
}

.ct-custom-dropdown .dropdown-item:hover {
  background-color: var(--ct-bg-hover);
  color: var(--ct-primary);
}
</style>
