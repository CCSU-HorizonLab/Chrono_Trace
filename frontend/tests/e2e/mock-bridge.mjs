/**
 * E2E mock bridge（真实用户 UI 自动测试用）。
 *
 * 以 addInitScript 在任何应用脚本前注入 window.pywebview.api——前端
 * bridgeReady() 直通，全部调用经真实 Proxy 代理链。mock 只替换后端返回，
 * 数据全部虚构（演示账号/林晚/陈默/周末徒步群），不含任何真实数据。
 *
 * 注意：addInitScript 只序列化函数体，模块作用域常量在页面上下文不存在——
 * 全部数据必须定义在本函数体内（自包含闭包）。
 */
export function mockBridgeInit() {
  const NOW = Math.floor(Date.now() / 1000)
  const DAY = 86400
  // —— 虚构数据集（单聊主联系人 cid=1 / 次联系人 cid=2 无分析 / 群 cid=3）——
  const conversations = [
    { id: 1, name: '林晚', message_count: 3210, conversation_type: 'private' },
    { id: 2, name: '陈默', message_count: 860, conversation_type: 'private' },
    { id: 3, name: '周末徒步群', message_count: 12877, conversation_type: 'group' },
  ]
  function dimension(name, score, weight, interp) {
    return {
      name, score, weight,
      weighted_score: Math.round(score * weight * 10) / 10,
      interpretation: interp,
      sub_scores: {}, bonus_scores: {}, confidence_meta: {},
    }
  }
  const affinityResult = {
    overall_score: 72.5,
    overall_interpretation: '关系整体温热，互动投入与情感共鸣稳定，近期回应节奏略有放缓。',
    interaction_investment: dimension('互动投入', 74, 0.40, '双方互动频次与投入较为均衡。'),
    emotional_resonance: dimension('情感共鸣', 78, 0.35, '情绪同频度高， TA 对你的分享回应积极。'),
    closeness_signals: dimension('亲近信号', 66, 0.15, '存在稳定的话题延展与延续性互动。'),
    preference_compatibility: dimension('喜好兼容度', 61, 0.10, '共同话题集中在影视与徒步。'),
    llm_relationship: null,
    llm_relationship_absent_reason: '未配置 LLM 模型，可在设置页添加',
    risk_assessment: {
      highest_level: '留意',
      signals: {
        response_slowdown: { label: '回应节奏放缓', level: '留意', note: '近 30 天 TA 回复中位数由 12 分钟升至 47 分钟' },
      },
    },
    conversation_id: 1,
    analysis_timestamp: NOW - 3600,
    analysis_duration_ms: 41230,
    task_id: 'e2e-task',
    cache_version: 5,
    cache_updated_at: NOW - 3600,
    analysis_caliber: 2,
    status: 'completed',
    progress_percent: 100,
    current_step: '分析完成',
  }
  const pulseOverview = {
    ok: true,
    analyzed: true,
    verdict: {
      text: '关系温度 72（温热），较上次下降 1.2 分。话题发起略偏你（63%），关系目前多由你在推动。你回 TA（中位约 8.0 分钟）比 TA 回你（约 47.0 分钟）更快。',
      source: 'template',
    },
    temperature: {
      score: 72, label: '温热', delta: -1.2,
      trend_line: [
        [NOW - 180 * DAY, 78], [NOW - 150 * DAY, 76], [NOW - 120 * DAY, 80],
        [NOW - 90 * DAY, 75], [NOW - 60 * DAY, 73], [NOW - 30 * DAY, 74],
        [NOW - 7 * DAY, 72],
      ],
    },
    initiative: { total_sessions: 214, user_initiated: 135, other_initiated: 79, me_pct: 63.1 },
    response: {
      recent: { me_to_ta_median_min: 8.0, ta_to_me_median_min: 47.0, me_count: 1201, ta_count: 987 },
      prev: { me_to_ta_median_min: 6.5, ta_to_me_median_min: 12.0, me_count: 1310, ta_count: 1205 },
    },
    monthly: {
      messages: 486, chars: 21400, late_night: 21, late_night_by_me: 13,
      morning_days: 9, morning_by_me: 4, night_days: 14, night_by_me: 8,
    },
    warning: {
      level: '留意',
      items: [{ label: '回应节奏放缓', level: '留意', note: '近 30 天 TA 回复中位数由 12 分钟升至 47 分钟' }],
    },
    professional: {
      result: affinityResult,
      analysis_stale: false,
      pending_message_count: 3,
      absent_reason: '未配置 LLM 模型，可在设置页添加',
    },
  }
  function emojiSnapshot(cid) {
    const hours = Array.from({ length: 24 }, (_, h) => (h >= 22 || h <= 1 ? 9 : h >= 19 ? 4 : 1))
    const total = hours.reduce((a, b) => a + b, 0)
    return {
      ok: true, version: 1, conversation_id: cid, scanned_messages: 3210,
      top_me: {
        unicode: [{ key: '😂', count: 96 }, { key: '🤣', count: 41 }, { key: '🙏', count: 22 }],
        builtin: [{ key: '呲牙', count: 87 }, { key: '偷笑', count: 33 }],
      },
      top_ta: {
        unicode: [{ key: '🥰', count: 64 }, { key: '😭', count: 29 }],
        builtin: [{ key: '捂脸', count: 51 }, { key: '可爱', count: 27 }],
      },
      months: [
        { month: '2026-06', me: 88, ta: 71 }, { month: '2026-07', me: 76, ta: 84 },
        { month: '2026-08', me: 92, ta: 79 }, { month: '2026-09', me: 64, ta: 62 },
        { month: '2026-10', me: 81, ta: 77 }, { month: '2026-11', me: 55, ta: 49 },
      ],
      hourly: hours,
      peak_hour: 22, peak_count: 9,
      rhythm_label: '深夜 22 点前后',
      custom_wall: [
        { md5: 'a1b2c3d4'.padEnd(32, '0'), count: 38, count_me: 20, count_ta: 18, first_used: NOW - 300 * DAY, last_used: NOW - 2 * DAY },
        { md5: 'b2c3d4e5'.padEnd(32, '0'), count: 25, count_me: 4, count_ta: 21, first_used: NOW - 200 * DAY, last_used: NOW - 9 * DAY },
      ],
      custom_anonymous: { me: 12, ta: 7 },
      _total: total,
    }
  }
  const deepPayload = {
    ok: true, version: 2, conversation_id: 1,
    from_ts: NOW - 400 * DAY, to_ts: NOW,
    contact: { display_name: '林晚', avatar: null, sensitive: true },
    stats: { total: 3210, self_count: 1680, other_count: 1530, active_days: 388, span_days: 400, user_sessions: 214, other_sessions: 118, me: 1680, other: 1530 },
    // 顶层 buckets（DeepEmotionPanel Bucket 口径：ts/score/userScore/otherScore）
    buckets: Array.from({ length: 56 }, (_, i) => {
      const ts = NOW - (56 - i) * 7 * DAY
      return {
        ts: new Date(ts * 1000).toISOString().slice(0, 10),
        score: Math.round((0.2 + ((i * 7) % 50) / 100) * 100) / 100,
        userScore: Math.round((0.15 + ((i * 5) % 40) / 100) * 100) / 100,
        otherScore: Math.round((0.1 + ((i * 3) % 60) / 100) * 100) / 100,
        msgCount: 38 + ((i * 13) % 60), userCount: 18 + ((i * 7) % 30), otherCount: 16 + ((i * 5) % 28),
        coverage: 0.9, lowConfidence: false,
      }
    }),
    wordcloud_evolution: {
      ok: true,
      segments: [
        {
          label: '初识 · 2025 秋', from_ts: NOW - 400 * DAY, to_ts: NOW - 270 * DAY, truncated: false,
          words: {
            all: [{ word: '你好', count: 45 }, { word: '周末', count: 38 }, { word: '电影', count: 31 }],
            me: [{ word: '你好', count: 28 }, { word: '电影', count: 20 }],
            other: [{ word: '周末', count: 24 }, { word: '你好', count: 17 }],
          },
        },
        {
          label: '熟络 · 2026 夏', from_ts: NOW - 270 * DAY, to_ts: NOW - 120 * DAY, truncated: false,
          words: {
            all: [{ word: '徒步', count: 88 }, { word: '哈哈哈', count: 72 }, { word: '晚饭', count: 55 }],
            me: [{ word: '徒步', count: 46 }, { word: '哈哈哈', count: 41 }],
            other: [{ word: '徒步', count: 42 }, { word: '晚饭', count: 30 }],
          },
        },
        {
          label: '近来 · 2026 秋', from_ts: NOW - 120 * DAY, to_ts: NOW, truncated: false,
          words: {
            all: [{ word: '加班', count: 61 }, { word: '改天', count: 44 }, { word: '徒步', count: 39 }],
            me: [{ word: '加班', count: 38 }, { word: '改天', count: 21 }],
            other: [{ word: '加班', count: 23 }, { word: '徒步', count: 22 }],
          },
        },
      ],
    },
    big5_evolution: {
      segments: 2, min_messages: 30,
      series: [
        {
          from_ts: NOW - 400 * DAY, to_ts: NOW - 180 * DAY,
          me: { source: 'local', scores: { openness: { score: 60 }, conscientiousness: { score: 54 }, extraversion: { score: 57 }, agreeableness: { score: 69 }, neuroticism: { score: 43 } } },
          other: { source: 'local', scores: { openness: { score: 68 }, conscientiousness: { score: 57 }, extraversion: { score: 63 }, agreeableness: { score: 74 }, neuroticism: { score: 41 } } },
        },
        {
          from_ts: NOW - 180 * DAY, to_ts: NOW,
          me: { source: 'local', scores: { openness: { score: 63 }, conscientiousness: { score: 55 }, extraversion: { score: 59 }, agreeableness: { score: 70 }, neuroticism: { score: 42 } } },
          other: { source: 'local', scores: { openness: { score: 66 }, conscientiousness: { score: 56 }, extraversion: { score: 60 }, agreeableness: { score: 72 }, neuroticism: { score: 44 } } },
        },
      ],
    },
    turning_points: [
      { direction: 'drop', from_ts: '2026-05', to_ts: '2026-06', from_score: 0.52, to_score: 0.38, delta: -0.14 },
      { direction: 'rise', from_ts: '2026-08', to_ts: '2026-09', from_score: 0.35, to_score: 0.48, delta: 0.13 },
    ],
    milestones: [
      { kind: 'first_message', ts: NOW - 400 * DAY, scope: 'global' },
      { kind: 'count_mark', ts: NOW - 210 * DAY, mark: 1000, scope: 'global' },
      { kind: 'count_mark', ts: NOW - 90 * DAY, mark: 3000, scope: 'global' },
      { kind: 'longest_silence', ts: NOW - 60 * DAY, days: 12, from_ts: NOW - 72 * DAY, to_ts: NOW - 60 * DAY },
    ],

    chapter_spans: [
      [NOW - 400 * DAY, NOW - 180 * DAY],
      [NOW - 180 * DAY, NOW],
    ],

    chapters_ok: true,
    affinity_history: {
      ok: true, comparable: true,
      points: pulseOverview.temperature.trend_line.map(([ts, score]) => ({ ts, score })),
    },
    calendar: {
      ok: true, year: 2026,
      grid: Object.fromEntries(
        Array.from({ length: 120 }, (_, i) => [String(NOW - (119 - i) * DAY), 1 + ((i * 7) % 23)]),
      ),
    },
    activity: { ok: true, grid: Array.from({ length: 7 }, (_, d) => Array.from({ length: 24 }, (_, h) => (h >= 20 && d >= 5 ? 6 : d >= 5 ? 2 : 1))) },
    quotes: { ok: true, items: [{ text: '下次徒步叫我一个', is_sender: false, ts: NOW - 200 * DAY }] },
    insights: { ok: true, items: [{ label: '深夜聊天 21 次', note: '多集中在周末' }] },
  }
  const big5Impressions = {
    ok: true, version: 2, conversation_id: 1,
    base: {
      extraversion: { score: 62, label: '外向性', note: '群聊活跃，单聊主动' },
      agreeableness: { score: 74, label: '宜人性', note: '语气友好，少冲突' },
      conscientiousness: { score: 58, label: '尽责性', note: '约定事项多兑现' },
      neuroticism: { score: 41, label: '神经质', note: '情绪波动低' },
      openness: { score: 69, label: '开放性', note: '话题涉猎广' },
    },
    enhanced: null, enhanced_version: 0,
    sample_count: 3210,
  }
  const memeDictionary = {
    ok: true, conversation_id: 1,
    items: [
      { text: '绝绝子', count: 55, me: 34, ta: 21 },
      { text: '夜爬吗', count: 52, me: 12, ta: 40 },
      { text: 'dddd', count: 27, me: 19, ta: 8 },
    ],
  }

  const mirrorStats = {
    ok: true, conversation_id: 1,
    reply: {
      me: { median: 480, count: 1201 },
      ta: { median: 2820, count: 987 },
    },
    initiative: { me: 135, total: 214 },
    volume: { me_chars: 21010, ta_chars: 18400 },
  }

  const weeklyReport = {
    ok: true,
    report: {
      week_start: NOW - 4 * DAY,
      verdict: '本周互动 486 条，较上周下降 12%；TA 回应中位数升至 47 分钟，主动天平仍偏你。',
      source: 'template',
      snapshot: { messages: 486, chars: 21400, late_night: 21, morning_days: 9, night_days: 14 },
      updated_at: NOW - 1800,
    },
    llm_configured: false,
  }
  const groupStats = {
    ok: true, conversation_id: 3,
    total_messages: 12877, active_members: 23,
    top_speakers: [
      { name: '老周', count: 2811 }, { name: '林晚', count: 1930 }, { name: '阿凯', count: 1544 },
    ],
    hourly: Array.from({ length: 24 }, (_, h) => (h >= 9 && h <= 22 ? 4 : 1)),
  }
  const settings = {
    ok: true,
    analysis_device_mode: 'auto',
    model_root_dir: '/home/demo/.chrono-trace/models',
    default_model_root_dir: '/home/demo/.chrono-trace/models',
    sentiment_model_dir: '/home/demo/.chrono-trace/models/sentiment_3class/onnx',
    embedding_model_dir: '/home/demo/.chrono-trace/models/embedding/onnx',
    wechat_accounts: [
      {
        wxid: 'e2e_wxid', label: '演示账号', avatar: '',
        wechat_dir: '/home/demo/xwechat_files/e2e_wxid', source: 'auto',
        db_key: 'e2e' + '0'.repeat(60), import_completed: true,
        last_import_at: NOW - DAY, last_import_total_size: 1024, last_import_files: [],
      },
    ],
    wechat_active_account: 'e2e_wxid',
    wechat_use_custom_path: false,
    wechat_data_dir: '/home/demo/xwechat_files/e2e_wxid',
    wechat_user_wxid: 'e2e_wxid',
    wechat_db_key: 'e2e' + '0'.repeat(60),
    wechat_import_completed: true,
    monitor_auto_start: false,
    rag_enabled: true,
  }
  const llmModels = {
    ok: true,
    models: [
      { id: 1, name: '演示本地模型', base_url: 'http://127.0.0.1:1234/v1', api_key: '', model: 'demo-chat', enabled: true, is_active: true, is_default: true },
    ],
  }
  const contactProfile = {
    ok: true, display_name: '林晚', version: 3, generated_at: NOW - 7200,
    tags: ['徒步爱好者', '夜猫子', '猫派'],
    emotion_spectrum: { positive: 0.46, neutral: 0.42, negative: 0.12 },
    topics: [{ label: '徒步/户外', weight: 0.31 }, { label: '影视', weight: 0.22 }, { label: '美食', weight: 0.18 }],
    summary: '性格外向温和，周末高频组织户外活动，聊到徒步话题时回复显著变快。',
    sensitive: false,
  }
  const state = { calls: [], uncovered: [] }
  const wait = (ms) => new Promise((r) => setTimeout(r, ms))

  const QA_ANSWER =
    '根据聊天记录，你们的关系整体处于稳定期。近三个月对方的话题参与度保持在较高水平，' +
    '但回复间隔从 10 分钟左右延长到了 40 分钟以上，多发生在工作日晚间。建议关注节奏变化而非单条消息的语气。'

  const handlers = {
    ping: async () => 'pong',
    get_settings: async () => settings,
    get_current_user_profile: async () => ({ ok: true, profile: null }),
    set_settings: async () => ({ ok: true }),
    // __E2E_EMPTY_DB 标志供首次引导用例模拟空库
    get_wechat_accounts: async () => ({ ok: true, accounts: window.__E2E_EMPTY_DB ? [] : settings.wechat_accounts }),
    set_active_wechat_account: async () => ({ ok: true }),
    get_wechat_paths: async () => ({ ok: true, paths: { wechat_dir: '/home/demo/xwechat_files', current_user: 'e2e_wxid' } }),
    detect_wechat_import_increment: async () => ({ ok: true, has_increment: false, new_files: [] }),

    get_conversation_list: async () => ({ ok: true, conversations: window.__E2E_EMPTY_DB ? [] : conversations }),
    get_conversation_span: async () => ({ success: true, data: { from_date: '2025-10-02', to_date: '2026-11-07' } }),

    get_pulse_overview: async (cid) => {
      await wait(60)
      if (Number(cid) === 1) return pulseOverview
      if (Number(cid) === 3) return { ok: false, error: '群聊无脉搏页数据' }
      return { ...pulseOverview, analyzed: false, temperature: null, initiative: null, response: null, warning: null, verdict: null, professional: { result: null, analysis_stale: false, pending_message_count: 0, absent_reason: null } }
    },
    get_weekly_report: async () => weeklyReport,
    request_weekly_llm: async () => ({ ok: false, error: '未配置 LLM' }),

    get_affinity_scores: async (cid) => {
      await wait(50)
      if (Number(cid) !== 1) return { ok: true, result: null, history: {}, analysis_stale: false, pending_message_count: 0 }
      return { ok: true, result: affinityResult, history: { comparable: true, score_trend: -1.2 }, analysis_stale: false, pending_message_count: 3 }
    },
    get_affinity_config: async () => ({ ok: true, config: { weights: null, enabled: true } }),
    get_relationship_context: async () => ({ ok: true, context: null }),
    get_relationship_field_options: async () => ({ ok: true, options: {} }),
    get_preference_keywords: async () => ({ ok: true, keywords: [{ keyword: '徒步', kind: 'like' }] }),
    get_affinity_keywords: async () => ({ ok: true, categories: [] }),
    check_gpu_status: async () => ({ ok: true, available: false, device: 'cpu', message: 'CPU 模式（演示）' }),
    check_analysis_model_status: async () => ({ ok: true, ready: true, missing: [] }),
    get_affinity_progress: async () => ({ status: 'not_found' }),

    get_deep_analysis: async () => { await wait(80); return deepPayload },
    get_relationship_chapters: async () => {
      const WEEKS = 58
      const weekStarts = Array.from({ length: WEEKS }, (_, i) => NOW - (WEEKS - i) * 7 * DAY)
      const textsMe = weekStarts.map((_, i) => 18 + ((i * 13) % 40))
      const textsOther = weekStarts.map((_, i) => 14 + ((i * 7) % 30))
      const big5Arr = (base) => weekStarts.map((_, i) => Math.min(92, Math.max(8, base + ((i * 11) % 21) - 10)))
      const splitAt = Math.floor(WEEKS * 0.55)
      return {
        ok: true, version: 2,
        span: { week_count: WEEKS, week_seconds: 7 * DAY, from_ts: weekStarts[0], to_ts: NOW },
        week_starts: weekStarts,
        big5_labels: { openness: '开放性', conscientiousness: '尽责性', extraversion: '外向性', agreeableness: '宜人性', neuroticism: '神经质' },
        weekly: {
          texts_me: textsMe, texts_other: textsOther,
          big5: {
            me: { openness: big5Arr(62), conscientiousness: big5Arr(55), extraversion: big5Arr(58), agreeableness: big5Arr(70), neuroticism: big5Arr(42) },
            other: { openness: big5Arr(69), conscientiousness: big5Arr(58), extraversion: big5Arr(64), agreeableness: big5Arr(74), neuroticism: big5Arr(41) },
          },
        },
        chapters: [
          {
            index: 0, week_index: 0, from_ts: weekStarts[0], to_ts: weekStarts[splitAt] - 1,
            phase: '初识与熟络', summary: null,
            stats: { texts: 1780, me_texts: 940, other_texts: 840, other_share: 0.47, pos_ratio: 0.48, latency_hours: 1.8, weeks: splitAt },
            changes: [{ key: 'frequency', label: '消息频率', direction: 'up', delta: 32 }],
          },
          {
            index: 1, week_index: splitAt, from_ts: weekStarts[splitAt], to_ts: NOW,
            phase: '稳定期', summary: null,
            stats: { texts: 1430, me_texts: 740, other_texts: 690, other_share: 0.48, pos_ratio: 0.45, latency_hours: 3.1, weeks: WEEKS - splitAt },
            changes: [{ key: 'latency', label: '回应延迟', direction: 'up', delta: 1.3 }],
          },
        ],
        summary: { months_total: 14, months_ready: 0, chapters_ready: 2, transitions_ready: 0, arc_ready: false, transitions: [], arc: null },
      }
    },
    start_chapter_summaries: async () => ({ ok: true, task_id: 'e2e-chapters' }),
    get_chapter_summaries_progress: async () => ({ ok: true, status: 'completed', done: 2, total: 2 }),
    get_sentiment_coverage: async () => ({ ok: true, coverage_ratio: 0.436, cached: 1400, total: 3210 }),
    get_emoji_stats: async (cid) => { await wait(50); return emojiSnapshot(cid) },
    get_big5_impressions: async () => big5Impressions,
    enhance_big5_impressions: async () => ({ ok: false, error: '未配置 LLM' }),
    generate_profile_evolution: async () => ({ ok: true, segments: [{ label: '2026 春', ts: NOW - 300 * DAY }, { label: '2026 秋', ts: NOW - 10 * DAY }] }),
    get_poster_payload: async () => ({
      ok: true, version: 1, conversation_id: 1,
      from_ts: NOW - 365 * DAY, to_ts: NOW,
      contact: { display_name: '林晚', avatar: null, sensitive: true },
      stats: { total: 3210, self_count: 1680, other_count: 1530, active_days: 388, span_days: 365 },
      emotion_curve: {
        bucket: 'month',
        points: Array.from({ length: 12 }, (_, i) => ({
          ts: `2026-${String(i + 1).padStart(2, '0')}`,
          score: 0.3 + i * 0.04, userScore: 0.2 + i * 0.05, otherScore: 0.35 + i * 0.03,
          msgCount: 120 + i * 12,
        })),
      },
      top_words: {
        all: [
          { word: '哈哈哈哈', weight: 99 }, { word: '好的', weight: 80 }, { word: '嗯嗯', weight: 60 },
          { word: '徒步', weight: 55 }, { word: '夜爬吗', weight: 48 },
        ],
        me: [{ word: '收到', weight: 90 }, { word: '走呀', weight: 70 }, { word: '哈哈哈哈', weight: 65 }],
        other: [{ word: '晚安', weight: 95 }, { word: '无聊', weight: 65 }, { word: '徒步', weight: 60 }],
      },
      quotes: {
        items: [
          { text: '下次徒步叫我一个', is_sender: false, ts: NOW - 200 * DAY },
          { text: '好，周六见', is_sender: true, ts: NOW - 199 * DAY },
        ],
        sensitive: true,
      },
      big5: {
        me: { source: 'local', scores: { openness: { score: 0.62 }, conscientiousness: { score: 0.55 }, extraversion: { score: 0.4 }, agreeableness: { score: 0.66 }, neuroticism: { score: 0.3 } } },
        other: { source: 'local', scores: { openness: { score: 0.5 }, conscientiousness: { score: 0.62 }, extraversion: { score: 0.58 }, agreeableness: { score: 0.44 }, neuroticism: { score: 0.48 } } },
      },
      story: {
        milestones: [
          { kind: 'first_message', ts: NOW - 400 * DAY, scope: 'global' },
          { kind: 'count_mark', ts: NOW - 90 * DAY, mark: 3000, scope: 'global' },
        ],
        chemistry: {
          late_night: { count: 204, self_count: 118, other_count: 86 },
          peak_day: { date: '2026-10-11', count: 96, self_count: 52, other_count: 44 },
          reply_stats: { count: 2188, avg: 4200, median: 900, self_avg: 480, other_avg: 2820 },
          initiator: { user_sessions: 135, other_sessions: 79, user_ratio: 0.63 },
        },
      },
      activity: {
        insights: { streak_days: 21, self_streak_days: 12 },
        grid: { all: Array.from({ length: 7 }, () => Array.from({ length: 24 }, (_, h) => (h >= 22 || h < 2 ? 9 : h >= 19 ? 4 : 1))), me: Array.from({ length: 7 }, () => Array.from({ length: 24 }, (_, h) => (h >= 22 || h < 2 ? 9 : h >= 19 ? 4 : 1))), max_all: 9, max_me: 9 },
        calendar: {
          year: 2026,
          days: Array.from({ length: 120 }, (_, i) => ({
            date: new Date((NOW - (119 - i) * DAY) * 1000).toISOString().slice(0, 10),
            count: (i % 23) + 1, self_count: (i % 12) + 1,
          })),
          max: 23,
        },
      },
    }),
    get_meme_dictionary: async () => memeDictionary,
    get_mirror_stats: async () => mirrorStats,
    save_share_image: async () => ({ ok: true, path: '/tmp/e2e-share.png' }),
    open_export_folder: async () => ({ ok: true }),
    export_chat_records: async () => ({ ok: true, path: '/tmp/e2e-export.txt' }),

    get_analysis: async () => ({ ok: true, result: affinityResult }),
    get_sessions: async () => ({ ok: true, sessions: [{ id: 1, start_ts: NOW - DAY, message_count: 24, summary: '徒步计划讨论' }] }),
    get_session_messages: async () => ({ ok: true, messages: [{ id: 1, is_sender: 1, content: '周六夜爬去吗', ts: NOW - DAY }] }),
    get_activity_calendar: async () => ({
      success: true,
      data: {
        year: 2026, years: [2025, 2026], max_activity_score: 100,
        entries: Array.from({ length: 150 }, (_, i) => ({
          date: new Date((NOW - (149 - i) * DAY) * 1000).toISOString().slice(0, 10),
          message_count: 1 + ((i * 7) % 23), session_count: 1 + (i % 4),
          active_duration_seconds: 600 + i * 30,
          user_initiated_sessions: i % 2, other_initiated_sessions: (i + 1) % 2,
          activity_score: 5 + ((i * 11) % 90), activity_level: 1 + (i % 4),
          first_time: '09:12', last_time: '23:40',
        })),
        summary: {
          active_days: 388, total_messages: 3210, current_streak: 4, longest_streak: 30,
          peak_day: { date: '2026-10-11', message_count: 96, session_count: 8, activity_score: 98 },
          global_first_session_start_time: NOW - 400 * DAY,
          global_peak_session: { start_time: NOW - 30 * DAY, message_count: 96 },
        },
      },
    }),
    // overall 是对象（后端 analysis_read 契约：字数统计+interpretation），高频词条走 get_analysis 的 wordcloud
    get_word_counts: async () => ({
      success: true,
      data: { overall: { user_char_count: 15200, other_char_count: 21400, char_ratio: 1.41, interpretation: '对方投入的字数是您的1.41倍' }, by_session: [] },
    }),
    // initiative_rate 是对方发起占比（后端 feature_extraction 契约：other_initiated/total，0-1 小数）
    get_initiative_stats: async () => ({
      success: true,
      data: { total_sessions: 214, user_initiated_sessions: 135, other_initiated_sessions: 79, initiative_rate: 0.369, interpretation: '对方主动发起36.9%的会话' },
    }),
    get_response_times: async () => ({
      success: true,
      data: {
        // 键为后端 7 桶口径，前端 aggregateResponseTimeDistribution 再聚成 4 桶展示
        count: 2188, avg: 4200, median: 900,
        distribution: { '<1m': 512, '1m-10m': 486, '10m-30m': 577, '30m-1h': 352, '1h-6h': 186, '6h-24h': 75, '>1d': 61 },
      },
    }),
    get_milestone_messages: async () => ({ ok: true, messages: [] }),

    get_llm_models: async () => llmModels,
    save_llm_model: async () => ({ ok: true }),
    delete_llm_model: async () => ({ ok: true }),
    fetch_provider_models: async () => ({ ok: true, models: ['demo-chat'] }),

    get_rag_status: async () => ({ ok: true, enabled: true, indexed_conversations: 2, total_facts: 34, pending: 0 }),
    get_monitor_rag_status: async () => ({ ok: true, active: false }),
    get_contact_facts: async () => ({ ok: true, facts: [], total: 0 }),
    get_rag_log_detail: async () => ({ ok: true, log: null }),
    get_embedding_cache_stats: async () => ({ ok: true, rows: 0, bytes: 0, max_rows: 50000, by_model: [] }),

    get_realtime_status: async () => ({ ok: true, running: false, talker: null }),
    get_realtime_messages: async () => ({ ok: true, messages: [] }),
    get_realtime_recent_messages: async () => ({ ok: true, messages: [] }),
    get_realtime_resume_info: async () => ({ ok: true, resumable: false }),
    get_pending_suggestions: async () => ({ ok: true, suggestions: [] }),
    get_suggestion_config: async () => ({ ok: true, config: { auto_suggest: true } }),
    set_suggestion_config: async () => ({ ok: true }),
    get_dynamic_quick_prompts: async () => ({ ok: true, prompts: ['约周末', '分享日常'] }),
    start_realtime_monitor: async () => ({ ok: true, batch_id: 'e2e-batch' }),
    stop_realtime_monitor: async () => ({ ok: true }),

    get_group_stats: async () => groupStats,
    generate_group_summary: async () => ({ ok: true, task_id: 'e2e-gs' }),
    get_latest_thread: async () => ({ ok: true, thread: null }),
    load_thread_context: async () => ({ ok: true }),

    ask_history: async (cid, _question, _history, reqId) => {
      await wait(60)
      const push = window.__chronoQaPush
      if (push && reqId) {
        for (const frag of ['根据聊天记录，', '你们的关系整体处于稳定期。', '近三个月对方的回复间隔从 10 分钟延长到 40 分钟以上。']) {
          push([{ type: 'delta', req_id: reqId, conversation_id: Number(cid), text: frag }])
          await wait(90)
        }
      }
      await wait(80)
      return {
        ok: true, answer: QA_ANSWER,
        citations: [{ index: 1, timestamp: NOW - 9 * DAY, is_sender: false, text: '这周加班有点多，可能来不了' }],
        memory_refs: [], degraded: false, truncated: false, semantic_indexing: false,
      }
    },
    cancel_history_qa: async () => ({ ok: true }),
    rehearse_reply: async (_cid, _text) => {
      await wait(120)
      return {
        ok: true,
        options: [
          { tone: 'warm', label: '温和回应', direction: '承接对方话题并给出具体时间', draft: '好呀，那就这周六，正好我也想出去走走', consequence: '对方大概率积极回复，节奏回升' },
          { tone: 'neutral', label: '平稳回应', direction: '明确意向但留余地', draft: '周六可以，具体时间到时再定', consequence: '关系维持现状，不增不减' },
          { tone: 'cool', label: '冷静观察', direction: '降低投入，观察对方反应', draft: '最近有点忙，下周再看', consequence: '短期热度可能进一步回落' },
        ],
      }
    },
    ask_avatar_chat: async (cid, _message, _history, reqId) => {
      await wait(60)
      const push = window.__chronoAvatarPush
      if (push && reqId) {
        for (const frag of ['嗯嗯 ', '周六可以！', '记得带件外套，山顶冷。']) {
          push([{ type: 'delta', req_id: reqId, conversation_id: Number(cid), text: frag }])
          await wait(90)
        }
      }
      await wait(60)
      return { ok: true, reply: '嗯嗯 周六可以！记得带件外套，山顶冷。', truncated: false, voice: { sample_count: 1840 } }
    },
    cancel_avatar_chat: async () => ({ ok: true }),

    get_contact_profile: async () => contactProfile,
    generate_contact_profile: async () => contactProfile,
    get_self_profile: async () => ({ ok: true, profile: null }),
    generate_self_profile: async () => ({ ok: true, profile: null }),
    list_profile_snapshots: async () => ({ ok: true, snapshots: [] }),

    select_file: async () => ({ ok: false, canceled: true }),
    select_directory: async () => ({ ok: false, canceled: true }),
    open_external_url: async () => ({ ok: true }),

    enter_floating_mode: async () => ({ ok: true }),
    exit_floating_mode: async () => ({ ok: true }),
    get_floating_status: async () => ({ ok: true, active: false, expanded: false }),
    set_floating_expanded: async () => ({ ok: true }),
    window_toggle_maximized: async () => ({ ok: true, maximized: false }),
    window_minimize: async () => ({ ok: true }),
    perform_close_action: async () => ({ ok: true }),
  }

  window.__e2eMock = state
  window.pywebview = {
    api: new Proxy({}, {
      get(_, prop) {
        return async (...args) => {
          state.calls.push(String(prop))
          const h = handlers[prop]
          if (h) return h(...args)
          if (!state.uncovered.includes(String(prop))) state.uncovered.push(String(prop))
          console.warn(`[e2e-mock] 未覆盖方法: ${String(prop)}`)
          return { ok: false, error: `e2e-mock 未覆盖 ${String(prop)}` }
        }
      },
    }),
  }
}
