<template>
  <section class="home-page">
    <div class="home-section">
      <h2 class="section-title"><span class="dot pink"></span>关于 Chrono Trace</h2>
      <div class="features-grid">
        <div class="feature-card">
          <div class="icon-wrap bg-yellow">
            <TrendingUp :size="22" />
          </div>
          <div>
            <h3>情绪曲线</h3>
            <p>观察历史情绪波动</p>
          </div>
        </div>
        <div class="feature-card">
          <div class="icon-wrap bg-purple">
            <Headphones :size="22" />
          </div>
          <div>
            <h3>实时监听</h3>
            <p>边聊天边获得建议</p>
          </div>
        </div>
        <div class="feature-card">
          <div class="icon-wrap bg-orange">
            <Sparkles :size="22" />
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
            <span class="step-title">确认数据目录</span>
          </div>
          <div class="step-content flex-row">
            <div class="path-display">
              <FolderOpen :size="16" class="folder-svg" />
              <span class="path-text">{{ (pathInfo && pathInfo.wechat_dir) || customWechatDir || '首次启动将自动检测微信目录...' }}</span>
            </div>
            <button class="change-btn" @click.stop.prevent="selectCustomPath">更改</button>
          </div>
        </div>

        <div class="step-arrow">
          <ChevronsRight :size="20" class="step-chevron" />
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

        <div v-if="manualKeyMode" class="step-arrow">
          <ChevronsRight :size="20" class="step-chevron" />
        </div>

        <div class="wizard-step">
          <div class="step-header">
            <span class="step-num bg-purple">{{ manualKeyMode ? 3 : 2 }}</span>
            <span class="step-title">导入数据库</span>
          </div>
          <div class="step-content">
            点击“开始导入”后，程序会自动引导微信登录并获取密钥完成导入。
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
      <Transition name="kc-fade">
        <div v-if="keyCaptureDialogOpen" class="kc-overlay" @click.self="closeKeyCaptureGuide">
          <div class="kc-dialog" role="dialog" aria-modal="true">
            <!-- Header -->
            <div class="kc-header">
              <div class="kc-header-left">
                <div class="kc-header-badge">
                  <KeyRound :size="22" :stroke-width="2.2" />
                </div>
                <div class="kc-header-text">
                  <h3>微信数据库密钥获取</h3>
                  <p>程序将自动引导微信登录并获取解密密钥</p>
                </div>
              </div>
              <button class="kc-close-btn" title="关闭" @click="closeKeyCaptureGuide">
                <X :size="18" />
              </button>
            </div>

            <!-- Horizontal Stepper -->
            <div class="kc-stepper">
              <div :class="['kc-step-item', { active: isStepActive(1), done: isStepDone(1) }]">
                <div class="kc-step-indicator">
                  <Check v-if="isStepDone(1)" :size="15" :stroke-width="2.5" class="kc-check-icon" />
                  <span v-else>1</span>
                </div>
                <span class="kc-step-title">准备登录</span>
              </div>

              <div :class="['kc-step-connector', { done: isStepDone(1) }]" />

              <div :class="['kc-step-item', { active: isStepActive(2), done: isStepDone(2) }]">
                <div class="kc-step-indicator">
                  <Check v-if="isStepDone(2)" :size="15" :stroke-width="2.5" class="kc-check-icon" />
                  <span v-else>2</span>
                </div>
                <span class="kc-step-title">安装监听</span>
              </div>

              <div :class="['kc-step-connector', { done: isStepDone(2) }]" />

              <div :class="['kc-step-item', { active: isStepActive(3), done: isStepDone(3) }]">
                <div class="kc-step-indicator">
                  <Check v-if="isStepDone(3)" :size="15" :stroke-width="2.5" class="kc-check-icon" />
                  <span v-else>3</span>
                </div>
                <span class="kc-step-title">登录捕获</span>
              </div>
            </div>

            <!-- Dynamic State Card -->
            <div class="kc-card-area">
              <!-- Warning / Confirm Restart -->
              <div v-if="keyCaptureStage === 'confirm_restart'" class="kc-card kc-card-warning">
                <div class="kc-card-badge warning">
                  <AlertTriangle :size="20" />
                </div>
                <div class="kc-card-content">
                  <h4>检测到微信正在运行</h4>
                  <p>自动获取密钥需在微信登录初期注入监听。确认后将关闭并重新启动微信到登录窗口，请再次登录以完成捕获。</p>
                </div>
              </div>

              <!-- Need Start -->
              <div v-else-if="keyCaptureStage === 'need_start'" class="kc-card kc-card-info">
                <div class="kc-card-badge info">
                  <Info :size="20" />
                </div>
                <div class="kc-card-content">
                  <h4>未检测到微信进程</h4>
                  <p>请先打开电脑端微信并停留在登录界面，然后点击下方“重新检测”继续。</p>
                </div>
              </div>

              <!-- Fallback / Error -->
              <div v-else-if="keyCaptureStage === 'fallback' || keyCaptureError" class="kc-card kc-card-error">
                <div class="kc-card-badge error">
                  <AlertCircle :size="20" />
                </div>
                <div class="kc-card-content">
                  <h4>{{ keyCaptureError || '自动获取密钥未能完成' }}</h4>
                  <p>未能自动捕获到密钥，您可以切换到手动输入数据库密钥，或稍后重试。</p>
                </div>
              </div>

              <!-- In-progress (checking, restarting, installing, hook_ready, capturing) -->
              <div v-else class="kc-card kc-card-loading">
                <div class="kc-pulse-wrap">
                  <span class="kc-pulse-ring" />
                  <span class="kc-pulse-core" />
                </div>
                <div class="kc-card-content">
                  <h4>{{ keyCaptureMessage }}</h4>
                  <p>{{ keyCaptureStage === 'hook_ready' || keyCaptureStage === 'capturing' ? '监听已就绪，请在微信中完成登录。捕获完成后将自动开始导入。' : '正在准备注入监听环境，请保持此窗口打开...' }}</p>
                </div>
              </div>
            </div>

            <!-- Actions -->
            <div class="kc-actions">
              <template v-if="keyCaptureStage === 'confirm_restart'">
                <button class="kc-btn kc-btn-ghost" @click="closeKeyCaptureGuide">取消</button>
                <button class="kc-btn kc-btn-primary" @click="confirmWechatRestart">关闭并重启微信</button>
              </template>
              <template v-else-if="keyCaptureStage === 'need_start'">
                <button class="kc-btn kc-btn-ghost" @click="closeKeyCaptureGuide">关闭</button>
                <button class="kc-btn kc-btn-primary" @click="openKeyCaptureGuide">重新检测</button>
              </template>
              <template v-else-if="keyCaptureStage === 'fallback'">
                <button class="kc-btn kc-btn-ghost" @click="closeKeyCaptureGuide">稍后处理</button>
                <button class="kc-btn kc-btn-primary" @click="enableManualKeyFallback">改用手动输入</button>
              </template>
              <template v-else>
                <button class="kc-btn kc-btn-ghost" @click="closeKeyCaptureGuide">取消获取</button>
              </template>
            </div>
          </div>
        </div>
      </Transition>
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
import {
  KeyRound,
  X,
  Check,
  AlertTriangle,
  AlertCircle,
  Info,
  FolderOpen,
  ChevronsRight,
  TrendingUp,
  Headphones,
  Sparkles
} from 'lucide-vue-next'
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
const legacyV3Info = ref<{ wechat_dir?: string; users?: string[] } | null>(null)
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
    if (!pathRes?.ok || !pathRes.data) {
      if (pathRes?.code === 'legacy_wechat_v3') {
        legacyV3Info.value = pathRes.v3 || null
        wechatErr.value = '检测到旧版微信 3.9 数据目录，请将微信升级到 4.0 及以上版本后重试。'
        addLog(`检测到旧版微信 3.9 数据目录：${pathRes.v3?.wechat_dir || '未知位置'}`)
      }
      return false
    }

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

function legacyV3GuidanceMessage(v3: { wechat_dir?: string; users?: string[] } | null | undefined) {
  const dir = v3?.wechat_dir || '（未知位置）'
  const users = v3?.users || []
  const accountNote = users.length
    ? `检测到 ${users.length} 个账号：${users.slice(0, 3).join('、')}${users.length > 3 ? ' 等' : ''}`
    : ''
  return [
    '已检测到旧版微信（3.9）的数据目录：',
    dir,
    accountNote,
    '',
    'Chrono Trace 仅支持微信 4.0 及以上版本：新版数据结构与密钥获取方式不同，旧版数据库无法导入。',
    '',
    '请升级微信后重试：微信「设置 → 关于微信 → 检查更新」，或前往 weixin.qq.com 下载最新版，登录同一账号后再回到本页。'
  ].filter(Boolean).join('\n')
}

async function showLegacyV3Guidance(v3: { wechat_dir?: string; users?: string[] } | null | undefined) {
  const dir = v3?.wechat_dir || '（未识别具体目录）'
  const users = Array.isArray(v3?.users) ? v3!.users : []
  const accountNote = users.length
    ? `检测到 ${users.length} 个账号：${users.slice(0, 3).join('、')}${users.length > 3 ? ' 等' : ''}`
    : ''
  await showDialog({
    title: '请升级微信至 4.0 及以上版本',
    type: 'wechat_upgrade',
    detectedPath: dir,
    detectedAccounts: accountNote,
    quickLinkTitle: '微信，是一个生活方式',
    quickLinkUrl: 'https://weixin.qq.com/',
    message: legacyV3GuidanceMessage(v3)
  })
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
        if (legacyV3Info.value) {
          await showLegacyV3Guidance(legacyV3Info.value)
        } else {
          addLog('暂未自动检测到微信数据目录，可稍后手动选择。')
          await promptManualWechatPathSelection('startup')
        }
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

function isStepActive(step: number): boolean {
  if (step === 1) return ['checking', 'need_start', 'confirm_restart', 'restarting'].includes(keyCaptureStage.value)
  if (step === 2) return keyCaptureStage.value === 'installing'
  if (step === 3) return ['hook_ready', 'capturing'].includes(keyCaptureStage.value)
  return false
}

function isStepDone(step: number): boolean {
  if (step === 1) return ['installing', 'hook_ready', 'capturing', 'completed'].includes(keyCaptureStage.value)
  if (step === 2) return ['hook_ready', 'capturing', 'completed'].includes(keyCaptureStage.value)
  if (step === 3) return keyCaptureStage.value === 'completed'
  return false
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
      if (captureState.restart_required === false) {
        // Linux：免重启流程——静态断点等待「退出登录后重新登录」即可
        await startKeyCaptureSession()
        return
      }
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

  if (!pathInfo.value) {
    const detected = await detectWechatPath({ silent: true, accountWxid: selectedWxid.value || undefined })
    if (!detected) {
      wechatErr.value = '未能自动检测到微信数据路径，请先在步骤 1 中确认数据目录。'
      await promptManualWechatPathSelection('startup')
      return
    }
  }

  if (!selectedWxid.value) {
    await loadWechatAccounts()
  }

  if (!wechatForm.dbKey.trim()) {
    if (manualKeyMode.value) {
      wechatErr.value = '请输入数据库密钥。'
      return
    }
    await openKeyCaptureGuide()
    return
  }
  if (!selectedWxid.value && !pathInfo.value?.current_user) {
    wechatErr.value = '暂未识别到微信账号，请先完成微信登录。'
    return
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
      if (scanResult.code === 'legacy_wechat_v3') {
        legacyV3Info.value = scanResult.v3 || null
        wechatErr.value = '该目录为旧版微信 3.9 数据目录，请将微信升级到 4.0 及以上版本后重试。'
        addLog(`所选目录为旧版微信 3.9 数据：${scanResult.v3?.wechat_dir || wechatDir}`)
        await showLegacyV3Guidance(scanResult.v3)
        return
      }
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
  color: #ffffff;
}

.icon-wrap svg {
  color: #ffffff;
  stroke: #ffffff;
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

/* ====================================================
   微信密钥获取 二级弹窗 (Modern Stepper Dialog)
==================================================== */
.kc-fade-enter-active,
.kc-fade-leave-active {
  transition: opacity 0.22s ease;
}

.kc-fade-enter-from,
.kc-fade-leave-to {
  opacity: 0;
}

.kc-fade-enter-active .kc-dialog {
  animation: kc-dialog-in 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.kc-fade-leave-active .kc-dialog {
  animation: kc-dialog-out 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes kc-dialog-in {
  from {
    opacity: 0;
    transform: scale(0.95) translateY(10px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

@keyframes kc-dialog-out {
  from {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
  to {
    opacity: 0;
    transform: scale(0.96) translateY(6px);
  }
}

.kc-overlay {
  position: fixed;
  inset: 0;
  z-index: 100000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(15, 23, 42, 0.45);
  backdrop-filter: blur(8px);
}

.kc-dialog {
  width: min(520px, 94vw);
  background: #ffffff;
  border: 1px solid rgba(226, 232, 240, 0.85);
  border-radius: 20px;
  padding: 24px 26px;
  box-shadow: 0 25px 60px -12px rgba(15, 23, 42, 0.22), 0 0 0 1px rgba(124, 77, 255, 0.05);
  display: flex;
  flex-direction: column;
}

.kc-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.kc-header-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.kc-header-badge {
  width: 44px;
  height: 44px;
  border-radius: 13px;
  background: linear-gradient(135deg, #8b5cf6 0%, #6d28d9 100%);
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 6px 16px -2px rgba(109, 40, 217, 0.35);
}

.kc-header-text h3 {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  color: var(--ct-text-primary, #0f172a);
}

.kc-header-text p {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--ct-text-secondary, #64748b);
  line-height: 1.4;
}

.kc-close-btn {
  background: transparent;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  padding: 6px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  margin-top: -2px;
  margin-right: -4px;
}

.kc-close-btn:hover {
  background: #f1f5f9;
  color: #334155;
}

/* Stepper */
.kc-stepper {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 22px 0 20px;
  padding: 0 8px;
}

.kc-step-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.kc-step-indicator {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #f1f5f9;
  border: 1.5px solid #e2e8f0;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.25s ease;
}

.kc-step-title {
  font-size: 12px;
  color: #94a3b8;
  font-weight: 500;
  transition: color 0.25s ease;
}

.kc-step-item.active .kc-step-indicator {
  background: var(--ct-color-primary, #7c4dff);
  border-color: var(--ct-color-primary, #7c4dff);
  color: #ffffff;
  box-shadow: 0 0 0 4px rgba(124, 77, 255, 0.18);
}

.kc-step-item.active .kc-step-title {
  color: var(--ct-color-primary, #7c4dff);
  font-weight: 600;
}

.kc-step-item.done .kc-step-indicator {
  background: #10b981;
  border-color: #10b981;
  color: #ffffff;
}

.kc-step-item.done .kc-step-title {
  color: #10b981;
  font-weight: 500;
}

.kc-check-icon {
  width: 16px;
  height: 16px;
}

.kc-step-connector {
  flex: 1;
  height: 2px;
  margin: 0 10px 18px;
  background: #e2e8f0;
  transition: background 0.3s ease;
}

.kc-step-connector.done {
  background: #10b981;
}

/* Card Area */
.kc-card-area {
  margin-bottom: 20px;
}

.kc-card {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 16px;
  border-radius: 14px;
  line-height: 1.5;
}

.kc-card-content h4 {
  margin: 0 0 4px;
  font-size: 14px;
  font-weight: 600;
}

.kc-card-content p {
  margin: 0;
  font-size: 13px;
  color: var(--ct-text-secondary, #475569);
  line-height: 1.5;
}

.kc-card-loading {
  background: rgba(124, 77, 255, 0.05);
  border: 1px solid rgba(124, 77, 255, 0.18);
}

.kc-card-loading .kc-card-content h4 {
  color: var(--ct-color-primary, #7c4dff);
}

.kc-pulse-wrap {
  position: relative;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 1px;
}

.kc-pulse-core {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--ct-color-primary, #7c4dff);
}

.kc-pulse-ring {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 2px solid var(--ct-color-primary, #7c4dff);
  animation: kc-pulse 1.8s cubic-bezier(0.24, 0, 0.38, 1) infinite;
}

@keyframes kc-pulse {
  0% {
    transform: scale(0.6);
    opacity: 0.9;
  }
  100% {
    transform: scale(1.6);
    opacity: 0;
  }
}

.kc-card-badge {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 1px;
}

.kc-card-warning {
  background: #fffbeb;
  border: 1px solid #fde68a;
}

.kc-card-warning .kc-card-content h4 {
  color: #b45309;
}

.kc-card-badge.warning {
  color: #d97706;
}

.kc-card-info {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
}

.kc-card-info .kc-card-content h4 {
  color: #15803d;
}

.kc-card-badge.info {
  color: #16a34a;
}

.kc-card-error {
  background: #fef2f2;
  border: 1px solid #fecaca;
}

.kc-card-error .kc-card-content h4 {
  color: #b91c1c;
}

.kc-card-badge.error {
  color: #dc2626;
}

/* Actions */
.kc-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

.kc-btn {
  height: 38px;
  padding: 0 18px;
  border-radius: 10px;
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.kc-btn-ghost {
  background: #f8fafc;
  color: #475569;
  border: 1px solid #e2e8f0;
}

.kc-btn-ghost:hover {
  background: #f1f5f9;
  color: #0f172a;
  border-color: #cbd5e1;
}

.kc-btn-primary {
  background: var(--ct-color-primary, #7c4dff);
  color: #ffffff;
  border: none;
  box-shadow: 0 4px 12px rgba(124, 77, 255, 0.25);
}

.kc-btn-primary:hover {
  background: var(--ct-color-primary-hover, #651fff);
  box-shadow: 0 6px 16px rgba(124, 77, 255, 0.35);
  transform: translateY(-1px);
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
