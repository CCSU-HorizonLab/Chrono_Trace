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
          <!-- 步骤1：获取密钥提示 -->
          <div class="hint-box">
            <p><strong>步骤 1：</strong> 使用 <a href="https://github.com/ycccccccy/wx_key" target="_blank">wx_key 工具</a> 获取微信数据库密钥</p>
            <p><strong>步骤 2：</strong> 将获取的32位hex密钥粘贴到下方输入框</p>
            <p><strong>步骤 3：</strong> 点击"开始导入"按钮</p>
          </div>

          <label class="row">
            <div class="lab">数据库密钥</div>
            <CtField 
              v-model="wechatForm.dbKey" 
              placeholder="输入32位hex密钥 (例如: 1a2b3c4d...)" 
              type="password"
            />
          </label>

          <div class="row">
            <div class="lab">导入选项</div>
            <div class="options">
              <label>
                <input type="checkbox" v-model="wechatForm.importContacts" />
                导入联系人
              </label>
              <label>
                <input type="checkbox" v-model="wechatForm.importMessages" />
                导入消息
              </label>
            </div>
          </div>

          <div class="actions">
            <CtButton :loading="wechatImporting" @click="onWeChatImport">开始导入</CtButton>
            <CtButton variant="ghost" :loading="verifying" @click="verifyKey">验证密钥</CtButton>
            <CtButton variant="ghost" @click="checkPaths">查看路径</CtButton>
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

      <!-- 通用数据导入（保留原功能） -->
      <CtCard title="通用数据导入">
        <div class="form">
          <label class="row">
            <div class="lab">对象名称</div>
            <CtField v-model="form.subject" placeholder="例如：小林 / Alex" />
          </label>
          <label class="row">
            <div class="lab">数据源路径</div>
            <CtField v-model="form.data_path" placeholder="例如：C:/data/chat/history.json 或导出目录" />
          </label>
          <div class="actions">
            <CtButton :loading="importing" @click="onImport">导入数据</CtButton>
            <CtButton variant="ghost" :loading="pinging" @click="ping">测试桥接</CtButton>
          </div>
          <p v-if="err" class="error">{{ err }}</p>
          <p v-if="ok" class="ok">{{ ok }}</p>
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
import { reactive, ref } from 'vue'
import { bridgeReady, api } from '@/api/bridge'
import CtCard from '@/components/base/CtCard.vue'
import CtField from '@/components/base/CtField.vue'
import CtButton from '@/components/base/CtButton.vue'

// 通用导入表单
const form = reactive({ subject: '', data_path: '' })
const err = ref('')
const ok = ref('')
const importing = ref(false)
const pinging = ref(false)

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

// 日志
const logs = ref<{ ts: string; msg: string }[]>([])

function addLog(msg: string) {
  const ts = new Date().toLocaleString()
  logs.value.unshift({ ts, msg })
}

// 微信导入功能
async function onWeChatImport() {
  wechatErr.value = ''
  wechatOk.value = ''
  importProgress.value = null

  if (!wechatForm.dbKey.trim()) {
    wechatErr.value = '请输入数据库密钥'
    return
  }

  wechatImporting.value = true
  addLog('开始导入微信数据...')

  try {
    await bridgeReady()
    
    // 模拟进度（实际应从后端获取）
    importProgress.value = { status: '正在解密数据库...', percent: 10 }
    
    const res = await api.import_wechat_data(wechatForm.dbKey, {
      import_contacts: wechatForm.importContacts,
      import_messages: wechatForm.importMessages
    })

    importProgress.value = { status: '导入完成', percent: 100 }

    if (res.ok) {
      const stats = res.stats || {}
      wechatOk.value = `导入成功！联系人: ${stats.contacts || 0}, 消息: ${stats.messages || 0}, 会话: ${stats.conversations || 0}`
      addLog(wechatOk.value)
    } else {
      wechatErr.value = res.error || '导入失败'
      addLog('导入失败: ' + wechatErr.value)
    }
  } catch (e: any) {
    wechatErr.value = e?.message || '导入异常'
    addLog('导入异常: ' + wechatErr.value)
    importProgress.value = null
  } finally {
    wechatImporting.value = false
  }
}

async function verifyKey() {
  wechatErr.value = ''
  wechatOk.value = ''

  if (!wechatForm.dbKey.trim()) {
    wechatErr.value = '请输入密钥'
    return
  }

  verifying.value = true
  addLog('验证密钥...')

  try {
    await bridgeReady()
    const res = await api.verify_wechat_key(wechatForm.dbKey)

    if (res.ok) {
      wechatOk.value = '密钥验证成功！'
      addLog('密钥验证成功')
    } else {
      wechatErr.value = res.error || '密钥验证失败'
      addLog('密钥验证失败')
    }
  } catch (e: any) {
    wechatErr.value = e?.message || '验证异常'
    addLog('验证异常')
  } finally {
    verifying.value = false
  }
}

async function checkPaths() {
  wechatErr.value = ''
  wechatOk.value = ''
  addLog('查询微信路径...')

  try {
    await bridgeReady()
    const res = await api.get_wechat_paths()

    if (res.ok) {
      const data = res.data
      const msg = `微信目录: ${data.wechat_dir}
当前用户: ${data.current_user}`
      alert(msg)
      addLog('路径查询成功')
    } else {
      wechatErr.value = res.error || '路径查询失败'
      addLog('路径查询失败')
    }
  } catch (e: any) {
    wechatErr.value = e?.message || '查询异常'
    addLog('查询异常')
  }
}

// 通用导入功能
async function onImport() {
  err.value = ''
  ok.value = ''
  if (!form.data_path.trim()) { err.value = '请填写数据源路径'; return }
  importing.value = true
  try {
    await bridgeReady()
    const res = await api.ingest_data(form.data_path, { subject: form.subject || '默认对象' })
    addLog('导入完成')
    ok.value = typeof res === 'string' ? res : '导入成功'
  } catch (e: any) {
    err.value = e?.message || '导入失败'
    addLog('导入失败')
  } finally {
    importing.value = false
  }
}

const pong = ref('')
async function ping() {
  pinging.value = true
  try {
    await bridgeReady()
    pong.value = await api.ping()
    addLog('桥接可用: ' + pong.value)
  } catch (e: any) {
    err.value = e?.message || '桥接失败'
    addLog('桥接失败')
  } finally {
    pinging.value = false
  }
}
</script>

<style scoped>
.home-page { display: flex; flex-direction: column; gap: 16px; }
.page-title { display: flex; align-items: center; justify-content: space-between; }
.page-title h1 { margin: 0; color: var(--ct-color-primary); }
.grid { display: grid; grid-template-columns: 1fr; gap: 16px; }

.slogan { margin: 0 0 8px; font-weight: 700; color: var(--ct-color-primary); }
.intro { margin: 8px 14px; padding-left: 16px; color: #555; }
.intro li { margin: 6px 0; }

.form { display: flex; flex-direction: column; gap: 12px; }
.row { display: grid; grid-template-columns: 140px 1fr; gap: 12px; align-items: center; }
.lab { color: #555; }
.actions { display: inline-flex; gap: 8px; }
.hint-box { background: #f0f7ff; border-left: 3px solid var(--ct-color-primary); padding: 12px; margin-bottom: 12px; }
.hint-box p { margin: 6px 0; font-size: 14px; }
.hint-box a { color: var(--ct-color-primary); text-decoration: underline; }
.options { display: flex; gap: 16px; }
.options label { display: flex; align-items: center; gap: 6px; cursor: pointer; }
.progress-box { margin-top: 12px; }
.progress-box p { margin: 0 0 6px; font-size: 14px; color: #555; }
.progress-bar { width: 100%; height: 8px; background: #e0e0e0; border-radius: 4px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--ct-color-primary); transition: width 0.3s; }
.error { color: #b00020; background: #fde7eb; padding: 8px 10px; border-radius: 8px; }
.ok { color: #0c7c3a; background: #e8f5ec; padding: 8px 10px; border-radius: 8px; }

.logs { padding: 4px 0; max-height: 220px; overflow: auto; }
.logs ul { list-style: none; padding: 0 14px; margin: 0; display: flex; flex-direction: column; gap: 6px; }
.logs .ts { color: #888; margin-right: 8px; font-size: 12px; }
.logs .msg { color: #333; }
.empty { color: #888; padding: 0 14px 12px; }
</style>
