<template>
  <section class="home-page">
    <div class="home-section">
      <h2 class="section-title"><span class="dot pink"></span>关于 Chrono Trace</h2>
      <div class="features-grid">
        <div class="feature-card">
          <div class="icon-wrap bg-yellow">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2" /></svg>
          </div>
          <div>
            <h3>情绪曲线</h3>
            <p>观察历史情绪波动</p>
          </div>
        </div>
        <div class="feature-card">
          <div class="icon-wrap bg-purple">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><path d="M3 18v-6a9 9 0 0 1 18 0v6" /><path d="M21 19a2 2 0 0 1-2 2h-1v-6h3v4z" /><path d="M3 19a2 2 0 0 0 2 2h1v-6H3v4z" /></svg>
          </div>
          <div>
            <h3>实时监听</h3>
            <p>边聊天边获得建议</p>
          </div>
        </div>
        <div class="feature-card">
          <div class="icon-wrap bg-orange">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><rect x="3" y="11" width="18" height="10" rx="2" /><circle cx="12" cy="5" r="2" /><path d="M12 7v4" /><line x1="8" y1="16" x2="8" y2="16" /><line x1="16" y1="16" x2="16" y2="16" /></svg>
          </div>
          <div>
            <h3>AI 策略</h3>
            <p>输出可执行沟通方向</p>
          </div>
        </div>
      </div>
    </div>

    <div class="home-section">
      <h2 class="section-title"><span class="dot pink"></span>微信数据导入</h2>

      <div v-if="incrementInfo" class="increment-banner">
        <div class="increment-copy">
          <strong>检测到微信数据有更新</strong>
          <p>新增大小 {{ formatBytes(incrementInfo.incrementSize) }}，上次导入时间 {{ formatImportTime(incrementInfo.lastImportAt) }}</p>
        </div>
        <div class="increment-actions">
          <button class="verify-btn" @click.stop.prevent="startImport">立即同步</button>
          <button class="change-btn" @click.stop.prevent="dismissIncrementBanner">暂不处理</button>
        </div>
      </div>

      <div v-if="availableAccounts.length" class="account-selector-row">
        <label class="account-selector-label">当前账号</label>
        <select :value="selectedWxid" class="account-selector-select" @change="onAccountSelect">
          <option v-for="account in availableAccounts" :key="account.wxid" :value="account.wxid">
            {{ account.label || account.wxid }}
          </option>
        </select>
      </div>

      <div class="wizard-container">
        <div class="wizard-step">
          <div class="step-header">
            <span class="step-num bg-purple">1</span>
            <span class="step-title">获取数据库密钥</span>
          </div>
          <div class="step-content">
            <a href="https://github.com/ycccccccy/wx_key" target="_blank" class="tool-link">
              <span class="tool-icon">下载</span> 获取 `wx_key` 工具
            </a>
          </div>
        </div>

        <div class="step-arrow">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ccc" stroke-width="2"><polyline points="13 17 18 12 13 7" /><polyline points="6 17 11 12 6 7" /></svg>
        </div>

        <div class="wizard-step">
          <div class="step-header">
            <span class="step-num bg-purple">2</span>
            <span class="step-title">验证密钥</span>
          </div>
          <div class="step-content flex-row">
            <input
              v-model="wechatForm.dbKey"
              class="ct-field"
              placeholder="db_key_7f8e3a2..."
              type="password"
            />
            <button class="verify-btn" :disabled="!wechatForm.dbKey.trim() || verifying || wechatImporting" @click.stop.prevent="onVerifyAndUnpack">
              {{ verifying ? '验证中...' : '验证' }}
            </button>
          </div>
        </div>

        <div class="step-arrow">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ccc" stroke-width="2"><polyline points="13 17 18 12 13 7" /><polyline points="6 17 11 12 6 7" /></svg>
        </div>

        <div class="wizard-step">
          <div class="step-header">
            <span class="step-num bg-purple">3</span>
            <span class="step-title">确认数据目录</span>
          </div>
          <div class="step-content flex-row">
            <div class="path-display">
              <span class="folder-icon">目录</span>
              <span class="path-text">{{ (pathInfo && pathInfo.wechat_dir) || customWechatDir || '首次启动将自动检测微信目录...' }}</span>
            </div>
            <button class="change-btn" @click.stop.prevent="selectCustomPath">更改</button>
          </div>
        </div>
      </div>

      <div class="status-area">
        <div v-if="importProgress" class="progress-box">
          <p>{{ importProgress.status }}</p>
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: importProgress.percent + '%' }" />
          </div>
        </div>
        <p v-if="wechatErr" class="error-msg">{{ wechatErr }}</p>
        <p v-if="wechatOk" class="success-msg">{{ wechatOk }}</p>
      </div>

      <div class="wizard-actions">
        <button class="btn-primary-large" :disabled="!pathInfo || !selectedWxid || wechatImporting" @click.stop.prevent="startImport">
          {{ wechatImporting ? '导入中...' : (hasImportedBefore ? '重新导入' : '开始导入') }}
        </button>
        <button class="btn-outline-large" :disabled="wechatImporting || verifying" @click.stop.prevent="resetFlow">重新配置</button>
      </div>
    </div>

    <div class="home-section">
      <h2 class="section-title"><span class="dot green"></span>运行日志</h2>
      <div class="log-container">
        <div v-if="!logs.length" class="empty-log">暂无日志</div>
        <ul v-else class="log-list">
          <li v-for="(item, index) in logs" :key="index" class="log-item">
            <span class="log-ts">{{ item.ts }}</span>
            <span class="log-msg">{{ item.msg }}</span>
          </li>
        </ul>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { bridgeReady, api } from '@/api/bridge'
import { showConfirm } from '@/utils/dialog'

type ImportProgress = { status: string; percent: number } | null
type IncrementInfo = {
  incrementSize: number
  changedFiles: Array<{ path: string; delta: number }>
  lastImportAt?: number | null
} | null
type WechatAccount = {
  wxid: string
  label: string
  avatar: string
  wechat_dir: string
  source: string
  db_key: string
  import_completed: boolean
  last_import_at?: number | null
  last_import_total_size: number
  last_import_files: Array<Record<string, any>>
}

const wechatForm = reactive({
  dbKey: '',
  importContacts: true,
  importMessages: true
})

const wechatErr = ref('')
const wechatOk = ref('')
const wechatImporting = ref(false)
const verifying = ref(false)
const importProgress = ref<ImportProgress>(null)
const hasImportedBefore = ref(false)
const incrementInfo = ref<IncrementInfo>(null)
const incrementDismissed = ref(false)
const pathInfo = ref<any>(null)
const customWechatDir = ref('')
const availableAccounts = ref<WechatAccount[]>([])
const activeAccountWxid = ref('')
const selectedWxid = ref('')
const logs = ref<{ ts: string; msg: string }[]>([
  { ts: new Date().toLocaleString(), msg: '系统启动完成，等待导入。' },
  { ts: new Date().toLocaleString(), msg: '已准备微信导入流程。' }
])

function addLog(msg: string) {
  logs.value.unshift({ ts: new Date().toLocaleString(), msg })
}

function formatBytes(size: number) {
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(2)} MB`
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${size} B`
}

function formatImportTime(ts?: number | null) {
  if (!ts) return '未知'
  return new Date(ts * 1000).toLocaleString()
}

function buildPathInfoFromAccount(account?: Partial<WechatAccount> | null) {
  if (!account?.wechat_dir || !account?.wxid) return null
  return {
    wechat_dir: account.wechat_dir,
    current_user: account.wxid,
    account_wxid: account.wxid,
    databases: {},
    source: account.source || 'auto'
  }
}

function getSelectedAccount() {
  return availableAccounts.value.find((account) => account.wxid === selectedWxid.value) || null
}

function getPreferredWechatPaths() {
  if (!pathInfo.value?.wechat_dir || !pathInfo.value?.current_user) return null
  return {
    wechat_dir: pathInfo.value.wechat_dir,
    current_user: pathInfo.value.current_user,
    account_wxid: selectedWxid.value || pathInfo.value.current_user
  }
}

function hydrateAccountState(wxid: string) {
  const account = availableAccounts.value.find((item) => item.wxid === wxid)
  selectedWxid.value = wxid
  activeAccountWxid.value = wxid
  wechatForm.dbKey = account?.db_key || ''
  hasImportedBefore.value = Boolean(account?.import_completed)
  pathInfo.value = buildPathInfoFromAccount(account)
  customWechatDir.value = account?.wechat_dir || ''
  incrementInfo.value = null
  incrementDismissed.value = false
}

async function persistAccounts() {
  const nextAccounts = availableAccounts.value.map((account) => {
    if (account.wxid !== selectedWxid.value) return account
    return {
      ...account,
      db_key: wechatForm.dbKey,
      label: account.label || account.wxid,
    }
  })
  availableAccounts.value = nextAccounts
  await api.set_settings({
    wechat_accounts: nextAccounts,
    wechat_active_account_wxid: activeAccountWxid.value || selectedWxid.value || '',
  })
}

function mergeAccounts(accounts: WechatAccount[]) {
  const merged = new Map<string, WechatAccount>()
  for (const existing of availableAccounts.value) {
    merged.set(existing.wxid, { ...existing })
  }
  for (const account of accounts) {
    const current = merged.get(account.wxid)
    merged.set(account.wxid, {
      ...(current || {}),
      ...account,
      label: account.label || current?.label || account.wxid,
      db_key: account.db_key || current?.db_key || '',
      last_import_files: account.last_import_files || current?.last_import_files || [],
    } as WechatAccount)
  }
  availableAccounts.value = Array.from(merged.values())
}

async function loadWechatAccounts() {
  try {
    await bridgeReady()
    const result = await api.get_wechat_accounts()
    if (!result?.ok) return
    mergeAccounts(result.accounts || [])
    activeAccountWxid.value = result.active_account_wxid || activeAccountWxid.value
    const nextWxid =
      activeAccountWxid.value ||
      selectedWxid.value ||
      (availableAccounts.value.length === 1 ? availableAccounts.value[0]?.wxid : '') ||
      ''
    if (nextWxid) {
      hydrateAccountState(nextWxid)
    }
  } catch (error) {
    console.error('[Home] loadWechatAccounts failed', error)
  }
}

async function detectWechatPath(options?: { silent?: boolean; accountWxid?: string }) {
  try {
    const accountWxid = options?.accountWxid || selectedWxid.value || activeAccountWxid.value || undefined
    const pathRes = await api.get_wechat_paths(accountWxid)
    if (!pathRes?.ok || !pathRes.data) return false

    pathInfo.value = pathRes.data
    mergeAccounts((pathRes.accounts || pathRes.data.accounts || []) as WechatAccount[])

    const detectedWxid =
      pathRes.data.account_wxid ||
      pathRes.data.current_user ||
      accountWxid ||
      (availableAccounts.value.length === 1 ? availableAccounts.value[0]?.wxid : '') ||
      ''

    if (detectedWxid) {
      activeAccountWxid.value = detectedWxid
      selectedWxid.value = detectedWxid
      const detectedAccount = availableAccounts.value.find((account) => account.wxid === detectedWxid)
      customWechatDir.value = pathRes.data.wechat_dir || detectedAccount?.wechat_dir || ''
      if (detectedAccount?.db_key) {
        wechatForm.dbKey = detectedAccount.db_key
      }
    }

    if (!options?.silent) {
      addLog(`已自动检测到微信数据目录：${pathRes.data.wechat_dir}`)
    }
    return true
  } catch (error) {
    console.error('[Home] detectWechatPath failed', error)
    return false
  }
}

async function loadSavedPaths() {
  try {
    await bridgeReady()
    const settings = await api.get_settings()
    mergeAccounts((settings.wechat_accounts || []) as WechatAccount[])
    activeAccountWxid.value = settings.wechat_active_account_wxid || ''

    const targetWxid =
      activeAccountWxid.value ||
      (availableAccounts.value.length === 1 ? availableAccounts.value[0]?.wxid : '') ||
      ''

    if (targetWxid) {
      hydrateAccountState(targetWxid)
      addLog(`已恢复账号配置：${targetWxid}`)
    }

    if (!pathInfo.value) {
      const detected = await detectWechatPath({ accountWxid: targetWxid || undefined })
      if (!detected) {
        addLog('暂未自动检测到微信数据目录，可稍后手动选择。')
      }
    }

    if (selectedWxid.value && hasImportedBefore.value) {
      await checkIncrement()
    }
  } catch (error) {
    console.error('[Home] loadSavedPaths failed', error)
  }
}

async function savePathsToSettings(paths: any, isCustom: boolean) {
  try {
    const wxid = String(paths.current_user || selectedWxid.value || '').trim()
    if (!wxid) return

    const nextAccounts = availableAccounts.value.filter((account) => account.wxid !== wxid)
    nextAccounts.push({
      ...(getSelectedAccount() || {
        wxid,
        label: wxid,
        avatar: '',
        last_import_files: [],
        last_import_total_size: 0,
        import_completed: false,
      }),
      wxid,
      label: getSelectedAccount()?.label || wxid,
      wechat_dir: paths.wechat_dir || '',
      source: isCustom ? 'custom' : 'auto',
      db_key: wechatForm.dbKey,
    } as WechatAccount)

    availableAccounts.value = nextAccounts
    activeAccountWxid.value = wxid
    selectedWxid.value = wxid
    await persistAccounts()
  } catch (error) {
    console.error('[Home] savePathsToSettings failed', error)
  }
}

async function checkIncrement() {
  if (incrementDismissed.value || !selectedWxid.value) return

  try {
    await bridgeReady()
    const result = await api.detect_wechat_import_increment(selectedWxid.value)
    if (result?.ok && result.has_increment) {
      incrementInfo.value = {
        incrementSize: result.increment_size || 0,
        changedFiles: result.changed_files || [],
        lastImportAt: result.last_import_at || null
      }
      addLog('检测到微信数据库有新增内容，可执行增量导入。')
    } else {
      incrementInfo.value = null
    }
  } catch (error) {
    console.error('[Home] checkIncrement failed', error)
  }
}

async function onVerifyAndUnpack() {
  if (verifying.value || wechatImporting.value) return

  wechatErr.value = ''
  wechatOk.value = ''
  importProgress.value = null

  if (!wechatForm.dbKey.trim()) {
    wechatErr.value = '请输入数据库密钥。'
    return
  }

  verifying.value = true
  addLog('正在验证密钥并检查微信数据路径。')

  try {
    await bridgeReady()
    importProgress.value = { status: '验证密钥...', percent: 10 }
    const verifyRes = await api.verify_wechat_key(
      wechatForm.dbKey,
      getPreferredWechatPaths() || undefined,
      selectedWxid.value || undefined,
    )

    if (!verifyRes.ok) {
      wechatErr.value = verifyRes.error || '密钥验证失败。'
      addLog(`密钥验证失败：${wechatErr.value}`)
      return
    }

    const preferredPaths = getPreferredWechatPaths()
    if (preferredPaths) {
      await savePathsToSettings(pathInfo.value, pathInfo.value?.source === 'custom')
      wechatOk.value = '验证成功。已确认微信数据路径，请点击“开始导入”。'
      addLog('密钥验证成功，当前微信数据路径可用。')
      await checkIncrement()
    } else {
      importProgress.value = { status: '查找微信数据路径...', percent: 30 }
      const detected = await detectWechatPath({ silent: true, accountWxid: selectedWxid.value || undefined })
      if (detected) {
        wechatOk.value = '验证成功。已检测到微信数据路径，请点击“开始导入”。'
        addLog('密钥验证成功，已检测到微信数据路径。')
        await checkIncrement()
      } else {
        wechatErr.value = '未能自动检测到微信路径，请手动选择数据目录。'
        addLog('自动检测微信路径失败，请手动指定目录。')
      }
    }
  } catch (error: any) {
    wechatErr.value = error?.message || '验证异常。'
    addLog(`验证异常：${wechatErr.value}`)
  } finally {
    importProgress.value = null
    verifying.value = false
  }
}

async function startImport() {
  if (wechatImporting.value || verifying.value) return
  if (!selectedWxid.value) {
    wechatErr.value = '请先选择要导入的微信账号。'
    return
  }
  if (!pathInfo.value) {
    wechatErr.value = '请先点击“验证”并确认微信数据路径。'
    return
  }
  if (!wechatForm.dbKey.trim()) {
    wechatErr.value = '请输入数据库密钥。'
    return
  }
  if (hasImportedBefore.value) {
    const confirmed = await showConfirm('检测到已有导入记录。继续导入会自动跳过重复数据，是否继续？')
    if (!confirmed) return
  }

  wechatImporting.value = true
  wechatErr.value = ''
  wechatOk.value = ''
  addLog('开始导入微信数据。')

  try {
    await bridgeReady()
    importProgress.value = { status: '正在导入数据...', percent: 20 }
    const res = await api.import_wechat_data(wechatForm.dbKey, {
      import_contacts: wechatForm.importContacts,
      import_messages: wechatForm.importMessages
    }, selectedWxid.value)

    if (!res.ok) {
      wechatErr.value = res.error || '导入失败。'
      addLog(`导入失败：${wechatErr.value}`)
      return
    }

    const stats = res.stats || {}
    wechatOk.value = `导入成功：联系人 ${stats.contacts || 0}，消息 ${stats.messages || 0}，会话 ${stats.conversations || 0}，跳过重复 ${stats.skipped || 0}。`
    hasImportedBefore.value = true
    incrementInfo.value = null
    incrementDismissed.value = false
    await loadWechatAccounts()
    window.dispatchEvent(new CustomEvent('chrono:user-avatar-refresh'))
    addLog(wechatOk.value)
  } catch (error: any) {
    wechatErr.value = error?.message || '导入异常。'
    addLog(`导入异常：${wechatErr.value}`)
  } finally {
    importProgress.value = { status: '完成', percent: 100 }
    setTimeout(() => {
      importProgress.value = null
    }, 1500)
    wechatImporting.value = false
  }
}

async function selectCustomPath() {
  try {
    await bridgeReady()
    const result = await api.select_directory('选择微信数据目录 (WeChat Files)')
    if (!result?.path) return

    customWechatDir.value = result.path
    addLog(`已选择目录：${result.path}`)
    await scanAndSetCustomPath(result.path)
  } catch (error: any) {
    wechatErr.value = `选择目录失败：${error?.message || '未知错误'}`
  }
}

async function scanAndSetCustomPath(wechatDir: string) {
  try {
    addLog('正在扫描微信目录。')
    const scanResult = await api.scan_wechat_directory(wechatDir)
    if (!scanResult.ok || !scanResult.accounts?.length) {
      wechatErr.value = '未在该目录下找到微信数据。'
      addLog('扫描失败：未找到可用的微信账号目录。')
      return
    }

    mergeAccounts((scanResult.accounts || []) as WechatAccount[])
    const nextWxid = selectedWxid.value || scanResult.accounts[0].wxid
    const databases = scanResult.databases[nextWxid]
    const resolvedAccount = (scanResult.accounts || []).find((account: WechatAccount) => account.wxid === nextWxid)
    const resolvedWechatDir = resolvedAccount?.wechat_dir || wechatDir
    const newPathInfo = {
      wechat_dir: resolvedWechatDir,
      current_user: nextWxid,
      account_wxid: nextWxid,
      databases: {
        message: databases.msg_dbs || [],
        contact: databases.contact_db
      },
      source: 'custom'
    }

    selectedWxid.value = nextWxid
    activeAccountWxid.value = nextWxid
    pathInfo.value = newPathInfo
    customWechatDir.value = resolvedWechatDir
    await savePathsToSettings(newPathInfo, true)
    wechatOk.value = `扫描成功，找到 ${scanResult.accounts.length} 个账号，当前使用 ${nextWxid}。`
    addLog(wechatOk.value)
  } catch (error: any) {
    wechatErr.value = `扫描失败：${error?.message || '未知错误'}`
  }
}

function dismissIncrementBanner() {
  incrementDismissed.value = true
  incrementInfo.value = null
  addLog('已忽略本次增量提醒。')
}

function resetFlow() {
  wechatErr.value = ''
  wechatOk.value = ''
  importProgress.value = null
  hasImportedBefore.value = false
  incrementInfo.value = null
  incrementDismissed.value = false

  availableAccounts.value = availableAccounts.value.map((account) => {
    if (account.wxid !== selectedWxid.value) return account
    return {
      ...account,
      db_key: wechatForm.dbKey,
      import_completed: false,
      last_import_at: null,
      last_import_total_size: 0,
      last_import_files: [],
    }
  })

  api.set_settings({
    wechat_accounts: availableAccounts.value,
    wechat_active_account_wxid: activeAccountWxid.value || selectedWxid.value || '',
  }).catch((error: any) => {
    console.error('[Home] resetFlow settings cleanup failed', error)
  })

  addLog('已重置当前账号的导入状态。')
}

async function onAccountSelect(event: Event) {
  const target = event.target as HTMLSelectElement | null
  const wxid = target?.value || ''
  if (!wxid) return

  selectedWxid.value = wxid
  activeAccountWxid.value = wxid
  await api.set_active_wechat_account(wxid)
  hydrateAccountState(wxid)
  await detectWechatPath({ silent: true, accountWxid: wxid })
  if (hasImportedBefore.value) {
    await checkIncrement()
  }
  window.dispatchEvent(new CustomEvent('chrono:user-avatar-refresh'))
}

async function handleGlobalAccountChanged() {
  await loadWechatAccounts()
  if (selectedWxid.value) {
    await detectWechatPath({ silent: true, accountWxid: selectedWxid.value })
    if (hasImportedBefore.value) {
      await checkIncrement()
    }
  }
}

onMounted(() => {
  loadSavedPaths()
  window.addEventListener('chrono:wechat-account-changed', handleGlobalAccountChanged)
})

onUnmounted(() => {
  window.removeEventListener('chrono:wechat-account-changed', handleGlobalAccountChanged)
})
</script>

<style scoped>
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
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.02);
  transition: transform 0.2s;
}

.feature-card:hover {
  transform: translateY(-2px);
}

.icon-wrap {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.bg-yellow {
  background: #eab308;
}

.bg-purple {
  background: #a855f7;
}

.bg-orange {
  background: #f97316;
}

.feature-card h3 {
  margin: 0 0 4px;
  font-size: 16px;
  color: var(--ct-text-primary);
}

.feature-card p {
  margin: 0;
  font-size: 13px;
  color: var(--ct-text-secondary);
}

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

.tool-link:hover {
  background: #e2e8f0;
}

.verify-btn,
.change-btn {
  padding: 8px 16px;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
  background: #fff;
  color: var(--ct-color-primary);
  cursor: pointer;
  white-space: nowrap;
}

.verify-btn:hover:not(:disabled),
.change-btn:hover:not(:disabled) {
  background: #f1f5f9;
}

.verify-btn:disabled,
.change-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

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

.btn-primary-large:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-outline-large {
  background: #fff;
  color: var(--ct-color-primary);
  border: 1px solid var(--ct-color-primary-light);
  padding: 12px 40px;
  border-radius: 30px;
  font-size: 16px;
  cursor: pointer;
}

.btn-outline-large:hover:not(:disabled) {
  background: var(--ct-color-primary-light);
}

.btn-outline-large:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.status-area {
  margin: 10px 0;
}

.account-selector-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 0 0 18px;
}

.account-selector-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--ct-text-secondary);
}

.account-selector-select {
  min-width: 220px;
  height: 40px;
  padding: 0 14px;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  background: #fff;
  color: var(--ct-text-primary);
}

.error-msg {
  color: #ef4444;
  font-size: 14px;
  margin: 10px 0;
}

.success-msg {
  color: #10b981;
  font-size: 14px;
  margin: 10px 0;
}

.increment-banner {
  margin: 10px 0 16px;
  padding: 12px 14px;
  border-radius: 12px;
  background: #fff7ed;
  border: 1px solid #fdba74;
  color: #9a3412;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.increment-copy p {
  margin: 6px 0 0;
  font-size: 13px;
}

.increment-actions {
  display: flex;
  gap: 10px;
}

.progress-box {
  max-width: 400px;
  margin: 0 0 10px;
}

.progress-bar {
  height: 6px;
  background: #e2e8f0;
  border-radius: 3px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--ct-color-primary);
  transition: width 0.3s ease;
}

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
  gap: 16px;
  font-size: 14px;
  color: var(--ct-text-secondary);
}

.log-ts {
  width: 170px;
  color: var(--ct-text-tertiary);
  flex-shrink: 0;
}

.log-msg {
  flex: 1;
}

.empty-log {
  color: var(--ct-text-tertiary);
  font-style: italic;
}

@media (max-width: 1024px) {
  .features-grid {
    gap: 10px;
  }

  .feature-card {
    padding: 15px 10px;
    gap: 10px;
  }

  .icon-wrap {
    width: 36px;
    height: 36px;
  }

  .icon-wrap svg {
    width: 18px;
    height: 18px;
  }

  .feature-card h3 {
    font-size: 14px;
  }

  .feature-card p {
    font-size: 11px;
  }

  .wizard-container {
    gap: 8px;
    margin-bottom: 20px;
  }

  .wizard-step {
    padding: 12px 8px;
    min-height: 80px;
  }

  .step-header {
    margin-bottom: 8px;
    gap: 6px;
  }

  .step-arrow {
    padding: 0 4px;
    transform: none;
  }

  .step-arrow svg {
    width: 16px;
    height: 16px;
  }

  .step-title {
    font-size: 12px;
  }

  .step-content {
    font-size: 11px;
  }

  .step-num {
    width: 20px;
    height: 20px;
    font-size: 10px;
  }

  .tool-link,
  .verify-btn,
  .change-btn {
    padding: 4px 8px;
    font-size: 11px;
  }

  .path-display {
    padding: 4px 6px;
    gap: 4px;
  }

  .increment-banner {
    flex-direction: column;
    align-items: flex-start;
  }

  .log-item {
    flex-wrap: wrap;
    gap: 10px;
  }

  .log-ts {
    width: auto;
  }
}
</style>
