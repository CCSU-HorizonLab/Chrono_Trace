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
        <CtAccountSelector
          v-model="selectedWxid"
          :accounts="availableAccounts"
          @update:modelValue="onAccountSelectValue"
        />
      </div>

      <div class="wizard-container">
        <div class="wizard-step">
          <div class="step-header">
            <span class="step-num bg-purple">1</span>
            <span class="step-title">获取数据库密钥</span>
          </div>
          <div class="step-content">
            点击“开始导入”后，程序会自动引导微信登录并获取密钥。
          </div>
        </div>

        <div v-if="manualKeyMode" class="step-arrow">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ccc" stroke-width="2"><polyline points="13 17 18 12 13 7" /><polyline points="6 17 11 12 6 7" /></svg>
        </div>

        <div v-if="manualKeyMode" class="wizard-step">
          <div class="step-header">
            <span class="step-num bg-orange">异常</span>
            <span class="step-title">手动验证数据库密钥</span>
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
        <button class="btn-primary-large" :disabled="wechatImporting || capturingKey" @click.stop.prevent="startImport">
          {{ wechatImporting ? '导入中...' : (hasImportedBefore ? '重新导入' : '开始导入') }}
        </button>
        <button class="btn-outline-large" :disabled="wechatImporting || verifying || capturingKey" @click.stop.prevent="resetFlow">重新配置</button>
      </div>
    </div>

    <Teleport to="body">
      <div v-if="keyCaptureDialogOpen" class="key-capture-overlay">
        <div class="key-capture-dialog" role="dialog" aria-modal="true">
          <div class="key-capture-header">
            <span class="key-capture-badge">密钥</span>
            <div>
              <h3>微信数据库密钥获取</h3>
              <p>请按提示完成微信登录，窗口会一直保持到密钥捕获完成。</p>
            </div>
          </div>
          <div class="key-capture-steps">
            <div :class="['key-capture-step', { active: keyCaptureStage === 'restarting' || keyCaptureStage === 'confirm_restart', done: ['installing', 'hook_ready', 'capturing', 'completed'].includes(keyCaptureStage) }]">
              <span>1</span><strong>准备微信登录窗口</strong>
            </div>
            <div :class="['key-capture-step', { active: keyCaptureStage === 'installing', done: ['hook_ready', 'capturing', 'completed'].includes(keyCaptureStage) }]">
              <span>2</span><strong>安装数据库监听</strong>
            </div>
            <div :class="['key-capture-step', { active: keyCaptureStage === 'hook_ready' || keyCaptureStage === 'capturing', done: keyCaptureStage === 'completed' }]">
              <span>3</span><strong>登录并捕获密钥</strong>
            </div>
          </div>
          <div class="key-capture-message">{{ keyCaptureMessage }}</div>
          <div v-if="keyCaptureError" class="key-capture-error">{{ keyCaptureError }}</div>
          <div v-if="keyCaptureStage === 'confirm_restart'" class="key-capture-actions">
            <button class="btn-outline-large" @click="closeKeyCaptureGuide">取消</button>
            <button class="btn-primary-large" @click="confirmWechatRestart">关闭并重启微信</button>
          </div>
          <div v-else-if="keyCaptureStage === 'need_start'" class="key-capture-actions">
            <button class="btn-outline-large" @click="closeKeyCaptureGuide">关闭</button>
            <button class="btn-primary-large" @click="openKeyCaptureGuide">重新检测</button>
          </div>
          <div v-else-if="keyCaptureStage === 'fallback'" class="key-capture-actions">
            <button class="btn-outline-large" @click="closeKeyCaptureGuide">稍后处理</button>
            <button class="btn-primary-large" @click="enableManualKeyFallback">改用手动输入</button>
          </div>
        </div>
      </div>
    </Teleport>

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
import { showConfirm, showDialog } from '@/utils/dialog'
import CtAccountSelector from '@/components/base/CtAccountSelector.vue'
import { clearWechatAccountProfileCache, enrichWechatAccountsWithProfiles } from '@/utils/wechatAccounts'

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
  profile_name?: string
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
const capturingKey = ref(false)
const manualKeyMode = ref(false)
const keyCaptureDialogOpen = ref(false)
const keyCaptureStage = ref('checking')
const keyCaptureMessage = ref('正在检查微信登录状态。')
const keyCaptureError = ref('')
const keyCaptureSessionId = ref('')
let keyCapturePollTimer: ReturnType<typeof setTimeout> | null = null
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
      profile_name: account.profile_name || current?.profile_name || '',
      last_import_files: account.last_import_files || current?.last_import_files || [],
    } as WechatAccount)
  }
  availableAccounts.value = Array.from(merged.values())
}

async function loadWechatAccounts(options: { forceProfiles?: boolean } = {}) {
  try {
    await bridgeReady()
    const result = await api.get_wechat_accounts()
    if (!result?.ok) return
    mergeAccounts(await enrichWechatAccountsWithProfiles(
      (result.accounts || []) as WechatAccount[],
      { forceRefresh: options.forceProfiles },
    ))
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
    mergeAccounts(await enrichWechatAccountsWithProfiles((pathRes.accounts || pathRes.data.accounts || []) as WechatAccount[]))

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

async function promptManualWechatPathSelection(context: 'startup' | 'verify') {
  const confirmed = await showConfirm({
    title: '未找到微信数据库',
    message:
      context === 'verify'
        ? '程序已经验证了密钥，但没有自动找到微信数据库目录。\n\n通常需要选择 WeChat Files 目录，再由程序自动识别账号和数据库。\n常见位置：\nC:\\Users\\你的用户名\\Documents\\WeChat Files\n\n现在就手动选择目录吗？'
        : '程序暂时没有自动找到微信数据库目录。\n\n通常需要选择 WeChat Files 目录，再由程序自动识别账号和数据库。\n常见位置：\nC:\\Users\\你的用户名\\Documents\\WeChat Files\n\n现在就手动选择目录吗？',
  })

  if (!confirmed) {
    wechatErr.value = '未能自动检测到微信路径，请点击“更改”手动选择 WeChat Files 目录。'
    addLog('用户取消手动选择微信目录，等待后续操作。')
    return
  }

  await showDialog({
    title: '手动匹配目录',
    message: '请在下一步选择微信的 WeChat Files 目录。选中后程序会自动扫描其中的账号与数据库文件。',
  })
  await selectCustomPath()
}

async function loadSavedPaths() {
  try {
    await bridgeReady()
    const settings = await api.get_settings()
    mergeAccounts(await enrichWechatAccountsWithProfiles((settings.wechat_accounts || []) as WechatAccount[]))
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
        await promptManualWechatPathSelection('startup')
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
        await promptManualWechatPathSelection('verify')
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

function stopKeyCapturePolling() {
  if (keyCapturePollTimer) {
    clearTimeout(keyCapturePollTimer)
    keyCapturePollTimer = null
  }
}

function closeKeyCaptureGuide() {
  stopKeyCapturePolling()
  keyCaptureDialogOpen.value = false
  capturingKey.value = false
  importProgress.value = null
}

function showKeyCaptureFailure(message: string) {
  stopKeyCapturePolling()
  keyCaptureStage.value = 'fallback'
  keyCaptureError.value = message
  keyCaptureMessage.value = '自动获取没有完成，可以切换到手动输入数据库密钥。'
  addLog(`自动获取数据库密钥失败：${message}`)
}

function enableManualKeyFallback() {
  manualKeyMode.value = true
  closeKeyCaptureGuide()
  wechatErr.value = keyCaptureError.value || '请手动输入数据库密钥后再验证。'
  addLog('已切换到手动输入数据库密钥模式。')
}

async function startKeyCaptureSession() {
  keyCaptureStage.value = 'installing'
  keyCaptureError.value = ''
  keyCaptureMessage.value = '正在安装数据库密钥监听，请保持此窗口打开。'
  importProgress.value = { status: '正在安装数据库密钥监听...', percent: 35 }
  addLog('开始安装数据库密钥监听。')

  const result = await api.start_wechat_db_key_capture(selectedWxid.value || undefined, 120)
  if (!result?.ok || !result.session_id) {
    showKeyCaptureFailure(result?.error || '数据库密钥监听安装失败。')
    return
  }

  keyCaptureSessionId.value = String(result.session_id)
  keyCaptureStage.value = 'hook_ready'
  keyCaptureMessage.value = '数据库密钥监听已安装，请在微信中完成登录。登录完成前请不要关闭此窗口。'
  importProgress.value = { status: '监听已安装，请登录微信...', percent: 55 }
  addLog('数据库密钥监听已安装，等待微信登录触发密钥读取。')
  pollKeyCaptureSession()
}

async function pollKeyCaptureSession() {
  stopKeyCapturePolling()
  if (!keyCaptureSessionId.value || !keyCaptureDialogOpen.value) return

  try {
    const result = await api.get_wechat_db_key_capture_session(keyCaptureSessionId.value)
    if (result?.status === 'completed' && result.ok) {
      keyCaptureStage.value = 'completed'
      keyCaptureMessage.value = '数据库密钥已获取并验证成功，正在自动开始解包导入。'
      importProgress.value = { status: '密钥已验证，正在开始解包导入...', percent: 75 }
      addLog('数据库密钥已捕获并验证成功，准备自动开始导入。')
      wechatForm.dbKey = String(result.db_key || '')
      manualKeyMode.value = false
      if (result.account_wxid) {
        selectedWxid.value = String(result.account_wxid)
        activeAccountWxid.value = String(result.account_wxid)
      }
      await loadWechatAccounts()
      closeKeyCaptureGuide()
      await startImport(true)
      return
    }
    if (result?.status === 'failed' || result?.status === 'timed_out') {
      showKeyCaptureFailure(result?.error || result?.message || '数据库密钥获取失败。')
      return
    }
    keyCaptureStage.value = result?.status === 'hook_ready' ? 'hook_ready' : 'capturing'
    keyCaptureMessage.value = result?.message || '正在等待微信登录触发数据库密钥。'
    keyCapturePollTimer = setTimeout(pollKeyCaptureSession, 500)
  } catch (error: any) {
    showKeyCaptureFailure(error?.message || '读取数据库密钥获取状态失败。')
  }
}

async function confirmWechatRestart() {
  keyCaptureStage.value = 'restarting'
  keyCaptureError.value = ''
  keyCaptureMessage.value = '正在关闭当前微信并重新启动到登录窗口，请稍候。'
  importProgress.value = { status: '正在关闭并重新启动微信...', percent: 15 }
  addLog('用户确认重启微信，正在准备登录窗口。')

  try {
    const restarted = await api.restart_wechat_for_key_capture()
    if (!restarted?.ok) {
      showKeyCaptureFailure(restarted?.error || '微信重启失败。')
      return
    }
    keyCaptureMessage.value = '微信已启动到登录窗口，正在安装数据库密钥监听。'
    await startKeyCaptureSession()
  } catch (error: any) {
    showKeyCaptureFailure(error?.message || '微信重启失败。')
  }
}

async function openKeyCaptureGuide() {
  if (capturingKey.value && !keyCaptureDialogOpen.value) return
  capturingKey.value = true
  wechatErr.value = ''
  wechatOk.value = ''
  keyCaptureDialogOpen.value = true
  keyCaptureStage.value = 'checking'
  keyCaptureError.value = ''
  keyCaptureMessage.value = '正在检查微信登录状态。'

  try {
    await bridgeReady()
    const captureState = await api.get_wechat_key_capture_status()
    if (!captureState?.ok) {
      showKeyCaptureFailure(captureState?.error || '无法检测微信登录状态。')
      return
    }
    if (!captureState.running) {
      keyCaptureStage.value = 'need_start'
      keyCaptureMessage.value = '未检测到微信进程，请先启动微信并停留在登录界面。'
      return
    }
    if (captureState.login_state === 'logged_in') {
      keyCaptureStage.value = 'confirm_restart'
      keyCaptureMessage.value = '检测到微信已经登录。确认后会关闭并重新启动微信，再安装监听。'
      return
    }
    await startKeyCaptureSession()
  } catch (error: any) {
    showKeyCaptureFailure(error?.message || '准备数据库密钥监听失败。')
  }
}

async function startImport(autoFromCapture = false) {
  if (wechatImporting.value || verifying.value || (capturingKey.value && !autoFromCapture)) return
  if (!wechatForm.dbKey.trim()) {
    if (manualKeyMode.value) {
      wechatErr.value = '请输入数据库密钥。'
      return
    }
    await openKeyCaptureGuide()
    return
  }
  if (!selectedWxid.value) {
    await loadWechatAccounts()
  }
  if (!selectedWxid.value) {
    wechatErr.value = '暂未识别到微信账号，请先完成微信登录。'
    return
  }
  if (!pathInfo.value) {
    const detected = await detectWechatPath({ silent: true, accountWxid: selectedWxid.value })
    if (!detected) {
      wechatErr.value = '未能自动检测到微信数据路径，请手动选择目录。'
      return
    }
  }
  if (hasImportedBefore.value && !autoFromCapture) {
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
    wechatOk.value = `导入成功：当前共联系人 ${stats.contacts || 0}，消息 ${stats.messages || 0}，会话 ${stats.conversations || 0}；本次新增联系人 ${stats.inserted_contacts || 0}，消息 ${stats.inserted_messages || 0}，跳过重复 ${stats.skipped || 0}。`
    hasImportedBefore.value = true
    incrementInfo.value = null
    incrementDismissed.value = false
    clearWechatAccountProfileCache(selectedWxid.value)
    await loadWechatAccounts({ forceProfiles: true })
    window.dispatchEvent(new CustomEvent('chrono:user-avatar-refresh', {
      detail: { wxid: selectedWxid.value, forceProfiles: true },
    }))
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

    mergeAccounts(await enrichWechatAccountsWithProfiles((scanResult.accounts || []) as WechatAccount[]))
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
  closeKeyCaptureGuide()
  manualKeyMode.value = false
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

async function onAccountSelectValue(wxid: string) {
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

async function handleWechatSettingsSaved(event?: Event) {
  const detail = (event as CustomEvent | undefined)?.detail || {}
  await loadWechatAccounts()
  const nextWxid =
    String(detail.wxid || '').trim() ||
    activeAccountWxid.value ||
    selectedWxid.value ||
    ''

  if (!nextWxid) return

  hydrateAccountState(nextWxid)
  if (!pathInfo.value) {
    await detectWechatPath({ silent: true, accountWxid: nextWxid })
  }
}

onMounted(() => {
  loadSavedPaths()
  window.addEventListener('chrono:wechat-account-changed', handleGlobalAccountChanged)
  window.addEventListener('chrono:wechat-settings-saved', handleWechatSettingsSaved)
})

onUnmounted(() => {
  stopKeyCapturePolling()
  window.removeEventListener('chrono:wechat-account-changed', handleGlobalAccountChanged)
  window.removeEventListener('chrono:wechat-settings-saved', handleWechatSettingsSaved)
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

.key-capture-overlay {
  position: fixed;
  inset: 0;
  z-index: 100000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(15, 23, 42, 0.55);
  backdrop-filter: blur(5px);
}

.key-capture-dialog {
  width: min(520px, 94vw);
  padding: 26px;
  border: 1px solid rgba(148, 163, 184, 0.25);
  border-radius: 20px;
  background: #fff;
  box-shadow: 0 24px 70px rgba(15, 23, 42, 0.24);
}

.key-capture-header {
  display: flex;
  align-items: flex-start;
  gap: 14px;
}

.key-capture-badge {
  display: inline-flex;
  width: 42px;
  height: 42px;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border-radius: 14px;
  color: #fff;
  background: #a855f7;
  font-size: 13px;
  font-weight: 700;
}

.key-capture-header h3 {
  margin: 0;
  color: var(--ct-text-primary);
  font-size: 18px;
}

.key-capture-header p {
  margin: 6px 0 0;
  color: var(--ct-text-secondary);
  font-size: 13px;
  line-height: 1.5;
}

.key-capture-steps {
  display: grid;
  gap: 10px;
  margin: 24px 0 18px;
}

.key-capture-step {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  color: #94a3b8;
  background: #f8fafc;
  font-size: 13px;
}

.key-capture-step span {
  display: inline-flex;
  width: 22px;
  height: 22px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #e2e8f0;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}

.key-capture-step.active {
  color: #7e22ce;
  background: #faf5ff;
}

.key-capture-step.active span,
.key-capture-step.done span {
  color: #fff;
  background: #a855f7;
}

.key-capture-step.done {
  color: #15803d;
  background: #f0fdf4;
}

.key-capture-message {
  min-height: 48px;
  padding: 14px;
  border-radius: 10px;
  color: var(--ct-text-primary);
  background: #f8fafc;
  line-height: 1.6;
  white-space: pre-line;
}

.key-capture-error {
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: 10px;
  color: #b91c1c;
  background: #fef2f2;
  line-height: 1.5;
}

.key-capture-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 20px;
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
