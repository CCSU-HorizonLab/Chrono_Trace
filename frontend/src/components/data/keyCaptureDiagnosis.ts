// 密钥提取失败诊断：按后端 code 命名空间（wechat/keys/* 与 webview/api/key_capture.py、
// bridge.py 的 legacy_wechat_v3）映射「发生了什么 + 该做什么」。
// 未知 code 一律返回 undefined，由调用方回落原文案。
export type KeyCaptureDiagnosis = { title: string; hint: string }

export const KEY_CAPTURE_DIAGNOSIS: Record<string, KeyCaptureDiagnosis> = {
  // —— 引擎无关 / 会话启动 ——
  wechat_not_running: {
    title: '未检测到运行中的微信',
    hint: '请先启动微信 PC 版并登录，再点击「重试自动获取」。',
  },
  hook_prepare_timeout: {
    title: '监听注入准备超时',
    hint: '通常是微信响应慢或被安全软件拦截，重试一次；多次失败建议完全退出微信后重开再试。',
  },
  capture_start_failed: {
    title: '密钥获取未能启动',
    hint: '启动自动获取过程出错，请重试一次；仍失败请改用手动输入密钥。',
  },
  capture_session_not_found: {
    title: '获取会话已失效',
    hint: '本次获取会话不存在或已过期，请点击「重试自动获取」重新开始。',
  },
  // —— Windows 监听（wx_key）——
  extension_missing: {
    title: '缺少密钥监听组件',
    hint: '程序目录缺少监听组件，可能被杀毒软件误删；可重装应用，或改用手动输入密钥。',
  },
  hook_initialize_failed: {
    title: '密钥监听初始化失败',
    hint: '当前微信版本可能与监听方式不兼容；重试一次，仍失败请改用手动输入密钥。',
  },
  hook_poll_failed: {
    title: '密钥监听读取中断',
    hint: '建议完全退出微信再重新打开并登录，然后点击「重试自动获取」。',
  },
  capture_timeout: {
    title: '等待登录超时',
    hint: '监听在有效期内没有等到登录动作；请在重试后，看到「请完成登录」提示时尽快登录。',
  },
  // —— Windows 只读扫描 ——
  scan_no_match: {
    title: '内存中未找到密钥特征',
    hint: '请确认微信已登录且是目标账号后重试；多次失败可改用监听方式或手动输入。',
  },
  scan_no_db: {
    title: '未找到加密数据库',
    hint: '所选目录中没有微信 4.x 加密数据库，请确认目录是当前登录账号的数据目录。',
  },
  scan_partial_primary_missing: {
    title: '密钥不全，缺少主库密钥',
    hint: '只扫到部分数据库的密钥，无法解密主库；请完全退出微信重开并登录后重试。',
  },
  scan_open_failed: {
    title: '无法访问微信进程内存',
    hint: '请用当前用户启动微信（不要管理员/普通账户混用），并检查安全软件未拦截，再重试。',
  },
  // —— Linux GDB 断点 ——
  ptrace_denied: {
    title: '系统拒绝调试附加权限',
    hint: 'Linux 需允许调试器附加微信进程：终端执行 echo 0 | sudo tee /proc/sys/kernel/yama/ptrace_scope 后重试。',
  },
  elf_analysis_failed: {
    title: '微信程序分析失败',
    hint: '微信版本更新后断点地址需要适配，请等待应用更新；也可改用手动输入密钥。',
  },
  capture_failed: {
    title: '密钥捕获未成功',
    hint: '请完全退出微信后重新打开并登录，再点击「重试自动获取」。',
  },
  // —— 重启微信引导（flow_win）——
  restart_failed: {
    title: '微信重启失败',
    hint: '自动重启微信未成功，请手动完全退出微信后重新打开，再点击「重试自动获取」。',
  },
  wechat_executable_not_found: {
    title: '未找到微信程序',
    hint: '无法定位微信主程序，请确认微信已安装；也可手动启动微信到登录界面后重试。',
  },
  wechat_close_failed: {
    title: '微信关闭失败',
    hint: '请在任务管理器中手动结束微信进程，再点击「重试自动获取」。',
  },
  wechat_launch_failed: {
    title: '微信重新启动失败',
    hint: '微信已关闭但重新启动失败，请手动打开微信并停留在登录界面，再重试。',
  },
  wechat_start_timeout: {
    title: '微信启动超时',
    hint: '微信启动后长时间未就绪，请等微信到达登录界面后再点击「重试自动获取」。',
  },
  // —— 桥接层 ——
  key_verification_failed: {
    title: '密钥验证未通过',
    hint: '拿到的密钥无法解密当前数据库，可能登录的不是目标账号；请确认账号后重试，或改用手动输入。',
  },
  legacy_wechat_v3: {
    title: '检测到微信 3.x 旧版本',
    hint: '本应用仅支持微信 4.0 及以上版本，请先升级微信再导入。',
  },
}

/** 按 code 查诊断；空 code 与未知 code 返回 undefined（调用方回落原文案） */
export function diagnoseKeyCapture(code: string): KeyCaptureDiagnosis | undefined {
  const normalized = String(code || '').trim()
  return normalized ? KEY_CAPTURE_DIAGNOSIS[normalized] : undefined
}
