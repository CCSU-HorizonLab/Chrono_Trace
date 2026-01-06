<template>
  <section class="settings-page">
    <header class="page-title">
      <h1>设置</h1>
      <div class="auto-save-status">
        <span v-if="saving" class="saving">💾 保存中...</span>
        <span v-else-if="lastSaveTime" class="saved">✅ 已保存 {{ lastSaveTime }}</span>
        <span v-else class="idle">⚙️ 自动保存已启用</span>
      </div>
    </header>

    <div class="grid">
      <!-- 通用配置 -->
      <CtCard title="通用配置">
        <template #default>
          <div class="form">
            <label class="row">
              <div class="lab">模型</div>
              <select v-model="form.model" class="ct-field">
                <option value="local">本地/内置</option>
                <option value="openai-gpt-4o">OpenAI · GPT-4o</option>
                <option value="qwen">阿里 · 通义千问</option>
                <option value="moonshot">Moonshot</option>
              </select>
            </label>

            <label class="row">
              <div class="lab">API Token</div>
              <CtField v-model="form.api_token" placeholder="用于访问所选模型的 API Token（保存在本地）" />
            </label>
          </div>
        </template>
        <template #footer>
          <small class="hint">提示：不同模型供应商可能需要在后端设置额外 Base URL 或代理；本页仅保存 Token 与模型类型。</small>
        </template>
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
  </section>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted, watch } from 'vue'
import { bridgeReady, api } from '@/api/bridge'
import CtCard from '@/components/base/CtCard.vue'
import CtField from '@/components/base/CtField.vue'
import CtButton from '@/components/base/CtButton.vue'

const loading = ref(false)
const saving = ref(false)
const scanning = ref(false)
const autoSaveTimer = ref<number | null>(null)
const lastSaveTime = ref<string>('')

const form = reactive<{ 
  model: string
  api_token: string
  interval_minutes: number
  batch_size: number
  realtime_enabled: boolean
  wechat_use_custom_path: boolean
  wechat_data_dir: string
  wechat_user_wxid: string
  wechat_db_key: string
}>({
  model: 'local',
  api_token: '',
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
      form.model = s.model ?? form.model
      form.api_token = s.api_token ?? form.api_token
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
      model: form.model,
      api_token: form.api_token,
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
      alert('选择目录失败：' + result.error)
    } else {
      console.log('[DEBUG] 用户取消选择或未选择')
    }
  } catch (e) {
    console.error('选择目录异常:', e)
    alert('选择目录出错：' + (e as Error).message)
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
      alert('扫描失败：' + (scanResult.error || '未知错误'))
      return
    }
    
    // 如果找到wxid，自动填充第一个
    if (scanResult.wxids && scanResult.wxids.length > 0) {
      const firstWxid = scanResult.wxids[0]
      form.wechat_user_wxid = firstWxid
      console.log('[DEBUG] 自动设置wxid:', firstWxid)
      
      alert(`扫描成功！
找到 ${scanResult.wxids.length} 个微信账号
已自动设置第一个账号：${firstWxid}
数据库将在导入时自动检测`)
    } else {
      alert('未在该目录下找到微信数据（wxid_ 开头的文件夹）')
    }
  } catch (e) {
    console.error('扫描异常:', e)
    alert('扫描出错：' + (e as Error).message)
  }
}

// 监听表单变化，自动保存
watch(form, () => {
  autoSave()
}, { deep: true })

onMounted(() => { onLoad() })
</script>

<style scoped>
.settings-page { display: flex; flex-direction: column; gap: var(--ct-space-lg); }
.page-title { display: flex; align-items: center; justify-content: space-between; }
.page-title h1 { margin: 0; color: var(--ct-color-primary); }

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
</style>
