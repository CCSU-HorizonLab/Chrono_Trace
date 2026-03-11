<template>
  <section class="home-page">
    <!-- 标题与介绍 -->
    <header class="page-title">
      <h1>首页</h1>
    </header>

    <div class="grid">
      <!-- 应用介绍 -->
      <CtCard title="关于 Chrono_Trace">
        <template #default>
          <p class="slogan">“镌刻对话年轮，丈量心动间距”</p>
          <ul class="intro">
            <li>导入历史聊天数据，生成情绪曲线、词云与分段总结。</li>
            <li>结合近期对话，提供个性化沟通建议（亲密/维持/疏远）。</li>
            <li>设置中可配置模型、API Token 与抓取策略。</li>
          </ul>
        </template>
      </CtCard>

      <!-- 微信数据导入 -->
      <CtCard title="微信数据导入">
        <div class="form">
          <!-- 提示信息 -->
          <div class="hint-box">
            <p><strong>📌 操作流程：</strong></p>
            <p>1️⃣ 使用 <a href="https://github.com/ycccccccy/wx_key" target="_blank">wx_key 工具</a> 获取微信数据库密钥</p>
            <p>2️⃣ 输入密钥后点击"验证并解包"</p>
            <p>3️⃣ 如果自动检测失败，可手动选择微信数据目录</p>
          </div>

          <!-- 密钥输入 -->
          <label class="row">
            <div class="lab">数据库密钥</div>
            <CtField 
              v-model="wechatForm.dbKey" 
              placeholder="输入64位hex密钥 (例如: 1a2b3c4d...)" 
              type="password"
            />
          </label>

          <!-- 路径状态显示 -->
          <div v-if="pathInfo" class="path-info">
            <div class="info-item">
              <span class="label">数据源：</span>
              <span class="value">{{ pathInfo.source === 'custom' ? '自定义路径' : '自动检测' }}</span>
            </div>
            <div v-if="pathInfo.wechat_dir" class="info-item">
              <span class="label">微信目录：</span>
              <span class="value">{{ pathInfo.wechat_dir }}</span>
            </div>
            <div v-if="pathInfo.current_user" class="info-item">
              <span class="label">当前用户：</span>
              <span class="value">{{ pathInfo.current_user }}</span>
            </div>
          </div>

          <!-- 自定义路径选择（仅在自动检测失败时显示） -->
          <div v-if="showCustomPath" class="custom-path-box">
            <p class="warning">⚠️ 自动检测失败，请手动选择微信数据目录</p>
            <div class="path-input-group">
              <CtField 
                v-model="customWechatDir" 
                placeholder="微信数据目录 (如: C:\Users\xxx\Documents\WeChat Files)" 
                readonly
              />
              <CtButton variant="ghost" @click.stop.prevent="selectCustomPath">选择目录</CtButton>
            </div>
          </div>

          <!-- 操作按钮 -->
          <div class="actions">
            <CtButton 
              :loading="verifying || wechatImporting" 
              :disabled="!wechatForm.dbKey.trim()"
              @click.stop.prevent="onVerifyAndUnpack"
            >
              {{ pathInfo ? '开始导入' : '验证并解包' }}
            </CtButton>
            <CtButton 
              v-if="pathInfo" 
              variant="ghost" 
              @click.stop.prevent="resetFlow"
            >
              重新配置
            </CtButton>
          </div>

          <!-- 进度显示 -->
          <div v-if="importProgress" class="progress-box">
            <p>{{ importProgress.status }}</p>
            <div class="progress-bar">
              <div class="progress-fill" :style="{ width: importProgress.percent + '%' }"></div>
            </div>
          </div>

          <p v-if="wechatErr" class="error">{{ wechatErr }}</p>
          <p v-if="wechatOk" class="ok">{{ wechatOk }}</p>
        </div>
      </CtCard>



      <!-- 运行日志 -->
      <CtCard title="运行日志">
        <div class="logs">
          <div v-if="!logs.length" class="empty">暂无日志</div>
          <ul v-else>
            <li v-for="(l, i) in logs" :key="i">
              <span class="ts">{{ l.ts }}</span>
              <span class="msg">{{ l.msg }}</span>
            </li>
          </ul>
        </div>
      </CtCard>
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
const logs = ref<{ ts: string; msg: string }[]>([])

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
  // 防止重复触发
  if (verifying.value || wechatImporting.value) {
    console.log('[DEBUG] 操作进行中，忽略重复点击')
    return
  }

  wechatErr.value = ''
  wechatOk.value = ''
  importProgress.value = null

  if (!wechatForm.dbKey.trim()) {
    wechatErr.value = '请输入数据库密钥'
    return
  }

  // 如果已经有路径信息，直接开始导入
  if (pathInfo.value) {
    await startImport()
    return
  }

  // 否则先验证密钥和路径
  verifying.value = true
  addLog('正在验证密钥和查找微信数据...')

  try {
    await bridgeReady()
    
    // 1. 验证密钥
    importProgress.value = { status: '验证密钥...', percent: 10 }
    const verifyRes = await api.verify_wechat_key(wechatForm.dbKey)
    
    if (!verifyRes.ok) {
      wechatErr.value = verifyRes.error || '密钥验证失败'
      addLog('密钥验证失败: ' + wechatErr.value)
      importProgress.value = null
      verifying.value = false
      return
    }

    addLog('✅ 密钥验证成功')
    
    // 2. 获取微信路径
    importProgress.value = { status: '查找微信数据路径...', percent: 30 }
    const pathRes = await api.get_wechat_paths()
    
    if (pathRes.ok && pathRes.data) {
      // 自动检测成功
      pathInfo.value = pathRes.data
      addLog('✅ 自动检测到微信数据路径')
      wechatOk.value = '解包成功！检测到微信数据，可以开始导入'
      importProgress.value = null
      
      // 保存自动检测到的路径
      await savePathsToSettings(pathRes.data, false)
    } else {
      // 自动检测失败，提示用户手动选择
      addLog('⚠️ 自动检测失败，请手动选择微信数据目录')
      showCustomPath.value = true
      wechatErr.value = '未能自动检测到微信路径，请手动选择数据目录'
      importProgress.value = null
    }
  } catch (e: any) {
    wechatErr.value = e?.message || '验证异常'
    addLog('验证异常: ' + wechatErr.value)
    importProgress.value = null
  } finally {
    verifying.value = false
  }
}

// 开始导入
async function startImport() {
  if (wechatImporting.value) {
    console.log('[DEBUG] 导入进行中，忽略重复点击')
    return
  }

  wechatImporting.value = true
  wechatErr.value = ''
  wechatOk.value = ''
  addLog('开始导入微信数据...')

  try {
    await bridgeReady()
    
    importProgress.value = { status: '正在解密数据库...', percent: 20 }
    
    const res = await api.import_wechat_data(wechatForm.dbKey, {
      import_contacts: wechatForm.importContacts,
      import_messages: wechatForm.importMessages
    })

    importProgress.value = { status: '导入完成', percent: 100 }

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
    importProgress.value = null
    wechatImporting.value = false
  }
}

// 选择自定义路径
async function selectCustomPath() {
  try {
    await bridgeReady()
    const result = await api.select_directory('选择微信数据目录 (WeChat Files)')
    
    if (result && result.path) {
      customWechatDir.value = result.path
      addLog('已选择目录: ' + result.path)
      
      // 自动扫描该目录
      await scanAndSetCustomPath(result.path)
    }
  } catch (e: any) {
    wechatErr.value = '选择目录失败: ' + (e?.message || '未知错误')
  }
}

// 保存路径到设置
async function savePathsToSettings(paths: any, isCustom: boolean) {
  try {
    const settingsToSave = {
      wechat_use_custom_path: isCustom,
      wechat_data_dir: paths.wechat_dir || '',
      wechat_user_wxid: paths.current_user || '',
      wechat_db_key: wechatForm.dbKey  // 保存密钥
    }
    
    console.log('[DEBUG] 保存路径和密钥到设置')
    await api.set_settings(settingsToSave)
    addLog('✅ 路径和密钥配置已保存')
  } catch (e: any) {
    console.error('[ERROR] 保存设置失败:', e)
  }
}

// 扫描并设置自定义路径
async function scanAndSetCustomPath(wechatDir: string) {
  try {
    addLog('扫描微信目录...')
    const scanResult = await api.scan_wechat_directory(wechatDir)
    
    if (!scanResult.ok || !scanResult.wxids || scanResult.wxids.length === 0) {
      wechatErr.value = '未在该目录下找到微信数据（wxid_ 文件夹）'
      addLog('扫描失败: 未找到wxid')
      return
    }
    
    // 获取第一个wxid的数据
    const firstWxid = scanResult.wxids[0]
    const databases = scanResult.databases[firstWxid]
    
    // 设置路径信息
    const newPathInfo = {
      wechat_dir: wechatDir,
      current_user: firstWxid,
      databases: {
        message: databases.msg_dbs || [],
        contact: databases.contact_db
      },
      source: 'custom'
    }
    
    pathInfo.value = newPathInfo
    
    // 保存到设置
    await savePathsToSettings(newPathInfo, true)
    
    showCustomPath.value = false
    wechatOk.value = `✅ 扫描成功！找到 ${scanResult.wxids.length} 个账号，已设置为：${firstWxid}`
    addLog(wechatOk.value)
  } catch (e: any) {
    wechatErr.value = '扫描失败: ' + (e?.message || '未知错误')
    addLog('扫描失败: ' + wechatErr.value)
  }
}

// 重置流程
function resetFlow() {
  pathInfo.value = null
  showCustomPath.value = false
  customWechatDir.value = ''
  wechatErr.value = ''
  wechatOk.value = ''
  importProgress.value = null
  addLog('已重置配置')
}


</script>

<style scoped>
.home-page { display: flex; flex-direction: column; gap: var(--ct-space-lg); }
.page-title { display: flex; align-items: center; justify-content: space-between; }
.page-title h1 { margin: 0; color: var(--ct-color-primary); }
.grid { display: grid; grid-template-columns: 1fr; gap: var(--ct-space-lg); }

.slogan { margin: 0 0 var(--ct-space-sm); font-weight: var(--ct-font-bold); color: var(--ct-color-primary); }
.intro { margin: var(--ct-space-sm) var(--ct-space-lg); padding-left: var(--ct-space-lg); color: var(--ct-text-secondary); }
.intro li { margin: 6px 0; }

.form { display: flex; flex-direction: column; gap: var(--ct-space-md); }
.row { display: grid; grid-template-columns: 140px 1fr; gap: var(--ct-space-md); align-items: center; }
.lab { color: var(--ct-text-secondary); }
.actions { display: inline-flex; gap: var(--ct-space-sm); }
.hint-box { background: var(--ct-color-info-light); border-left: 3px solid var(--ct-color-info); padding: var(--ct-space-md); margin-bottom: var(--ct-space-md); border-radius: var(--ct-radius-sm); }
.hint-box p { margin: 6px 0; font-size: var(--ct-text-sm); }
.hint-box a { color: var(--ct-color-primary); text-decoration: underline; }
.options { display: flex; gap: var(--ct-space-lg); }
.options label { display: flex; align-items: center; gap: var(--ct-space-sm); cursor: pointer; }

/* 路径信息显示 */
.path-info {
  background: var(--ct-bg-secondary);
  padding: var(--ct-space-md);
  border-radius: var(--ct-radius-md);
  margin: var(--ct-space-sm) 0;
}
.info-item {
  display: flex;
  margin: var(--ct-space-xs) 0;
  font-size: var(--ct-text-sm);
}
.info-item .label {
  color: var(--ct-text-secondary);
  min-width: 100px;
}
.info-item .value {
  color: var(--ct-text-primary);
  font-family: var(--ct-font-mono);
  word-break: break-all;
}

/* 自定义路径选择 */
.custom-path-box {
  background: var(--ct-color-warning-light);
  border-left: 3px solid var(--ct-color-warning);
  padding: var(--ct-space-md);
  margin: var(--ct-space-sm) 0;
  border-radius: var(--ct-radius-sm);
}
.custom-path-box .warning {
  margin: 0 0 var(--ct-space-sm) 0;
  color: var(--ct-color-warning);
  font-size: var(--ct-text-sm);
}
.path-input-group {
  display: flex;
  gap: var(--ct-space-sm);
  align-items: center;
}
.path-input-group .ct-field {
  flex: 1;
}

.progress-box { margin-top: var(--ct-space-md); }
.progress-box p { margin: 0 0 6px; font-size: var(--ct-text-sm); color: var(--ct-text-secondary); }
.progress-bar { width: 100%; height: 8px; background: var(--ct-border-color); border-radius: var(--ct-radius-sm); overflow: hidden; }
.progress-fill { height: 100%; background: var(--ct-color-primary); transition: width var(--ct-transition-normal); }
.error { color: var(--ct-color-error); background: var(--ct-color-error-light); padding: var(--ct-space-sm) var(--ct-space-md); border-radius: var(--ct-radius-md); }
.ok { color: var(--ct-color-success); background: var(--ct-color-success-light); padding: var(--ct-space-sm) var(--ct-space-md); border-radius: var(--ct-radius-md); }

.logs { padding: var(--ct-space-xs) 0; max-height: 220px; overflow: auto; }
.logs ul { list-style: none; padding: 0 var(--ct-space-lg); margin: 0; display: flex; flex-direction: column; gap: 6px; }
.logs .ts { color: var(--ct-text-tertiary); margin-right: var(--ct-space-sm); font-size: var(--ct-text-xs); }
.logs .msg { color: var(--ct-text-primary); }
.empty { color: var(--ct-text-tertiary); padding: 0 var(--ct-space-lg) var(--ct-space-md); }
</style>
