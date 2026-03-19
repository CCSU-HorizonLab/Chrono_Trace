import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { bridgeReady, api } from '@/api/bridge'
import { analyzeAffinity, getAffinityScores, getAffinityProgress, getRelationshipContext, type AffinityAnalysisResult } from '@/api/affinity'

import FiltersBar from '@/components/analytics/FiltersBar.vue'
import DateRangeFilter from '@/components/analytics/DateRangeFilter.vue'
import SubjectCard from '@/components/analytics/SubjectCard.vue'
import EmotionLineChart from '@/components/charts/EmotionLineChart.vue'
import WordCloud from '@/components/charts/WordCloud.vue'
import ConversationTimeline from '@/components/timeline/ConversationTimeline.vue'

import AffinityScoreCard from '@/components/affinity/AffinityScoreCard.vue'
import DimensionRadar from '@/components/affinity/DimensionRadar.vue'
import SubScoreBreakdown from '@/components/affinity/SubScoreBreakdown.vue'
import WeightInfoTooltip from '@/components/affinity/WeightInfoTooltip.vue'
import PreferenceKeywordsDialog from '@/components/affinity/PreferenceKeywordsDialog.vue'
import RelationshipContextForm from '@/components/affinity/RelationshipContextForm.vue'
import CtCard from '@/components/base/CtCard.vue'
import CtButton from '@/components/base/CtButton.vue'

type Conversation = { id: number; name: string; username: string; message_count: number; last_message_time: string }
type Session = { id: number; start_time: number; end_time: number; duration: number; message_count: number; initiator: string; messages: any[] }
type TimeseriesPoint = {
    ts: string
    score: number
    positive?: number
    neutral?: number
    negative?: number
    msgCount?: number
    userScore?: number
    otherScore?: number
}
type SubjectStats = { msgCount: number; avgScore: number; maxDay?: string; minDay?: string }
type Subject = { id?: string | number; name: string; avatar?: string; stats?: SubjectStats }
type Analysis = { subject?: Subject; timeseries: TimeseriesPoint[]; wordcloud: { word: string; weight: number }[] }

export default {
    components: {
        FiltersBar, DateRangeFilter, SubjectCard, EmotionLineChart, WordCloud, ConversationTimeline,
        AffinityScoreCard, DimensionRadar, SubScoreBreakdown, WeightInfoTooltip,
        PreferenceKeywordsDialog, RelationshipContextForm, CtCard, CtButton
    },
    setup() {
        const currentTab = ref('affinity')

        // Core State
        const conversations = ref<Conversation[]>([])
        const selectedConversationId = ref<number | null>(null)
        const dates = reactive({ from: '', to: '' })
        const loading = ref(false)
        const loadingSessions = ref(false)
        const error = ref('')
        const analysis = reactive<Analysis>({ timeseries: [], wordcloud: [] })
        const subject = ref<Subject | undefined>(undefined)
        const sessions = ref<Session[]>([])

        // Affinity State
        const analysisResult = ref<AffinityAnalysisResult | null>(null)
        const displayScore = ref(0)
        const showKeywordsDialog = ref(false)
        const showContextForm = ref(false)
        const pendingAnalysisForce = ref(false)
        const analysisLaunchPending = ref(false)

        // Global Progress
        const isGlobalAnalyzing = ref(false)
        const globalProgressPercent = ref(0)
        const globalProgressStep = ref('')

        // Features State
        const hasFeatures = ref(false)
        const featureStats = ref({ avgResponseTime: 0, medianResponseTime: 0, initiativeRate: 0, wordRatio: 0 })
        const responseTimeStats = ref({
            avg: 0,
            median: 0,
            min: 0,
            max: 0,
            abnormal_count: 0,
            count: 0,
            distribution: null as Record<string, number> | null,
            distributionKeys: ['<1m', '1m-10m', '10m-30m', '30m-1h', '1h-6h', '6h-24h', '>1d']
        })
        const initiativeStats = ref({ totalSessions: 0, userInitiatedSessions: 0, otherInitiatedSessions: 0, initiativeRate: 0, interpretation: '' })
        const wordCountsStats = ref({ userCharCount: 0, otherCharCount: 0, charRatio: 0, interpretation: '' })

        // Chart Refs
        const responseTimeChart = ref<HTMLDivElement | null>(null)
        const timelineChart = ref<HTMLDivElement | null>(null)
        const wordCountChart = ref<HTMLDivElement | null>(null)
        let responseTimeChartInstance: echarts.ECharts | null = null
        let timelineChartInstance: echarts.ECharts | null = null
        let wordCountChartInstance: echarts.ECharts | null = null

        const stats = ref<{ totalMessages: number; avgSentiment: number; activeDays: number; sessionCount: number } | null>(null)
        const currentRangeLabel = computed(() => {
            if (!dates.from || !dates.to) return '默认近30天，可切换时间范围'
            return `${dates.from} 至 ${dates.to}`
        })
        const hasContentAnalysis = computed(() => {
            return Boolean(subject.value?.stats && (
                (subject.value.stats.msgCount || 0) > 0 ||
                analysis.wordcloud.length > 0 ||
                analysis.timeseries.length > 0
            ))
        })

        const currentContactName = computed(() => {
            if (!selectedConversationId.value) return '选择联系人'
            return conversations.value.find(c => c.id === selectedConversationId.value)?.name || '选择联系人'
        })

        const hasPreferenceKeywords = computed(() => analysisResult.value?.preference_compatibility?.weight !== undefined && analysisResult.value.preference_compatibility.weight > 0)
        const hasCachedAffinityAnalysis = computed(() => Boolean(analysisResult.value))

        const allDimensions = computed(() => {
            if (!analysisResult.value) return {}
            return {
                emotional_resonance: analysisResult.value.emotional_resonance || undefined,
                chat_positivity: analysisResult.value.chat_positivity || undefined,
                attitude_tendency: analysisResult.value.attitude_tendency || undefined,
                preference_compatibility: analysisResult.value.preference_compatibility || undefined
            }
        })

        const radius = 50
        const circumference = 2 * Math.PI * radius
        const strokeDashoffset = computed(() => circumference - (displayScore.value / 100) * circumference)

        function formatNumber(num: number): string {
            if (!num) return '0'
            if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M'
            if (num >= 1000) return (num / 1000).toFixed(1) + 'K'
            return num.toString()
        }

        function formatTime(seconds: number): string {
            if (seconds === undefined || seconds === null) return '-'
            if (seconds < 1 && seconds > 0) return '<1s'
            if (seconds === 0) return '0s'
            if (seconds < 60) return `${Math.round(seconds)}s`
            if (seconds < 3600) return `${Math.round(seconds / 60)}m`
            if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`
            return `${(seconds / 86400).toFixed(1)}d`
        }

        function getResponseTimeLabel(rangeKey: string): string {
            const labelMap: Record<string, string> = {
                '<1m': '1分钟内',
                '1m-10m': '1到10分钟',
                '10m-30m': '10到30分钟',
                '30m-1h': '30分钟到1小时',
                '1h-6h': '1到6小时',
                '6h-24h': '6到24小时',
                '>1d': '1天以上'
            }
            return labelMap[rangeKey] || rangeKey
        }

        function getResponseTimePercent(rangeKey: string): string {
            const count = responseTimeStats.value.distribution?.[rangeKey] || 0
            const total = responseTimeStats.value.count || 1
            return `${((count / total) * 100).toFixed(1)}%`
        }

        function setDefaultDates(days = 7) {
            const to = new Date()
            const from = new Date()
            from.setDate(to.getDate() - (days - 1))
            dates.from = from.toISOString().slice(0, 10)
            dates.to = to.toISOString().slice(0, 10)
        }

        function refreshSummaryStats() {
            const timeseries = analysis.timeseries || []
            const totalSentiment = timeseries.reduce((sum: number, p: any) => sum + (p.score || 0), 0)
            stats.value = {
                totalMessages: subject.value?.stats?.msgCount || 0,
                avgSentiment: timeseries.length ? parseFloat((totalSentiment / timeseries.length).toFixed(2)) : 0,
                activeDays: timeseries.length,
                sessionCount: sessions.value.length
            }
        }

        async function loadConversations() {
            try {
                await bridgeReady()
                const res = await api.get_conversation_list()
                if (res.ok) {
                    conversations.value = res.conversations
                    if (conversations.value.length > 0 && !selectedConversationId.value) {
                        onConversationChange(conversations.value[0].id)
                    }
                }
            } catch (e: any) { console.error('加载联系人失败', e) }
        }

        async function onConversationChange(id: number) {
            selectedConversationId.value = id
            hasFeatures.value = false
            analysisResult.value = null
            loadAnalysis()
            loadSessions()
            tryLoadExistingFeatures()
            tryLoadAffinityScores()
        }

        function onDatesChange(newDates: { from: string; to: string }) {
            dates.from = newDates.from
            dates.to = newDates.to
            loadAnalysis()
        }

        const handleExport = () => {
            // Note: export function might just redirect or emit. Assuming an unimplemented function for now
            console.warn('Export to CSV is clicked.')
            alert('导出功能尚未实现。')
        }

        async function tryLoadAffinityScores() {
            if (!selectedConversationId.value) return
            try {
                const scores = await getAffinityScores(selectedConversationId.value)
                if (scores && scores.cache_version >= 4) {
                    analysisResult.value = scores
                } else {
                    analysisResult.value = null
                }
            } catch (e) {
                analysisResult.value = null
            }
        }

        async function tryLoadExistingFeatures() {
            if (!selectedConversationId.value) return
            hasFeatures.value = false
            try {
                const res = await api.get_response_times(selectedConversationId.value)
                if (res.success && res.data && res.data.count > 0) {
                    hasFeatures.value = true
                    await loadFeatureData()
                }
            } catch (e) { }
        }

        async function loadAnalysis() {
            if (!selectedConversationId.value) return
            loading.value = true
            error.value = ''
            try {
                await bridgeReady()
                const res = await api.get_analysis({ conversation_id: selectedConversationId.value, from: dates.from, to: dates.to })
                if (res.error) { error.value = res.error; return }
                analysis.timeseries = res?.timeseries ?? []
                analysis.wordcloud = res?.wordcloud ?? []
                subject.value = res?.subject ?? subject.value
                refreshSummaryStats()
            } catch (e: any) {
                error.value = e?.message || '加载失败'
            } finally { loading.value = false }
        }

        async function loadSessions() {
            if (!selectedConversationId.value) return
            loadingSessions.value = true
            try {
                await bridgeReady()
                const res = await api.get_sessions(selectedConversationId.value, 50, 0)
                if (res.success && res.data && res.data.sessions) {
                    sessions.value = res.data.sessions.map((s: any) => ({
                        ...s,
                        start_time: s.start_time * 1000,
                        end_time: s.end_time * 1000,
                        duration: (s.end_time || 0) - (s.start_time || 0)
                    }))
                    await nextTick()
                    if (currentTab.value === 'features' || currentTab.value === 'content') renderTimelineChart()
                    refreshSummaryStats()
                }
            } catch (e) { console.error(e) } finally { loadingSessions.value = false }
        }

        const handleStartGlobalAnalysis = async (force: boolean) => {
            if (!selectedConversationId.value) return
            if (isGlobalAnalyzing.value) return
            if (analysisLaunchPending.value || isGlobalAnalyzing.value) return
            analysisLaunchPending.value = true
            try {
                const { has_context } = await getRelationshipContext(selectedConversationId.value)
                if (!has_context) {
                    pendingAnalysisForce.value = force
                    showContextForm.value = true
                    analysisLaunchPending.value = false
                    return
                }
            } catch (e) { }
            await startGlobalAnalysis(force)
        }

        const handleContextSaved = () => startGlobalAnalysis(pendingAnalysisForce.value)
        const handleKeywordsUpdated = async () => { if (selectedConversationId.value) await startGlobalAnalysis(true) }

        async function startGlobalAnalysis(force: boolean) {
            if (!selectedConversationId.value) return
            isGlobalAnalyzing.value = true
            globalProgressPercent.value = 0
            globalProgressStep.value = '即将开始...'

            try {
                // Stage 1: Feature Extraction
                globalProgressStep.value = '正在提取客观互动特征...'
                globalProgressPercent.value = 5
                const extractRes = await api.extract_features(selectedConversationId.value)
                if (extractRes.success || extractRes.ok) {
                    const taskId = (extractRes.data || extractRes).task_id
                    if ((extractRes.data || extractRes).status !== 'completed') {
                        await new Promise<void>((resolve, reject) => {
                            const timer = setInterval(async () => {
                                try {
                                    const prog = await api.get_extraction_progress(taskId)
                                    const d = prog.data || prog
                                    if (prog.success || prog.ok) {
                                        globalProgressPercent.value = 5 + (d.progress || 0) * 0.45
                                        globalProgressStep.value = `[特征分析] ${d.message || d.current_step || '分析中...'}`
                                        if (d.status === 'completed') { clearInterval(timer); resolve() }
                                        else if (d.status === 'failed') { clearInterval(timer); resolve() } // Don't block affinity if features fail
                                    }
                                } catch (e) { clearInterval(timer); resolve() }
                            }, 500)
                        })
                    }
                    hasFeatures.value = true
                    await Promise.all([
                        loadFeatureData(),
                        loadSessions()
                    ])
                }

                // Stage 2: Affinity Model
                globalProgressPercent.value = 50
                globalProgressStep.value = '正在进行深度关系推理...'
                const affinityTaskId = await analyzeAffinity(selectedConversationId.value, force)
                await new Promise<void>((resolve, reject) => {
                    const timer = setInterval(async () => {
                        try {
                            const prog = await getAffinityProgress(affinityTaskId)
                            if (prog.ok) {
                                globalProgressPercent.value = 50 + prog.progress_percent * 0.5
                                globalProgressStep.value = `[深度推理] ${prog.current_step || '分析中...'}`
                                if (prog.status === 'completed') {
                                    clearInterval(timer)
                                    if (prog.result) {
                                        analysisResult.value = prog.result as AffinityAnalysisResult
                                    }

                                    const scores = await getAffinityScores(selectedConversationId.value!)
                                    if (
                                        scores &&
                                        (
                                            !analysisResult.value ||
                                            (scores.cache_updated_at || 0) >= (analysisResult.value.cache_updated_at || 0)
                                        )
                                    ) {
                                        analysisResult.value = scores
                                    }
                                    await Promise.all([
                                        loadAnalysis(),
                                        loadSessions()
                                    ])
                                    resolve()
                                } else if (prog.status === 'failed') {
                                    clearInterval(timer); reject(new Error(prog.error))
                                }
                            }
                        } catch (e) { }
                    }, 500)
                })

                globalProgressPercent.value = 100
                globalProgressStep.value = '全面分析完成'
            } catch (e: any) {
                globalProgressStep.value = '分析失败: ' + String(e)
            } finally {
                analysisLaunchPending.value = false
                setTimeout(() => { isGlobalAnalyzing.value = false }, 2000)
            }
        }

        async function loadFeatureData() {
            if (!selectedConversationId.value) return
            try {
                const [rtData, iniData, wcData] = await Promise.all([
                    api.get_response_times(selectedConversationId.value),
                    api.get_initiative_stats(selectedConversationId.value),
                    api.get_word_counts(selectedConversationId.value, false)
                ])
                if (rtData.success && rtData.data) {
                    responseTimeStats.value = {
                        ...responseTimeStats.value,
                        ...rtData.data,
                        distribution: rtData.data.distribution || responseTimeStats.value.distribution
                    }
                    featureStats.value.avgResponseTime = rtData.data.avg
                    featureStats.value.medianResponseTime = rtData.data.median
                    if (currentTab.value === 'features') await nextTick(() => renderResponseTimeChart())
                }
                if (iniData.success && iniData.data) {
                    initiativeStats.value = {
                        totalSessions: iniData.data.total_sessions, userInitiatedSessions: iniData.data.user_initiated_sessions,
                        otherInitiatedSessions: iniData.data.other_initiated_sessions, initiativeRate: iniData.data.initiative_rate, interpretation: iniData.data.interpretation
                    }
                    featureStats.value.initiativeRate = iniData.data.initiative_rate
                }
                if (wcData.success && wcData.data?.overall) {
                    const o = wcData.data.overall
                    wordCountsStats.value = { userCharCount: o.user_char_count, otherCharCount: o.other_char_count, charRatio: o.char_ratio, interpretation: o.interpretation }
                    featureStats.value.wordRatio = o.char_ratio
                    if (currentTab.value === 'features') await nextTick(() => renderWordCountChart())
                }
            } catch (e) { }
        }

        function renderResponseTimeChart() {
            if (!responseTimeChart.value || !responseTimeStats.value.distribution) return
            if (responseTimeChartInstance) responseTimeChartInstance.dispose()
            responseTimeChartInstance = echarts.init(responseTimeChart.value)
            const data = responseTimeStats.value.distributionKeys.map(k => responseTimeStats.value.distribution![k] || 0)
            responseTimeChartInstance.setOption({
                backgroundColor: 'transparent',
                tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
                grid: { left: '3%', right: '4%', bottom: '3%', top: '10%', containLabel: true },
                xAxis: { type: 'category', data: responseTimeStats.value.distributionKeys, axisLabel: { color: 'rgba(255,255,255,0.6)', fontSize: 11, interval: 0 } },
                yAxis: { type: 'value', splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)', type: 'dashed' } }, axisLabel: { color: 'rgba(255,255,255,0.6)' } },
                series: [{ type: 'bar', data: data, itemStyle: { borderRadius: [4, 4, 0, 0], color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: '#818cf8' }, { offset: 1, color: '#6366f1' }]) }, label: { show: true, position: 'top', color: 'rgba(255,255,255,0.7)', fontSize: 11 } }]
            })
        }

        function renderTimelineChart() {
            if (!timelineChart.value || !sessions.value.length) return
            if (timelineChartInstance) timelineChartInstance.dispose()
            timelineChartInstance = echarts.init(timelineChart.value)
            const dailyData: Record<string, { total: number, user: number, other: number }> = {}
            let maxCount = 0
            sessions.value.forEach(s => {
                const d = new Date(s.start_time)
                const dateStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
                if (!dailyData[dateStr]) dailyData[dateStr] = { total: 0, user: 0, other: 0 }
                dailyData[dateStr].total += s.message_count
                if (s.initiator === 'user') dailyData[dateStr].user += s.message_count; else dailyData[dateStr].other += s.message_count
                maxCount = Math.max(maxCount, dailyData[dateStr].total)
            })
            const data = Object.entries(dailyData).map(([date, stats]) => [date, stats.total, stats.user, stats.other])
            const years = [...new Set(Object.keys(dailyData).map(d => d.split('-')[0]))]
            const displayYear = years.length > 0 ? parseInt(years[years.length - 1]) : new Date().getFullYear()

            timelineChartInstance.setOption({
                calendar: { top: 60, left: 40, right: 20, bottom: 20, cellSize: ['auto', 14], range: displayYear, itemStyle: { borderColor: 'transparent', color: 'rgba(255,255,255,0.02)' }, dayLabel: { color: '#64748b' }, monthLabel: { color: '#64748b' } },
                visualMap: { min: 0, max: Math.max(maxCount, 1), orient: 'horizontal', right: 20, top: 10, inRange: { color: ['rgba(255,255,255,0.05)', '#818cf8', '#312e81'] } },
                series: [{ type: 'heatmap', coordinateSystem: 'calendar', data: data, itemStyle: { borderRadius: 3 } }]
            })
        }

        function renderWordCountChart() {
            if (!wordCountChart.value) return
            if (wordCountChartInstance) wordCountChartInstance.dispose()
            wordCountChartInstance = echarts.init(wordCountChart.value)
            wordCountChartInstance.setOption({
                grid: { left: '3%', right: '4%', bottom: '3%', top: '10%', containLabel: true },
                xAxis: { type: 'category', data: ['我', '对方'], axisLabel: { color: 'rgba(255,255,255,0.6)' } },
                yAxis: { type: 'value', splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)', type: 'dashed' } }, axisLabel: { color: 'rgba(255,255,255,0.6)', formatter: (v: number) => `${(v / 1000).toFixed(0)}k` } },
                series: [{ type: 'bar', data: [{ value: wordCountsStats.value.userCharCount, itemStyle: { color: '#818cf8' } }, { value: wordCountsStats.value.otherCharCount, itemStyle: { color: '#f472b6' } }], barWidth: '40%', label: { show: true, position: 'top', color: 'rgba(255,255,255,0.8)', formatter: (p: any) => formatNumber(p.value) } }]
            })
        }

        watch(() => currentTab.value, async (newVal) => {
            await nextTick()
            if (newVal === 'features') {
                if (hasFeatures.value) { renderResponseTimeChart(); renderWordCountChart(); }
                if (sessions.value.length) renderTimelineChart()
            }
        })

        watch(() => analysisResult.value, (newVal) => {
            if (newVal) {
                let start = 0; const end = newVal.overall_score; const duration = 1000; const startTime = performance.now()
                const animate = (currentTime: number) => {
                    const progress = Math.min((currentTime - startTime) / duration, 1)
                    displayScore.value = start + (end - start) * (1 - Math.pow(1 - progress, 4))
                    if (progress < 1) requestAnimationFrame(animate)
                }
                requestAnimationFrame(animate)
            } else displayScore.value = 0
        })

        const getScoreColor = (score: number) => { if (score >= 80) return '#10b981'; if (score >= 60) return '#3b82f6'; if (score >= 40) return '#f59e0b'; return '#ef4444' }
        const scrollToDetails = (idSuffix: string) => document.getElementById(`detail-${idSuffix}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
        const handlePreferenceDisabledClick = () => { showKeywordsDialog.value = true }
        function onWordSelect(word: string) { console.debug('selected', word) }
        function handleResize() { responseTimeChartInstance?.resize(); timelineChartInstance?.resize(); wordCountChartInstance?.resize() }

        onMounted(async () => {
            if (!dates.from || !dates.to) setDefaultDates(30)
            await loadConversations()
            window.addEventListener('resize', handleResize)
        })

        onUnmounted(() => {
            window.removeEventListener('resize', handleResize)
            responseTimeChartInstance?.dispose(); timelineChartInstance?.dispose(); wordCountChartInstance?.dispose()
        })

        return {
            currentTab, conversations, selectedConversationId, dates, loading, loadingSessions, error, analysis, subject, sessions,
            analysisResult, displayScore, showKeywordsDialog, showContextForm, pendingAnalysisForce, isGlobalAnalyzing, globalProgressPercent, globalProgressStep,
            hasFeatures, hasCachedAffinityAnalysis, featureStats, responseTimeStats, initiativeStats, wordCountsStats,
            responseTimeChart, timelineChart, wordCountChart, stats, currentContactName, hasPreferenceKeywords, allDimensions,
            currentRangeLabel, hasContentAnalysis, circumference, strokeDashoffset, formatNumber, formatTime, getResponseTimeLabel, getResponseTimePercent, onConversationChange, onDatesChange, handleExport, handleStartGlobalAnalysis, handleContextSaved, handleKeywordsUpdated,
            getScoreColor, scrollToDetails, handlePreferenceDisabledClick, onWordSelect, loadAnalysis, loadSessions
        }
    }
}
