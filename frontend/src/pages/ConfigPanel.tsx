import { useState } from 'react'

export default function ConfigPanel() {
  const [saved, setSaved] = useState(false)

  const handleSave = () => {
    setSaved(true)
    setTimeout(() => setSaved(false), 3000)
  }

  return (
    <div className="space-y-4 max-w-[800px]">
      <h1 className="text-xl font-bold">参数配置后台</h1>

      {/* Thresholds */}
      <section className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
        <h2 className="text-sm font-semibold mb-4">信号阈值调整</h2>
        <div className="space-y-4">
          {[
            { label: 'GEX 翻正阈值', value: 0, min: -100, max: 100, unit: '%' },
            { label: 'DIX 暗盘买入阈值', value: 45, min: 0, max: 100, unit: '%' },
            { label: 'Short Volume 阈值', value: 45, min: 0, max: 100, unit: '%' },
            { label: 'Hawkes 分支比临界', value: 0.7, min: 0, max: 1, unit: '', step: 0.05 },
            { label: '共振信号冷却期', value: 30, min: 5, max: 120, unit: '分钟' },
          ].map((item) => (
            <div key={item.label}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-[var(--text-secondary)]">{item.label}</span>
                <span className="text-xs text-[var(--text-primary)] font-mono">
                  {item.value}{item.unit}
                </span>
              </div>
              <input
                type="range"
                defaultValue={item.value}
                min={item.min}
                max={item.max}
                step={item.step ?? 1}
                className="w-full h-1.5 rounded-full appearance-none bg-[var(--bg-primary)] cursor-pointer accent-[var(--accent-blue)]"
              />
            </div>
          ))}
        </div>
      </section>

      {/* Fetch frequency */}
      <section className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
        <h2 className="text-sm font-semibold mb-4">抓取频率设置</h2>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-[var(--text-secondary)] mb-1">盘中刷新间隔</label>
            <select className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border)] text-xs text-[var(--text-primary)]">
              {[1, 5, 10, 15, 30].map((m) => (
                <option key={m} value={m}>{m} 分钟</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-[var(--text-secondary)] mb-1">盘后刷新间隔</label>
            <select className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border)] text-xs text-[var(--text-primary)]">
              {[15, 30, 60].map((m) => (
                <option key={m} value={m}>{m} 分钟</option>
              ))}
            </select>
          </div>
        </div>
      </section>

      {/* Notification channels */}
      <section className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
        <h2 className="text-sm font-semibold mb-4">通知渠道绑定</h2>
        <div className="space-y-4">
          <div>
            <label className="block text-xs text-[var(--text-secondary)] mb-1">Email 收件人</label>
            <input
              type="text"
              placeholder="user@example.com"
              className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border)] text-xs text-[var(--text-primary)]"
            />
          </div>
          <div>
            <label className="block text-xs text-[var(--text-secondary)] mb-1">Telegram Bot Token</label>
            <input
              type="password"
              placeholder="••••••••••••"
              className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border)] text-xs text-[var(--text-primary)]"
            />
          </div>
          <div>
            <label className="block text-xs text-[var(--text-secondary)] mb-1">Discord Webhook URL</label>
            <input
              type="password"
              placeholder="••••••••••••"
              className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border)] text-xs text-[var(--text-primary)]"
            />
          </div>
          <div className="flex gap-2">
            <button className="px-3 py-1.5 text-xs rounded-lg bg-[var(--border)] text-[var(--text-secondary)] hover:text-white transition-colors">
              测试发送
            </button>
          </div>
        </div>
      </section>

      {/* Action buttons */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          className="px-4 py-2 rounded-lg bg-[var(--accent-blue)] text-white text-sm hover:opacity-90 transition-opacity"
        >
          {saved ? '已保存 ✓' : '保存配置'}
        </button>
        <button className="px-4 py-2 rounded-lg border border-[var(--border)] text-sm text-[var(--text-secondary)] hover:text-white transition-colors">
          恢复默认值
        </button>
        <button className="px-4 py-2 rounded-lg border border-[var(--border)] text-sm text-[var(--text-secondary)] hover:text-white transition-colors">
          导出配置 JSON
        </button>
      </div>
    </div>
  )
}
