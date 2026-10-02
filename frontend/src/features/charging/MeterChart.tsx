import { useState } from 'react'

export interface MeterReading {
  timestamp: string; measurand: string; phase: string; location: string; value: string; unit: string
}
const metrics: Record<string, { label: string; unit: string; units: string[] }> = {
  'Energy.Active.Import.Register': { label: 'Điện năng tích lũy', unit: 'kWh', units: ['Wh', 'kWh'] },
  'Power.Active.Import': { label: 'Công suất nạp', unit: 'kW', units: ['W', 'kW'] },
  'Power.Offered': { label: 'Công suất cấp', unit: 'kW', units: ['W', 'kW'] },
  Voltage: { label: 'Điện áp', unit: 'V', units: ['V'] },
  'Current.Import': { label: 'Dòng điện', unit: 'A', units: ['A'] },
  SoC: { label: 'Mức pin', unit: '%', units: ['Percent'] },
  Temperature: { label: 'Nhiệt độ', unit: '°C', units: ['Celsius', 'Celcius'] },
  Frequency: { label: 'Tần số', unit: 'Hz', units: ['Hertz'] },
}
const format = (value: number) => value.toLocaleString('vi-VN', { maximumFractionDigits: 3 })
const time = (stamp: string) => new Date(stamp).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })

export function MeterChart({ readings, sessionId }: { readings: MeterReading[]; sessionId: number }) {
  const [metric, setMetric] = useState('Energy.Active.Import.Register')
  const [series, setSeries] = useState('')
  const [chosen, setChosen] = useState<string | null>(null)
  const numeric = readings.filter(r => r.value.trim() !== '' && Number.isFinite(Number(r.value)) && Number.isFinite(Date.parse(r.timestamp)) && metrics[r.measurand]?.units.includes(r.unit))
  const available = Object.keys(metrics).filter(key => numeric.some(r => r.measurand === key))
  const active = available.includes(metric) ? metric : available[0]
  const definition = metrics[active]
  const energy = numeric.filter(r => r.measurand === active)
  const streams = [...new Set(energy.map(r => `${r.phase}|${r.location}`))].sort()
  const selected = streams.includes(series) ? series : streams.includes('|Outlet') ? '|Outlet' : streams[0]
  const points = energy.filter(r => `${r.phase}|${r.location}` === selected).map(r => ({ ...r, energy: Number(r.value) / (['Wh', 'W'].includes(r.unit) ? 1000 : 1) })).sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp))
  if (!points.length) return <div className="charging-chart-empty"><strong>Chưa có dữ liệu biểu đồ</strong><p>Trụ chưa gửi số đo phù hợp. Bạn vẫn có thể xem dữ liệu nhận được trong bảng số đo.</p></div>
  const low = Math.min(...points.map(p => p.energy))
  const high = Math.max(...points.map(p => p.energy))
  const padding = Math.max((high - low) * .15, .05)
  const floor = low - padding
  const ceiling = high + padding
  const first = Date.parse(points[0].timestamp)
  const last = Date.parse(points[points.length - 1].timestamp)
  const x = (stamp: string) => last === first ? 390 : 64 + (Date.parse(stamp) - first) / (last - first) * 630
  const y = (value: number) => 190 - (value - floor) / (ceiling - floor) * 156
  const pointKey = (index: number) => `${points[index].timestamp}|${points[index].value}|${index}`
  const found = points.findIndex((_, index) => pointKey(index) === chosen)
  const selectedIndex = found < 0 ? points.length - 1 : found
  const point = points[selectedIndex]
  const isEnergy = active === 'Energy.Active.Import.Register'
  const regression = isEnergy && points.some((p, i) => i > 0 && p.energy < points[i - 1].energy)
  return <figure className="charging-chart" aria-labelledby={`meter-title-${sessionId}`}>
    <div className="charging-chart-heading"><label>Thông số<select value={active} onChange={e => { setMetric(e.target.value); setSeries(''); setChosen(null) }}>{available.map(key => <option key={key} value={key}>{metrics[key].label} ({metrics[key].unit})</option>)}</select></label><h3 id={`meter-title-${sessionId}`}>Diễn biến số đo</h3>{streams.length > 1 && <label>Nguồn số đo<select value={selected} onChange={e => { setSeries(e.target.value); setChosen(null) }}>{streams.map(key => <option key={key} value={key}>{key.split('|')[0] || 'Tổng'} · {key.split('|')[1]}</option>)}</select></label>}</div>
    <svg viewBox="0 0 720 232" role="img" aria-label={`Biểu đồ ${definition.label.toLowerCase()} phiên ${sessionId}, ${points.length} số đo theo thời gian${regression ? ', có số đo giảm' : ''}`}>
      <text x="8" y="20" className="charging-chart-axis">{definition.unit}</text>
      {[0, 1, 2].map(i => { const value = floor + (ceiling - floor) * i / 2; return <g key={i}><line x1="64" x2="694" y1={y(value)} y2={y(value)} className="charging-chart-grid" /><text x="54" y={y(value) + 4} textAnchor="end" className="charging-chart-axis">{format(value)}</text></g> })}
      {points.slice(1).map((p, i) => <line key={`${p.timestamp}-${i}`} x1={x(points[i].timestamp)} y1={y(points[i].energy)} x2={x(p.timestamp)} y2={y(p.energy)} className={isEnergy && p.energy < points[i].energy ? 'charging-chart-line charging-chart-line--warning' : 'charging-chart-line'} />)}
      {points.map((p, i) => <circle key={`${p.timestamp}-${i}`} cx={x(p.timestamp)} cy={y(p.energy)} r={i === selectedIndex ? 6 : 4} className={isEnergy && i > 0 && p.energy < points[i - 1].energy ? 'charging-chart-point charging-chart-point--warning' : 'charging-chart-point'} onMouseEnter={() => setChosen(pointKey(i))} onClick={() => setChosen(pointKey(i))}><title>{time(p.timestamp)} · {format(p.energy)} {definition.unit}</title></circle>)}
      <text x="64" y="220" className="charging-chart-axis">{time(points[0].timestamp)}</text><text x="694" y="220" textAnchor="end" className="charging-chart-axis">{time(points[points.length - 1].timestamp)}</text>
    </svg>
    <div className="charging-chart-readout"><time dateTime={point.timestamp}>{new Date(point.timestamp).toLocaleString('vi-VN')}</time><strong>{format(point.energy)} {definition.unit}</strong>{isEnergy && selectedIndex > 0 && point.energy < points[selectedIndex - 1].energy && <span className="status-badge status-badge--blocked">Số đo giảm</span>}</div>
    {points.length > 1 && <label className="charging-chart-scrubber">Chọn số đo<input type="range" min="0" max={points.length - 1} value={selectedIndex} onChange={e => setChosen(pointKey(Number(e.target.value)))} aria-label={`Chọn số đo ${definition.label.toLowerCase()} phiên ${sessionId}`} aria-valuetext={`${new Date(point.timestamp).toLocaleString('vi-VN')}, ${format(point.energy)} {definition.unit}`} /></label>}
    <figcaption>{points.length} số đo · {definition.label} · {selected.split('|')[0] || 'Tổng'} / {selected.split('|')[1]}{regression ? ' · Đoạn nét đứt: số đo giảm' : ''}. Tối đa 100 bản ghi/trang.</figcaption>
  </figure>
}



