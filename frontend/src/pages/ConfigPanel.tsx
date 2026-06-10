import { useState } from 'react'
import { useConfig, useUpdateConfig, useConfigDefaults, useConfigAudit, useRestoreConfig } from '../api/config'
import { useTestNotification } from '../api/notifications'
import { Save, RotateCcw, Download, History, Zap } from 'lucide-react'

export default function ConfigPanel() {
  const [saved, setSaved] = useState(false)
  const [restoredVersion, setRestoredVersion] = useState('')
  const [testingChannel, setTestingChannel] = useState<string | null>(null)

  const { data: config, isLoading } = useConfig()
  const { data: defaults } = useConfigDefaults()
  const { data: auditData } = useConfigAudit()
  const updateConfig = useUpdateConfig()
  const restoreConfig = useRestoreConfig()
  const testMutation = useTestNotification()

  const auditLogs = auditData?.audit_logs ?? []

  // Threshold state (initialized from config/defaults)
  const [thresholds, setThresholds] = useState({
    dix: 45, shortVolume: 45, gex: 0,
    level3: 3.5, level2: 3.0, level1: 2.0,
    cooldown: 30,
  })

  const handleSave = async () => {
    await updateConfig.mutateAsync({ thresholds, cooldown_minutes: thresholds.cooldown } as Record<string, unknown>)
    setSaved(true)
    setTimeout(() => setSaved(false), 3000)
  }

  const handleRestoreDefault = async () => {
    setRestoredVersion('default')
    if (defaults?.thresholds) {
      setThresholds({
        dix: defaults.thresholds.DIX_THRESHOLD ?? 45,
        shortVolume: defaults.thresholds.SHORT_VOLUME_THRESHOLD ?? 45,
        gex: defaults.thresholds.GEX_THRESHOLD ?? 0,
        level3: defaults.thresholds.LEVEL_3_THRESHOLD ?? 3.5,
        level2: defaults.thresholds.LEVEL_2_THRESHOLD ?? 3.0,
        level1: defaults.thresholds.LEVEL_1_THRESHOLD ?? 2.0,
        cooldown: defaults.cooldown_minutes ?? 30,
      })
    }
    await restoreConfig.mutateAsync('default')
    setTimeout(() => setRestoredVersion(''), 3000)
  }

  const handleTestChannel = async (channel: string) => {
    setTestingChannel(channel)
    await testMutation.mutateAsync(channel)
    setTestingChannel(null)
  }

  const handleExport = () => {
    const json = JSON.stringify(thresholds, null, 2)
    const blob = new Blob([json], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'msr-config-backup.json'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-4 max-w-[860px]">
      <h1 className="text-xl font-bold">参数配置后台</h1>

      {isLoading ? (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (<div key={i} className="h-48 rounded-xl skeleton" />))}
        </div>
      ) : (
        <>
          {/* Signal Thresholds */}
          <section className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-5">
            <h2 className="text-sm font-semibold mb-5 flex items-center gap-2">
              <span className="w-1 h-4 rounded-full bg-[var(--accent-blue)]" />
              信号阈值调整
            </h2>
            <div className="space-y-5">
              {[
                { label: 'DIX 吸筹线', key: 'dix', value: thresholds.dix, min: 0, max: 100, step: 1, unit: '%', desc: 'DIX 暗盘买入强度阈值' },
                { label: 'Short Volume 阈值', key: 'shortVolume', value: thresholds.shortVolume, min: 0, max: 100, step: 1, unit: '%', desc: '卖空比触发线' },
                { label: 'GEX 翻正阈值', key: 'gex', value: thresholds.gex, min: -1000, max: 1000, step: 10, unit: '$M', desc: 'Gamma 敞口翻正门槛' },
              ].map((item) => (
                <div key={item.key}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-[var(--text-secondary)]">{item.label}</span>
                    <span className="text-xs text-[var(--text-primary)] font-mono">{item.value}{item.unit}</span>
                  </div>
                  <input
                    type="range"
                    value={item.value}
                    min={item.min} max={item.max} step={item.step}
                    onChange={(e) => setThresholds((t) => ({ ...t, [item.key]: Number(e.target.value) }))}
                    className="w-full h-1.5 rounded-full bg-[var(--bg-primary)] cursor-pointer accent-[var(--accent-blue)]"
                  />
                  <p className="text-[9px] text-[var(--text-secondary)] mt-0.5">{item.desc}</p>
                </div>
              ))}

              <div className="border-t border-[var(--border)] pt-4">
                <p className="text-[10px] text-[var(--text-secondary)] mb-3">共振等级触发线</p>
                {[
                  { label: 'LEVEL 3 共振线', key: 'level3', value: thresholds.level3, min: 1.0, max: 5.0, step: 0.1, color: '#ef4444' },
                  { label: 'LEVEL 2 共振线', key: 'level2', value: thresholds.level2, min: 1.0, max: 5.0, step: 0.1, color: '#eab308' },
                  { label: 'LEVEL 1 共振线', key: 'level1', value: thresholds.level1, min: 1.0, max: 5.0, step: 0.1, color: '#f59e0b' },
                ].map((item) => (
                  <div key={item.key} className="mb-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs text-[var(--text-secondary)]">{item.label}</span>
                      <span className="text-xs font-mono" style={{ color: item.color }}>{item.value.toFixed(1)}/5.0</span>
                    </div>
                    <input
                      type="range"
                      value={item.value}
                      min={item.min} max={item.max} step={item.step}
                      onChange={(e) => setThresholds((t) => ({ ...t, [item.key]: Number(e.target.value) }))}
                      className="w-full h-1.5 rounded-full bg-[var(--bg-primary)] cursor-pointer"
                      style={{ accentColor: item.color }}
                    />
                  </div>
                ))}
              </div>

              {/* Cooldown */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-[var(--text-secondary)]">信号冷却期</span>
                  <span className="text-xs text-[var(--text-primary)] font-mono">{thresholds.cooldown} 分钟</span>
                </div>
                <input
                  type="range"
                  value={thresholds.cooldown}
                  min={5} max={120} step={5}
                  onChange={(e) => setThresholds((t) => ({ ...t, cooldown: Number(e.target.value) }))}
                  className="w-full h-1.5 rounded-full bg-[var(--bg-primary)] cursor-pointer accent-[var(--accent-blue)]"
                />
              </div>
            </div>
          </section>

          {/* Fetch Frequency */}
          <section className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-5">
            <h2 className="text-sm font-semibold mb-4 flex items-center gap-2">
              <span className="w-1 h-4 rounded-full bg-[var(--accent-green)]" />
              抓取频率设置
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {[
                { label: '盘中 GEX/VIX 间隔', options: [1, 5, 10, 15, 30], default: 15, unit: '分钟' },
                { label: '加密监控间隔', options: [1, 3, 5, 10], default: 5, unit: '分钟' },
                { label: '盘后 DIX 时间', options: ['20:00', '20:30', '21:00'], default: '20:30', unit: '' },
              ].map((item) => (
                <div key={item.label}>
                  <label className="block text-xs text-[var(--text-secondary)] mb-1">{item.label}</label>
                  <select defaultValue={item.default} className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border)] text-xs text-[var(--text-primary)]">
                    {item.options.map((o) => (
                      <option key={o} value={o}>{o}{item.unit}</option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
          </section>

          {/* Notification Channel Binding */}
          <section className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-5">
            <h2 className="text-sm font-semibold mb-4 flex items-center gap-2">
              <span className="w-1 h-4 rounded-full bg-[var(--accent-yellow)]" />
              通知渠道绑定
            </h2>
            <div className="space-y-4">
              <div>
                <label className="block text-xs text-[var(--text-secondary)] mb-1">Email 收件人</label>
                <div className="flex gap-2">
                  <input type="text" placeholder="trader@example.com" className="flex-1 px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border)] text-xs text-[var(--text-primary)] placeholder-[var(--text-secondary)]" />
                  <button onClick={() => handleTestChannel('email')} disabled={testingChannel === 'email'}
                    className="flex items-center gap-1 px-3 py-2 rounded-lg border border-[var(--border)] text-xs text-[var(--text-secondary)] hover:text-white hover:border-white/30 disabled:opacity-50 transition-colors">
                    <Zap size={12} /> {testingChannel === 'email' ? '...' : '测试'}
                  </button>
                </div>
              </div>
              <div>
                <label className="block text-xs text-[var(--text-secondary)] mb-1">Telegram Bot Token</label>
                <div className="flex gap-2">
                  <input type="password" placeholder="••••••••••••" defaultValue="••••••••••••" className="flex-1 px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border)] text-xs text-[var(--text-primary)]" />
                  <button onClick={() => handleTestChannel('telegram')} disabled={testingChannel === 'telegram'}
                    className="flex items-center gap-1 px-3 py-2 rounded-lg border border-[var(--border)] text-xs text-[var(--text-secondary)] hover:text-white hover:border-white/30 disabled:opacity-50 transition-colors">
                    <Zap size={12} /> {testingChannel === 'telegram' ? '...' : '测试'}
                  </button>
                </div>
              </div>
              <div>
                <label className="block text-xs text-[var(--text-secondary)] mb-1">Discord Webhook URL</label>
                <div className="flex gap-2">
                  <input type="password" placeholder="••••••••••••" className="flex-1 px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border)] text-xs text-[var(--text-primary)]" />
                  <button onClick={() => handleTestChannel('discord')} disabled={testingChannel === 'discord'}
                    className="flex items-center gap-1 px-3 py-2 rounded-lg border border-[var(--border)] text-xs text-[var(--text-secondary)] hover:text-white hover:border-white/30 disabled:opacity-50 transition-colors">
                    <Zap size={12} /> {testingChannel === 'discord' ? '...' : '测试'}
                  </button>
                </div>
              </div>
              {testMutation.isSuccess && (
                <p className="text-[10px] text-[var(--accent-green)]">✅ 测试消息已发送</p>
              )}
            </div>
          </section>

          {/* Audit Log */}
          <section className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-5">
            <h2 className="text-sm font-semibold mb-4 flex items-center gap-2">
              <History size={14} className="text-[var(--text-secondary)]" />
              配置审计日志
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full text-[10px]">
                <thead>
                  <tr className="border-b border-[var(--border)] text-[var(--text-secondary)]">
                    <th className="text-left py-2 px-2 font-medium">时间</th>
                    <th className="text-left py-2 px-2 font-medium">用户</th>
                    <th className="text-left py-2 px-2 font-medium">字段</th>
                    <th className="text-left py-2 px-2 font-medium">旧值</th>
                    <th className="text-left py-2 px-2 font-medium">新值</th>
                  </tr>
                </thead>
                <tbody>
                  {auditLogs.map((entry, i) => (
                    <tr key={i} className="border-b border-[var(--border)]/30 hover:bg-white/5">
                      <td className="py-2 px-2 text-[var(--text-secondary)]">{entry.timestamp ? new Date(entry.timestamp).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '--'}</td>
                      <td className="py-2 px-2 text-[var(--text-primary)]">{entry.user}</td>
                      <td className="py-2 px-2 text-[var(--accent-blue)]">{entry.field}</td>
                      <td className="py-2 px-2 text-[var(--accent-red)]">{entry.old_value}</td>
                      <td className="py-2 px-2 text-[var(--accent-green)]">{entry.new_value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* Action Buttons */}
          <div className="flex items-center gap-3 flex-wrap">
            <button
              onClick={handleSave}
              disabled={updateConfig.isPending}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-[var(--accent-blue)] text-white text-sm hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              <Save size={14} />
              {saved ? '已保存 ✓' : updateConfig.isPending ? '保存中...' : '保存配置'}
            </button>
            <button
              onClick={handleRestoreDefault}
              disabled={restoreConfig.isPending}
              className="flex items-center gap-2 px-4 py-2.5 rounded-lg border border-[var(--border)] text-sm text-[var(--text-secondary)] hover:text-white hover:border-white/30 transition-colors"
            >
              <RotateCcw size={14} />
              {restoredVersion === 'default' ? '已还原 ✓' : '恢复默认值'}
            </button>
            <button
              onClick={handleExport}
              className="flex items-center gap-2 px-4 py-2.5 rounded-lg border border-[var(--border)] text-sm text-[var(--text-secondary)] hover:text-white hover:border-white/30 transition-colors"
            >
              <Download size={14} />
              导出配置 JSON
            </button>
          </div>
        </>
      )}
    </div>
  )
}
