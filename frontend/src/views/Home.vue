<template>
  <section class="home-page">
    <!-- 关于 Chrono_Trace -->
    <div class="home-section">
      <h2 class="section-title"><span class="dot pink"></span>关于Chrono_Trace</h2>
      <div class="features-grid">
        <div class="feature-card">
          <div class="icon-wrap bg-yellow">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"></path></svg>
          </div>
          <div>
            <h3>情绪曲线</h3>
            <p>历史情绪波动</p>
          </div>
        </div>
        <div class="feature-card">
          <div class="icon-wrap bg-purple">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><path d="M3 18v-6a9 9 0 0 1 18 0v6"></path><path d="M21 19a2 2 0 0 1-2 2h-1v-6h3v4z"></path><path d="M3 19a2 2 0 0 0 2 2h1v-6H3v4z"></path></svg>
          </div>
          <div>
            <h3>实时监听</h3>
            <p>边聊边建议</p>
          </div>
        </div>
        <div class="feature-card">
          <div class="icon-wrap bg-orange">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><rect x="3" y="11" width="18" height="10" rx="2"></rect><circle cx="12" cy="5" r="2"></circle><path d="M12 7v4"></path><line x1="8" y1="16" x2="8" y2="16"></line><line x1="16" y1="16" x2="16" y2="16"></line></svg>
          </div>
          <div>
            <h3>AI 策略</h3>
            <p>个性化沟通</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 微信数据导入 -->
    <div class="home-section">
      <h2 class="section-title"><span class="dot pink"></span>微信数据导入</h2>
      
      <div class="wizard-container">
        <!-- 步骤 1 -->
        <div class="wizard-step">
          <div class="step-header">
            <span class="step-num bg-purple">1</span>
            <span class="step-title">获取数据库密钥</span>
          </div>
          <div class="step-content">
            <a href="https://github.com/ycccccccy/wx_key" target="_blank" class="tool-link">
              <span class="tool-icon">🔑</span> 下载wx_key工具
            </a>
          </div>
        </div>

        <div class="step-arrow">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ccc" stroke-width="2"><polyline points="13 17 18 12 13 7"></polyline><polyline points="6 17 11 12 6 7"></polyline></svg>
        </div>

        <!-- 步骤 2 -->
        <div class="wizard-step">
          <div class="step-header">
            <span class="step-num bg-purple">2</span>
            <span class="step-title">输入密钥</span>
          </div>
          <div class="step-content flex-row">
            <input 
              v-model="wechatForm.dbKey" 
              class="ct-field"
              placeholder="db_key_7f8e3a2..." 
              type="password"
            />
            <button class="verify-btn" :disabled="!wechatForm.dbKey.trim() || verifying" @click.stop.prevent="onVerifyAndUnpack">
              {{ verifying ? '...' : '验证' }}
            </button>
          </div>
        </div>

        <div class="step-arrow">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ccc" stroke-width="2"><polyline points="13 17 18 12 13 7"></polyline><polyline points="6 17 11 12 6 7"></polyline></svg>
        </div>

        <!-- 步骤 3 -->
        <div class="wizard-step">
          <div class="step-header">
            <span class="step-num bg-purple">3</span>
            <span class="step-title">选择数据目录（可选）</span>
          </div>
          <div class="step-content flex-row">
            <div class="path-display">
               <span class="folder-icon">📁</span>
               <span class="path-text">{{ (pathInfo && pathInfo.wechat_dir) || customWechatDir || '自动检测中...' }}</span>
            </div>
            <button class="change-btn" @click.stop.prevent="selectCustomPath">更改</button>
          </div>
        </div>
      </div>

      <!-- 进度与提示 -->
      <div class="status-area">
        <div v-if="importProgress" class="progress-box">
          <p>{{ importProgress.status }}</p>
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: importProgress.percent + '%' }"></div>
          </div>
        </div>
        <p v-if="wechatErr" class="error-msg">{{ wechatErr }}</p>
        <p v-if="wechatOk" class="success-msg">{{ wechatOk }}</p>
      </div>

      <!-- 主操作区 -->
      <div class="wizard-actions">
        <button class="btn-primary-large" :disabled="!pathInfo" @click.stop.prevent="startImport">
          {{ wechatImporting ? '导入中...' : '开始导入' }}
        </button>
        <button class="btn-outline-large" @click.stop.prevent="resetFlow">重新配置</button>
      </div>
    </div>

    <!-- 运行日志 -->
    <div class="home-section">
      <h2 class="section-title"><span class="dot green"></span>运行日志</h2>
      <div class="log-container">
        <div v-if="!logs.length" class="empty-log">暂无日志</div>
        <ul v-else class="log-list">
          <li v-for="(l, i) in logs" :key="i" class="log-item">
            <span class="log-ts">{{ l.ts.split(' ')[0] === new Date().toLocaleDateString() ? '今天 ' + l.ts.split(' ')[1] : l.ts }}</span>
            <span class="log-user">张彬彬</span>
            <span class="log-count">2, 345条</span>
            <span class="log-msg">{{ l.msg }}</span>
            <a href="#" class="log-link" @click.prevent>查看>></a>
          </li>
        </ul>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { bridgeReady, api } from '@/api/bridge'
import CtCard from '@/components/base/CtCard.vue'
import CtField from '@/components/base/CtField.vue'
import CtButton from '@/components/base/CtButton.vue'

// 微信导入表单
const wechatForm = reactive({
  dbKey: '',
  importContacts: true,
  importMessages: true
})
const wechatErr = ref('')
const wechatOk = ref('')
const wechatImporting = ref(false)
const verifying = ref(false)
const importProgress = ref<{ status: string; percent: number } | null>(null)

// 路径信息
const pathInfo = ref<any>(null)
const showCustomPath = ref(false)
const customWechatDir = ref('')

// 日志
const logs = ref<{ ts: string; msg: string }[]>([
  { ts: new Date().toLocaleString(), msg: "系统启动完成，等待导入..." },
  { ts: new Date().toLocaleString(), msg: "初始化配置加载成功" }
])

function addLog(msg: string) {
  const ts = new Date().toLocaleString()
  logs.value.unshift({ ts, msg })
}

// 页面加载时尝试恢复保存的路径配置和密钥
async function loadSavedPaths() {
  try {
    await bridgeReady()
    const settings = await api.get_settings()
    console.log('[DEBUG] 加载已保存的设置:', settings)
    
    // 恢复密钥
    if (settings.wechat_db_key) {
      wechatForm.dbKey = settings.wechat_db_key
      addLog('✅ 已恢复上次保存的数据库密钥')
      console.log('[DEBUG] 已恢复密钥')
    }
    
    // 恢复路径信息
    if (settings.wechat_data_dir && settings.wechat_user_wxid) {
      pathInfo.value = {
        wechat_dir: settings.wechat_data_dir,
        current_user: settings.wechat_user_wxid,
        databases: {},
        source: settings.wechat_use_custom_path ? 'custom' : 'auto'
      }
      addLog('✅ 已恢复上次保存的路径配置')
      console.log('[DEBUG] 已恢复路径信息:', pathInfo.value)
    } else {
      console.log('[DEBUG] 未找到已保存的路径配置')
    }
  } catch (e) {
    console.error('[ERROR] 加载设置失败:', e)
  }
}

// 组件挂载时加载保存的路径
onMounted(() => {
  loadSavedPaths()
})

// 核心流程：验证并解包
async function onVerifyAndUnpack() {
  if (verifying.value || wechatImporting.value) return
  wechatErr.value = ''
  wechatOk.value = ''
  importProgress.value = null

  if (!wechatForm.dbKey.trim()) {
    wechatErr.value = '请输入数据库密钥'
    return
  }

  if (pathInfo.value) {
    await startImport()
    return
  }

  verifying.value = true
  addLog('正在验证密钥和查找微信数据...')

  try {
    await bridgeReady()
    importProgress.value = { status: '验证密钥...', percent: 10 }
    const verifyRes = await api.verify_wechat_key(wechatForm.dbKey)
    
    if (!verifyRes.ok) {
      wechatErr.value = verifyRes.error || '密钥验证失败'
      addLog('密钥验证失败: ' + wechatErr.value)
      verifying.value = false; importProgress.value = null; return;
    }

    addLog('✅ 密钥验证成功')
    importProgress.value = { status: '查找微信数据路径...', percent: 30 }
    const pathRes = await api.get_wechat_paths()
    
    if (pathRes.ok && pathRes.data) {
      pathInfo.value = pathRes.data
      addLog('✅ 自动检测到微信数据路径')
      wechatOk.value = '解包成功！检测到微信数据，可以开始导入'
      await savePathsToSettings(pathRes.data, false)
    } else {
      addLog('⚠️ 自动检测失败，请手动选择微信数据目录')
      showCustomPath.value = true
      wechatErr.value = '未能自动检测到微信路径，请手动选择数据目录'
    }
  } catch (e: any) {
    wechatErr.value = e?.message || '验证异常'
    addLog('验证异常: ' + wechatErr.value)
  } finally {
    importProgress.value = null
    verifying.value = false
  }
}

async function startImport() {
  if (wechatImporting.value) return
  wechatImporting.value = true; wechatErr.value = ''; wechatOk.value = ''
  addLog('开始导入微信数据...')

  try {
    await bridgeReady()
    importProgress.value = { status: '正在解密数据库...', percent: 20 }
    const res = await api.import_wechat_data(wechatForm.dbKey, {
      import_contacts: wechatForm.importContacts,
      import_messages: wechatForm.importMessages
    })

    if (res.ok) {
      const stats = res.stats || {}
      wechatOk.value = `✅ 导入成功！联系人: ${stats.contacts || 0}, 消息: ${stats.messages || 0}, 会话: ${stats.conversations || 0}`
      addLog(wechatOk.value)
    } else {
      wechatErr.value = res.error || '导入失败'
      addLog('❌ 导入失败: ' + wechatErr.value)
    }
  } catch (e: any) {
    wechatErr.value = e?.message || '导入异常'
    addLog('❌ 导入异常: ' + wechatErr.value)
  } finally {
    importProgress.value = { status: '完成', percent: 100 }
    setTimeout(() => { importProgress.value = null }, 2000)
    wechatImporting.value = false
  }
}

async function selectCustomPath() {
  try {
    await bridgeReady()
    const result = await api.select_directory('选择微信数据目录 (WeChat Files)')
    if (result && result.path) {
      customWechatDir.value = result.path
      addLog('已选择目录: ' + result.path)
      await scanAndSetCustomPath(result.path)
    }
  } catch (e: any) {
    wechatErr.value = '选择目录失败: ' + (e?.message || '未知错误')
  }
}

async function savePathsToSettings(paths: any, isCustom: boolean) {
  try {
    await api.set_settings({
      wechat_use_custom_path: isCustom,
      wechat_data_dir: paths.wechat_dir || '',
      wechat_user_wxid: paths.current_user || '',
      wechat_db_key: wechatForm.dbKey
    })
  } catch (e) {
    console.error('[ERROR] 保存设置失败:', e)
  }
}

async function scanAndSetCustomPath(wechatDir: string) {
  try {
    addLog('扫描微信目录...')
    const scanResult = await api.scan_wechat_directory(wechatDir)
    if (!scanResult.ok || !scanResult.wxids || scanResult.wxids.length === 0) {
      wechatErr.value = '未在该目录下找到微信数据'
      addLog('扫描失败: 未找到wxid')
      return
    }
    const firstWxid = scanResult.wxids[0]
    const databases = scanResult.databases[firstWxid]
    const newPathInfo = {
      wechat_dir: wechatDir, current_user: firstWxid,
      databases: { message: databases.msg_dbs || [], contact: databases.contact_db },
      source: 'custom'
    }
    pathInfo.value = newPathInfo
    await savePathsToSettings(newPathInfo, true)
    showCustomPath.value = false
    wechatOk.value = `✅ 扫描成功！找到 ${scanResult.wxids.length} 个账号，已设置为：${firstWxid}`
    addLog(wechatOk.value)
  } catch (e: any) {
    wechatErr.value = '扫描失败: ' + (e?.message || '未知错误')
  }
}

function resetFlow() {
  pathInfo.value = null; showCustomPath.value = false; customWechatDir.value = '';
  wechatErr.value = ''; wechatOk.value = ''; importProgress.value = null;
  addLog('已重置配置')
}
</script>

<style scoped>
/* 1. 关于 Chrono_Trace 卡片网格 */
.features-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}

.feature-card {
  background: #f7f9fc;
  border-radius: 12px;
  padding: 30px 20px;
  display: flex;
  align-items: center;
  gap: 20px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.02);
  transition: transform 0.2s;
}

.feature-card:hover { transform: translateY(-2px); }

.icon-wrap {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.bg-yellow { background: #eab308; }
.bg-purple { background: #a855f7; }
.bg-orange { background: #f97316; }

.feature-card h3 { margin: 0 0 4px 0; font-size: 16px; color: var(--ct-text-primary); }
.feature-card p { margin: 0; font-size: 13px; color: var(--ct-text-secondary); }

/* 2. 微信数据导入 步骤向导 */
.wizard-container {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 30px;
}

.wizard-step {
  flex: 1;
  background: #f7f9fc;
  border-radius: 12px;
  padding: 20px;
  min-height: 110px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.step-arrow {
  padding: 0 16px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.step-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.step-num {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: bold;
}

.step-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--ct-text-primary);
}

.step-content {
  font-size: 13px;
  color: var(--ct-text-secondary);
}

.flex-row {
  display: flex;
  gap: 10px;
  align-items: center;
}

.tool-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: #f1f5f9;
  border-radius: 6px;
  color: var(--ct-text-secondary);
  border: 1px solid #e2e8f0;
}
.tool-link:hover { background: #e2e8f0; }

.verify-btn, .change-btn {
  padding: 8px 16px;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
  background: #fff;
  color: var(--ct-color-primary);
  cursor: pointer;
  white-space: nowrap;
}
.verify-btn:hover:not(:disabled), .change-btn:hover { background: #f1f5f9; }
.verify-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.path-display {
  flex: 1;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  overflow: hidden;
}
.path-text {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.wizard-actions {
  display: flex;
  justify-content: flex-start;
  gap: 20px;
  margin-top: 10px;
}

.btn-primary-large {
  background: var(--ct-color-primary);
  color: #fff;
  border: none;
  padding: 12px 60px;
  border-radius: 30px;
  font-size: 16px;
  font-weight: 500;
  cursor: pointer;
  box-shadow: 0 4px 12px var(--ct-color-primary-muted);
}
.btn-primary-large:hover:not(:disabled) {
  background: var(--ct-color-primary-hover);
  transform: translateY(-1px);
}
.btn-primary-large:disabled { opacity: 0.6; cursor: not-allowed; }

.btn-outline-large {
  background: #fff;
  color: var(--ct-color-primary);
  border: 1px solid var(--ct-color-primary-light);
  padding: 12px 40px;
  border-radius: 30px;
  font-size: 16px;
  cursor: pointer;
}
.btn-outline-large:hover { background: var(--ct-color-primary-light); }

.status-area { margin: 10px 0; }
.error-msg { color: #ef4444; font-size: 14px; margin: 10px 0; }
.success-msg { color: #10b981; font-size: 14px; margin: 10px 0; }
.progress-box { max-width: 400px; margin: 0 0 10px; }
.progress-bar { height: 6px; background: #e2e8f0; border-radius: 3px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--ct-color-primary); transition: width 0.3s ease; }

/* 3. 运行日志 */
.log-container {
  padding-left: 20px;
}

.log-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.log-item {
  display: flex;
  align-items: center;
  font-size: 14px;
  color: var(--ct-text-secondary);
}

.log-ts { width: 100px; color: var(--ct-text-tertiary); }
.log-user { width: 80px; font-weight: 600; color: var(--ct-text-primary); }
.log-count { width: 100px; }
.log-msg { flex: 1; opacity: 0.6; }

.log-link {
  color: var(--ct-color-primary);
  text-decoration: none;
  font-size: 13px;
  margin-left: 10px;
}
.log-link:hover { text-decoration: underline; }
.empty-log { color: var(--ct-text-tertiary); font-style: italic; }

@media (max-width: 1024px) {
  .features-grid { grid-template-columns: 1fr; }
  .wizard-container { flex-direction: column; gap: 10px; }
  .step-arrow { transform: rotate(90deg); padding: 10px 0; }
  .log-item { flex-wrap: wrap; gap: 10px; }
  .log-msg { display: none; }
}
</style>
