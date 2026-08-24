import React, { useEffect, useMemo, useState } from 'react'
import { getDiffs, submitDecisions, type DecisionPayload, type MemoryHint } from '../lib/api'

interface DiffRow {
  key: string; type: string; table: number; confidence: string;
  output_index: number; group: string;
  关键件名称: string; 型号: string; 规格材料: string; 制造商: string;
  生产企业: string; 证书号: string; changed_fields: string[];
  source_label: string; action: string; reason: string;
  orig_data?: Record<string, string> | null;
  plm_data?: Record<string, string> | null;
  pair_reason?: string; pair_confidence?: number;
  memory_applied?: boolean; memory?: MemoryHint | null;
  a_row?: Record<string, any> | null;
  b_row?: Record<string, any> | null;
}

// 并排对照视图展示的字段顺序（须与后端 _VERIFY_FIELDS 覆盖一致，
// 含表2特有的 本次使用/备注，否则会出现"判为不同却无字段高亮"）
const SPLIT_FIELDS = ['位号', '关键件名称', '型号', '规格材料', '制造商',
  '生产企业', '认证标准', '证书号', '本次使用', '备注']

// 视为"已决策"的裁决集合（含手动匹配纠正动作）
const DECIDED = ['accept', 'reject', 'ignore', 'reject_dup', 'reject_pair',
  'reject_same', 'reject_split', 'unpair']

export default function ReviewPage({ jobId, onDone }: { jobId: string; onDone: () => void }) {
  const [diffs, setDiffs] = useState<DiffRow[]>([])
  const [decisions, setDecisions] = useState<Record<string, string>>({})
  const [targets, setTargets] = useState<Record<string, string>>({})   // 手动匹配：key -> 目标 diff key
  const [reasons, setReasons] = useState<Record<string, string>>({})   // 决策理由（尤其拒绝）
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [filter, setFilter] = useState<string>('review') // review | all
  const [viewMode, setViewMode] = useState<'merged' | 'split'>('split') // 默认并排对照 A|B

  useEffect(() => {
    getDiffs(jobId).then(data => {
      setDiffs(data)
      const auto: Record<string, string> = {}
      data.forEach(d => { auto[d.key] = d.type === 'same' ? 'accept' : '' })
      setDecisions(auto)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [jobId])

  const reviewItems = diffs.filter(d => d.type !== 'same')
  const displayItems = filter === 'review' ? reviewItems : diffs

  // 被手动匹配"占用"为目标的行（不再单独决策，展示为"已被匹配"）
  const consumedKeys = useMemo(() => {
    const s = new Set<string>()
    diffs.forEach(d => {
      const v = decisions[d.key]
      if ((v === 'reject_dup' || v === 'reject_pair') && targets[d.key]) s.add(targets[d.key])
    })
    return s
  }, [diffs, decisions, targets])

  // 反查：某行被哪个源行匹配走了
  const consumedBy = useMemo(() => {
    const m: Record<string, DiffRow> = {}
    diffs.forEach(d => {
      const v = decisions[d.key]
      if ((v === 'reject_dup' || v === 'reject_pair') && targets[d.key]) m[targets[d.key]] = d
    })
    return m
  }, [diffs, decisions, targets])

  const jumpNextPending = () => {
    const target = reviewItems.find(d =>
      !DECIDED.includes(decisions[d.key]) && !consumedKeys.has(d.key))
    if (!target) { alert('已全部决策完成'); return }
    const el = document.getElementById('row-' + target.key)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      const old = el.style.background
      el.style.transition = 'background 0.3s'
      el.style.background = '#fff1b8'
      setTimeout(() => { el.style.background = old }, 1200)
    }
  }

  const setDecision = (key: string, value: string) => {
    setDecisions(prev => ({ ...prev, [key]: value }))
    // 切换到非手动匹配裁决时，清掉残留 target
    if (value !== 'reject_dup' && value !== 'reject_pair') {
      setTargets(prev => { const n = { ...prev }; delete n[key]; return n })
    }
  }
  const setTarget = (key: string, tkey: string) =>
    setTargets(prev => ({ ...prev, [key]: tkey }))
  const setReason = (key: string, r: string) =>
    setReasons(prev => ({ ...prev, [key]: r }))

  // 手动匹配一步到位：设裁决 + 目标（可选理由）
  const applyMatch = (key: string, verdict: 'reject_dup' | 'reject_pair', tkey: string) => {
    setDecisions(prev => ({ ...prev, [key]: verdict }))
    setTargets(prev => ({ ...prev, [key]: tkey }))
  }
  const cancelMatch = (key: string) => {
    setDecisions(prev => ({ ...prev, [key]: '' }))
    setTargets(prev => { const n = { ...prev }; delete n[key]; return n })
  }

  const allDecided = reviewItems.every(d =>
    DECIDED.includes(decisions[d.key]) || consumedKeys.has(d.key))
  const decidedCount = reviewItems.filter(d =>
    DECIDED.includes(decisions[d.key]) || consumedKeys.has(d.key)).length

  const handleSubmit = async () => {
    // 组装载荷：手动匹配/带理由 → 明细对象；其余 → 字符串
    const final: Record<string, DecisionPayload> = {}
    diffs.forEach(d => {
      if (consumedKeys.has(d.key)) return // 被匹配走的目标不单独提交
      const v = decisions[d.key] || 'accept'
      if ((v === 'reject_dup' || v === 'reject_pair')) {
        if (!targets[d.key]) return // 缺目标的手动匹配跳过（保底不误提交）
        final[d.key] = { verdict: v, target_key: targets[d.key], reason: reasons[d.key] || '' }
      } else if (reasons[d.key]) {
        final[d.key] = { verdict: v, reason: reasons[d.key] }
      } else {
        final[d.key] = v
      }
    })
    setSubmitting(true)
    try {
      await submitDecisions(jobId, final)
      onDone()
    } catch (err: any) {
      alert('提交失败：' + err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const typeLabel = (t: string) => {
    if (t === 'same') return '相同'
    if (t === 'only_orig') return 'A独有'
    if (t === 'only_plm') return 'B独有'
    if (t === 'changed') return '内容不同'
    return t
  }
  const typeColor = (t: string) => {
    if (t === 'only_plm') return '#ff4d4f'
    if (t === 'only_orig') return '#fa8c16'
    if (t === 'changed') return '#1677ff'
    return '#52c41a'
  }

  if (loading) return <div style={{ padding: 40, textAlign: 'center' }}>加载中...</div>

  const ctx: ActionCtx = {
    diffs, decisions, targets, reasons, consumedKeys, consumedBy,
    setDecision, setTarget, setReason, applyMatch, cancelMatch,
  }

  return (
    <div style={{ maxWidth: 1200, margin: '20px auto', padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <h2 style={{ margin: 0 }}>差异确认 ({reviewItems.length} 项需确认 / 共 {diffs.length} 行)</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button onClick={jumpNextPending}
            style={{ padding: '4px 12px', background: '#fa8c16', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}>
            跳到下一个待确认 ↓
          </button>
          <label>
            <input type="radio" checked={filter === 'all'} onChange={() => setFilter('all')} /> 全部（按输出顺序）
          </label>
          <label>
            <input type="radio" checked={filter === 'review'} onChange={() => setFilter('review')} /> 只看待确认
          </label>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: 12, color: '#666' }}>显示方式：</span>
        {([['split', '并排对照 A | B'], ['merged', '合并视图']] as const).map(([m, label]) => (
          <button key={m} onClick={() => setViewMode(m)}
            style={{
              padding: '4px 12px', fontSize: 12, cursor: 'pointer', borderRadius: 4,
              border: viewMode === m ? '1px solid #1677ff' : '1px solid #d9d9d9',
              background: viewMode === m ? '#e6f4ff' : '#fff',
              color: viewMode === m ? '#1677ff' : '#555', fontWeight: viewMode === m ? 600 : 400,
            }}>
            {label}
          </button>
        ))}
      </div>
      <div style={{ fontSize: 12, color: '#999', marginBottom: 6 }}>
        {viewMode === 'merged'
          ? '行序与最终生成的整合清单一致（表一在前、表二在后；旧版本独有行已归入对应关键件组）。序号即文档行号。'
          : '左＝A旧版本原始行，右＝B新版本原始行，同一水平线即为对应关系；仅一侧存在的行对侧留空，差异字段高亮标出。'}
      </div>
      <div style={{ fontSize: 12, color: '#8c8c8c', marginBottom: 12, background: '#f6f8fa', border: '1px solid #eee', borderRadius: 4, padding: '6px 10px' }}>
        拒绝策略：<b>独有项</b>可"拒绝并匹配"到另一侧对应行（完全相同→合并，有差异→配对）；
        <b>内容不同</b>可拒绝为"其实相同"或"拆成两个独有项"。
      </div>

      {viewMode === 'split' && (
        <SplitView items={displayItems} ctx={ctx} typeLabel={typeLabel} typeColor={typeColor} />
      )}
      {viewMode === 'merged' && (
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: '#fafafa' }}>
              <th style={thStyle}>#</th>
              <th style={thStyle}>类型</th>
              <th style={thStyle}>表</th>
              <th style={thStyle}>关键件名称</th>
              <th style={thStyle}>型号</th>
              <th style={thStyle}>规格材料</th>
              <th style={thStyle}>证书号</th>
              <th style={thStyle}>来源</th>
              <th style={thStyle}>AI建议</th>
              <th style={{ ...thStyle, minWidth: 220 }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {displayItems.map((d, i) => {
              const prev = i > 0 ? displayItems[i - 1] : null
              const newTable = !prev || prev.table !== d.table
              const newGroup = d.group && (!prev || prev.group !== d.group)
              const isSame = d.type === 'same'
              const decided = DECIDED.includes(decisions[d.key]) || consumedKeys.has(d.key)
              return (
              <React.Fragment key={d.key}>
                {newTable && (
                  <tr>
                    <td colSpan={10} style={{ padding: '10px 8px 4px', fontWeight: 700, fontSize: 14,
                                              borderBottom: '2px solid #e6e6e6', background: '#fff' }}>
                      {d.table === 1 ? '表一 关键件主清单' : '表二 备选件/电源单元清单'}
                    </td>
                  </tr>
                )}
                {newGroup && (
                  <tr>
                    <td colSpan={10} style={{ padding: '6px 8px', background: '#f5f5f5', fontSize: 12,
                                              color: '#555', fontWeight: 600 }}>
                      {d.group}
                    </td>
                  </tr>
                )}
                <tr id={'row-' + d.key}
                  style={{
                    borderBottom: '1px solid #f0f0f0',
                    background: isSame ? '#fff' : (decided ? '#fff' : '#fffdf5'),
                    borderLeft: isSame ? '3px solid transparent' : `3px solid ${typeColor(d.type)}`,
                    opacity: isSame ? 0.55 : 1,
                  }}>
                  <td style={{ ...tdStyle, color: '#999', fontFamily: 'monospace', fontSize: 12 }}>{d.output_index}</td>
                  <td style={tdStyle}>
                    {(() => {
                      const p = pairedSides(d, ctx)
                      if (p) return <span style={{ color: '#722ed1', fontWeight: 600 }}>{p.mode === 'same' ? '手动合并' : '手动配对'}</span>
                      return <span style={{ color: typeColor(d.type), fontWeight: 600 }}>{typeLabel(d.type)}</span>
                    })()}
                  </td>
                  <td style={tdStyle}>表{d.table}</td>
                  <td style={tdStyle}>{d.关键件名称?.slice(0, 20)}</td>
                  <td style={tdStyle}>{d.型号?.slice(0, 30)}</td>
                  <td style={tdStyle}>{d.规格材料?.slice(0, 20)}</td>
                  <td style={tdStyle}>{d.证书号?.slice(0, 20)}</td>
                  <td style={tdStyle}>{d.source_label}</td>
                  <td style={tdStyle}>
                    <span style={{ fontSize: 11, color: '#666' }}>{d.action} {d.reason?.slice(0, 20)}</span>
                    {d.memory_applied && <MemoryBadge hint={d.memory || null} />}
                  </td>
                  <td style={{ ...tdStyle, verticalAlign: 'top' }}>
                    <ActionCell d={d} ctx={ctx} />
                  </td>
                </tr>
                {d.pair_reason && (
                  <tr style={{ background: '#fff' }}>
                    <td colSpan={10} style={{ padding: '4px 16px', background: '#f6ffed', borderLeft: '3px solid #fa8c16' }}>
                      <span style={{ fontSize: 12, color: '#d46b08' }}>
                        🤖 AI 疑似同一件（置信度 {Math.round((d.pair_confidence || 0) * 100)}%）：{d.pair_reason}
                        　—　默认合并为一行；若非同一物料请点"拒绝配对(拆开)"分别保留。
                      </span>
                    </td>
                  </tr>
                )}
                {(() => {
                  // 手动匹配预览优先；否则回退到后端给的 CHANGED 对比数据
                  const paired = pairedSides(d, ctx)
                  let oData: Record<string, string> | null = null
                  let pData: Record<string, string> | null = null
                  if (paired) {
                    oData = fieldMap(paired.aRow); pData = fieldMap(paired.bRow)
                  } else if (d.type === 'changed' && d.orig_data && d.plm_data) {
                    oData = d.orig_data as Record<string, string>
                    pData = d.plm_data as Record<string, string>
                  }
                  if (!oData || !pData) return null
                  return (
                    <tr style={{ background: '#fff' }}>
                      <td colSpan={10} style={{ padding: '10px 16px', fontSize: 12, background: paired ? '#faf5ff' : '#fff' }}>
                        {paired && (
                          <div style={{ fontSize: 11, color: '#722ed1', marginBottom: 6 }}>
                            🔗 手动{paired.mode === 'same' ? '合并为相同' : '配对为差异'}预览（差异字段已高亮，提交后写入整合清单）
                          </div>
                        )}
                        <CompareSubTable oData={oData} pData={pData} />
                      </td>
                    </tr>
                  )
                })()}
              </React.Fragment>
            )})}
          </tbody>
        </table>
      </div>
      )}

      <div style={{ marginTop: 24, textAlign: 'center' }}>
        <button onClick={() => {
          const all: Record<string, string> = {}
          reviewItems.forEach(d => { if (!consumedKeys.has(d.key)) all[d.key] = 'accept' })
          setDecisions(prev => ({ ...prev, ...all }))
        }}
          style={{ padding: '8px 24px', background: '#52c41a', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', marginRight: 16 }}>
          全部接受
        </button>
        <button onClick={handleSubmit} disabled={submitting}
          style={{ padding: '12px 48px', background: allDecided ? '#1677ff' : '#91caff', color: '#fff', border: 'none', borderRadius: 6, fontSize: 16, cursor: 'pointer' }}>
          {submitting ? '提交中...' : `提交决策 (${decidedCount}/${reviewItems.length} 已决策)`}
        </button>
      </div>
    </div>
  )
}

// ===== 决策上下文（透传给 ActionCell / SplitView）=====
interface ActionCtx {
  diffs: DiffRow[]
  decisions: Record<string, string>
  targets: Record<string, string>
  reasons: Record<string, string>
  consumedKeys: Set<string>
  consumedBy: Record<string, DiffRow>
  setDecision: (k: string, v: string) => void
  setTarget: (k: string, t: string) => void
  setReason: (k: string, r: string) => void
  applyMatch: (k: string, v: 'reject_dup' | 'reject_pair', t: string) => void
  cancelMatch: (k: string) => void
}

// ===== 记忆反哺标记 =====
function MemoryBadge({ hint }: { hint: MemoryHint | null }) {
  const tip = hint
    ? `长期记忆：历史确认 ${hint.accepts} 次 / 否决 ${hint.rejects} 次` +
      (hint.last_reason ? `\n近因：${hint.last_reason}` : '')
    : '命中长期记忆'
  const rejectDominant = hint && hint.dominant === 'reject'
  return (
    <span title={tip} style={{
      marginLeft: 6, fontSize: 10, padding: '0 4px', borderRadius: 3, whiteSpace: 'nowrap',
      background: rejectDominant ? '#fff1f0' : '#f6ffed',
      color: rejectDominant ? '#cf1322' : '#389e0d',
      border: `1px solid ${rejectDominant ? '#ffa39e' : '#b7eb8f'}`,
    }}>
      🧠记忆{hint ? ` ${hint.accepts}✓/${hint.rejects}✗` : ''}
    </span>
  )
}

// ===== 操作单元：接受/拒绝 + 手动匹配 + 差异纠正 =====
function ActionCell({ d, ctx }: { d: DiffRow; ctx: ActionCtx }) {
  const [open, setOpen] = useState(false)
  const v = ctx.decisions[d.key] || ''

  if (d.type === 'same') return <span style={{ color: '#52c41a' }}>自动保留</span>

  // 本行被其它行手动匹配走了 → 展示"已被匹配"，不再单独决策
  if (ctx.consumedKeys.has(d.key)) {
    const src = ctx.consumedBy[d.key]
    return (
      <span style={{ fontSize: 12, color: '#722ed1' }}>
        🔗 已被 #{src?.output_index} 匹配{ctx.decisions[src?.key || ''] === 'reject_dup' ? '(相同)' : '(差异)'}
      </span>
    )
  }

  // LLM 提名配对：接受合并 / 拒绝拆开（沿用原逻辑）
  if (d.pair_reason) {
    return (
      <div style={{ display: 'flex', gap: 4 }}>
        <Btn on={v === 'accept'} color="#52c41a" onClick={() => ctx.setDecision(d.key, v === 'accept' ? '' : 'accept')}>接受配对</Btn>
        <Btn on={v === 'unpair'} color="#fa8c16" onClick={() => ctx.setDecision(d.key, v === 'unpair' ? '' : 'unpair')} title="拆开为两行分别保留，不合并">拒绝配对(拆开)</Btn>
      </div>
    )
  }

  const isOnly = d.type === 'only_plm' || d.type === 'only_orig'
  const isChanged = d.type === 'changed'
  // 单选：再次点击已选中的裁决 → 取消（回到未决策）；切换裁决时关掉匹配弹窗
  const choose = (verdict: string) => { setOpen(false); ctx.setDecision(d.key, v === verdict ? '' : verdict) }

  // 已选定手动匹配 → 展示摘要 + 重新选择 + 取消
  if ((v === 'reject_dup' || v === 'reject_pair') && ctx.targets[d.key]) {
    const tgt = ctx.diffs.find(x => x.key === ctx.targets[d.key])
    return (
      <div style={{ fontSize: 12 }}>
        <div style={{ color: '#722ed1', marginBottom: 4 }}>
          🔗 匹配到 #{tgt?.output_index} {tgt?.关键件名称?.slice(0, 12)}
          {v === 'reject_dup' ? '（合并为相同）' : '（配对为差异）'}
        </div>
        <button onClick={() => setOpen(true)} style={{ ...linkBtn, marginRight: 10 }}>重新选择</button>
        <button onClick={() => ctx.cancelMatch(d.key)} style={linkBtn}>取消匹配</button>
        <input value={ctx.reasons[d.key] || ''} placeholder="配对理由(选填)"
          onChange={e => ctx.setReason(d.key, e.target.value)}
          style={{ marginTop: 4, width: '100%', fontSize: 11, padding: '2px 4px', border: '1px solid #eee', borderRadius: 3 }} />
        {open && <MatchModal d={d} ctx={ctx} onClose={() => setOpen(false)} />}
      </div>
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        <Btn on={v === 'accept'} color="#52c41a" onClick={() => choose('accept')}>
          {isOnly ? '接受(独有)' : '接受(差异)'}
        </Btn>
        {isChanged && (
          <>
            <Btn on={v === 'reject_same'} color="#13c2c2" onClick={() => choose('reject_same')} title="两侧其实一致，合并为一份">其实相同</Btn>
            <Btn on={v === 'reject_split'} color="#fa8c16" onClick={() => choose('reject_split')} title="不是同一个件，拆成两个独有项">拆两独有</Btn>
          </>
        )}
        {isOnly && (
          <Btn on={open} color="#722ed1"
            onClick={() => setOpen(o => !o)}
            title="拒绝独有判定：另一侧其实有对应项，手动匹配">拒绝并匹配 ▾</Btn>
        )}
        <Btn on={v === 'reject'} color="#ff4d4f" onClick={() => choose('reject')} title="直接丢弃该行">拒绝(丢弃)</Btn>
      </div>
      {isOnly && open && <MatchModal d={d} ctx={ctx} onClose={() => setOpen(false)} />}
      {(v === 'reject' || v === 'reject_same' || v === 'reject_split') && (
        <input value={ctx.reasons[d.key] || ''} placeholder="理由(选填)"
          onChange={e => ctx.setReason(d.key, e.target.value)}
          style={{ marginTop: 4, width: '100%', fontSize: 11, padding: '2px 4px', border: '1px solid #eee', borderRadius: 3 }} />
      )}
    </div>
  )
}

// ===== 手动匹配弹窗：全屏居中，多列完整展示另一侧独有项，点选行 =====
function MatchModal({ d, ctx, onClose }: { d: DiffRow; ctx: ActionCtx; onClose: () => void }) {
  const [q, setQ] = useState('')
  const [sel, setSel] = useState(ctx.targets[d.key] || '')
  const wantType = d.type === 'only_plm' ? 'only_orig' : 'only_plm'
  const sideLabel = wantType === 'only_orig' ? 'A · 旧版本（原始清单）' : 'B · 新版本（PLM导出）'
  const candidates = useMemo(() => {
    const kw = q.trim()
    return ctx.diffs.filter(x =>
      x.type === wantType && x.table === d.table && !ctx.consumedKeys.has(x.key) && x.key !== d.key &&
      (!kw || (x.关键件名称 + x.型号 + x.规格材料 + x.制造商 + x.证书号).includes(kw))
    )
  }, [ctx.diffs, ctx.consumedKeys, q, wantType, d.table, d.key])

  const apply = (verdict: 'reject_dup' | 'reject_pair') => {
    if (!sel) { alert('请先在下表中点选一行作为对应目标'); return }
    ctx.applyMatch(d.key, verdict, sel)
    onClose()
  }

  const mTh: React.CSSProperties = { position: 'sticky', top: 0, background: '#fafafa', padding: '6px 8px', textAlign: 'left', borderBottom: '2px solid #eee', fontWeight: 600, whiteSpace: 'nowrap' }
  const mTd: React.CSSProperties = { padding: '6px 8px', borderBottom: '1px solid #f0f0f0', verticalAlign: 'top', wordBreak: 'break-all' }

  return (
    <div onClick={onClose}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div onClick={e => e.stopPropagation()}
        style={{ background: '#fff', width: 'min(860px, 94vw)', maxHeight: '82vh', borderRadius: 8, boxShadow: '0 8px 32px rgba(0,0,0,0.25)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* 头部：本行信息 */}
        <div style={{ padding: '12px 16px', borderBottom: '1px solid #eee', background: '#faf5ff' }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#722ed1' }}>手动匹配 · 为本行选择对应项</div>
          <div style={{ fontSize: 12, color: '#555', marginTop: 4 }}>
            本行（{d.type === 'only_plm' ? 'B新版本独有' : 'A旧版本独有'} #{d.output_index}）：
            <b>{d.关键件名称}</b>　型号：{d.型号 || '-'}　规格：{d.规格材料 || '-'}　制造商：{d.制造商 || '-'}　证书号：{d.证书号 || '-'}
          </div>
          <div style={{ fontSize: 12, color: '#888', marginTop: 4 }}>
            从 <b>{sideLabel}</b> 的独有项中点选与本行对应的目标（同表{d.table}，共 {candidates.length} 个候选）：
          </div>
          <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="按 名称/型号/规格/制造商/证书号 过滤…"
            style={{ width: '100%', fontSize: 13, padding: '6px 10px', border: '1px solid #d9d9d9', borderRadius: 4, marginTop: 8, boxSizing: 'border-box' }} />
        </div>
        {/* 候选列表 */}
        <div style={{ overflow: 'auto', flex: 1 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr>
                <th style={{ ...mTh, width: 50 }}>#</th>
                <th style={{ ...mTh, width: 140 }}>关键件名称</th>
                <th style={mTh}>型号</th>
                <th style={{ ...mTh, width: 130 }}>制造商</th>
                <th style={{ ...mTh, width: 120 }}>证书号</th>
              </tr>
            </thead>
            <tbody>
              {candidates.length === 0 && (
                <tr><td colSpan={5} style={{ ...mTd, textAlign: 'center', color: '#999', padding: 24 }}>无匹配候选（可清空过滤词，或确认是否同一表）</td></tr>
              )}
              {candidates.map(c => {
                const on = sel === c.key
                return (
                  <tr key={c.key} onClick={() => setSel(c.key)}
                    style={{ cursor: 'pointer', background: on ? '#e6f4ff' : '#fff', outline: on ? '2px solid #1677ff' : 'none' }}>
                    <td style={{ ...mTd, fontFamily: 'monospace', color: '#999' }}>{on ? '● ' : ''}{c.output_index}</td>
                    <td style={mTd}>{c.关键件名称 || '-'}</td>
                    <td style={mTd}>{c.型号 || '-'}</td>
                    <td style={mTd}>{c.制造商 || '-'}</td>
                    <td style={mTd}>{c.证书号 || '-'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        {/* 底部操作 */}
        <div style={{ padding: '12px 16px', borderTop: '1px solid #eee', display: 'flex', gap: 10, alignItems: 'center', justifyContent: 'flex-end' }}>
          <span style={{ marginRight: 'auto', fontSize: 12, color: sel ? '#1677ff' : '#999' }}>
            {sel ? `已选 #${ctx.diffs.find(x => x.key === sel)?.output_index}` : '未选择'}
          </span>
          <button disabled={!sel} onClick={() => apply('reject_dup')}
            style={{ padding: '6px 14px', border: 'none', borderRadius: 4, cursor: sel ? 'pointer' : 'not-allowed', background: sel ? '#13c2c2' : '#d9d9d9', color: '#fff', fontSize: 13 }}
            title="两侧完全相同，合并为一份">完全相同 → 合并</button>
          <button disabled={!sel} onClick={() => apply('reject_pair')}
            style={{ padding: '6px 14px', border: 'none', borderRadius: 4, cursor: sel ? 'pointer' : 'not-allowed', background: sel ? '#1677ff' : '#d9d9d9', color: '#fff', fontSize: 13 }}
            title="同一件但有差异，配对为内容不同">有差异 → 配对</button>
          <button onClick={onClose} style={{ padding: '6px 14px', border: '1px solid #d9d9d9', borderRadius: 4, cursor: 'pointer', background: '#fff', fontSize: 13 }}>取消</button>
        </div>
      </div>
    </div>
  )
}

// ===== 并排对照视图：左 A旧版本 / 中 对应关系 / 右 B新版本 =====
function SplitView({ items, ctx, typeLabel, typeColor }: {
  items: DiffRow[]
  ctx: ActionCtx
  typeLabel: (t: string) => string
  typeColor: (t: string) => string
}) {
  const relation = (d: DiffRow, v: string) => {
    if (v === 'reject_same') return { sym: '🔗＝', color: '#722ed1', tip: '已确认：两侧其实相同' }
    if (v === 'reject_split') return { sym: '✂', color: '#722ed1', tip: '已确认：拆成两个独有项' }
    if (d.pair_reason) return { sym: '🤖≈', color: '#d46b08', tip: 'AI 提名疑似同一件' }
    if (d.type === 'same') return { sym: '＝', color: '#bbb', tip: '两侧一致' }
    if (d.type === 'changed') return { sym: '≠', color: '#1677ff', tip: '同一件，内容有差异' }
    if (d.type === 'only_orig') return { sym: '←', color: '#fa8c16', tip: '仅旧版本有（保留）' }
    return { sym: '→', color: '#ff4d4f', tip: '仅新版本有（新增）' }
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, tableLayout: 'fixed' }}>
        <colgroup>
          <col style={{ width: '38px' }} />
          <col style={{ width: '34%' }} />
          <col style={{ width: '84px' }} />
          <col style={{ width: '34%' }} />
          <col style={{ width: '210px' }} />
        </colgroup>
        <thead>
          <tr style={{ background: '#fafafa' }}>
            <th style={thStyle}>#</th>
            <th style={{ ...thStyle, color: '#fa8c16' }}>A · 旧版本（原始清单）</th>
            <th style={{ ...thStyle, textAlign: 'center' }}>对应</th>
            <th style={{ ...thStyle, color: '#1677ff' }}>B · 新版本（PLM导出）</th>
            <th style={thStyle}>操作</th>
          </tr>
        </thead>
        <tbody>
          {items.map(d => {
            // 该行被其它行手动匹配走了 → 折叠为一行提示，配对预览在源行展示
            const src = ctx.consumedBy[d.key]
            if (src) {
              return (
                <tr key={d.key} id={'row-' + d.key} style={{ borderBottom: '1px solid #eee', background: '#faf5ff', opacity: 0.85 }}>
                  <td style={{ ...tdStyle, color: '#999', fontFamily: 'monospace', verticalAlign: 'top' }}>{d.output_index}</td>
                  <td colSpan={3} style={{ ...tdStyle, color: '#722ed1' }}>
                    🔗 本行已并入 #{src.output_index} 的手动配对预览（{ctx.decisions[src.key] === 'reject_dup' ? '合并为相同' : '配对为差异'}）
                  </td>
                  <td style={{ ...tdStyle, verticalAlign: 'top' }}>
                    <button onClick={() => ctx.cancelMatch(src.key)} style={linkBtn}>取消该匹配</button>
                  </td>
                </tr>
              )
            }

            const v = ctx.decisions[d.key] || ''
            const paired = pairedSides(d, ctx)
            // 手动匹配预览：两侧都填充；差异靠 SideCell 直接比对高亮（含型号）
            const a = paired ? paired.aRow : (d.a_row || null)
            const b = paired ? paired.bRow : (d.b_row || null)
            const rel = paired
              ? (paired.mode === 'same'
                  ? { sym: '🔗＝', color: '#722ed1', tip: '手动合并为相同' }
                  : { sym: '🔗≠', color: '#722ed1', tip: '手动配对为差异（型号等差异已高亮）' })
              : relation(d, v)
            // 手动配对预览：不依赖后端 changed_fields，SideCell 用两侧直接比对高亮
            const diffSet = new Set(paired ? [] : (d.changed_fields || []))
            const isSame = d.type === 'same' && !paired
            const previewing = !!paired
            return (
              <tr key={d.key} id={'row-' + d.key} style={{
                borderBottom: '1px solid #eee',
                background: previewing ? '#faf5ff' : (isSame ? '#fff' : (d.type === 'changed' || d.pair_reason ? '#fbfdff' : '#fffdf5')),
                opacity: isSame ? 0.6 : 1,
                boxShadow: previewing ? 'inset 3px 0 0 #722ed1' : undefined,
              }}>
                <td style={{ ...tdStyle, color: '#999', fontFamily: 'monospace', verticalAlign: 'top' }}>
                  {d.output_index}
                </td>
                <td style={{ ...tdStyle, verticalAlign: 'top', borderLeft: `3px solid ${a ? '#ffd591' : 'transparent'}` }}>
                  {a ? <SideCell row={a} other={b} diffSet={diffSet} side="a" />
                     : <EmptySide text="旧版本无此行（新版本新增）" />}
                </td>
                <td style={{ ...tdStyle, textAlign: 'center', verticalAlign: 'middle' }} title={rel.tip}>
                  <div style={{ fontSize: 18, fontWeight: 700, color: rel.color, lineHeight: 1.2 }}>{rel.sym}</div>
                  <div style={{ fontSize: 10, color: previewing ? '#722ed1' : typeColor(d.type), fontWeight: 600 }}>
                    {previewing ? (paired!.mode === 'same' ? '手动合并' : '手动配对') : typeLabel(d.type)}
                  </div>
                  {a && b && (
                    <div style={{ fontSize: 10, color: '#aaa', fontFamily: 'monospace', marginTop: 2 }}>
                      A#{a._row_index}→B#{b._row_index}
                    </div>
                  )}
                  {a && !b && <div style={{ fontSize: 10, color: '#aaa', fontFamily: 'monospace' }}>A#{a._row_index}</div>}
                  {!a && b && <div style={{ fontSize: 10, color: '#aaa', fontFamily: 'monospace' }}>B#{b._row_index}</div>}
                </td>
                <td style={{ ...tdStyle, verticalAlign: 'top', borderLeft: `3px solid ${b ? '#91caff' : 'transparent'}` }}>
                  {b ? <SideCell row={b} other={a} diffSet={diffSet} side="b" />
                     : <EmptySide text="新版本无此行（旧版本保留）" />}
                </td>
                <td style={{ ...tdStyle, verticalAlign: 'top' }}>
                  <ActionCell d={d} ctx={ctx} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** 一侧的字段列表：差异字段高亮 + 词级标注 */
function SideCell({ row, other, diffSet, side }: {
  row: Record<string, any>
  other: Record<string, any> | null
  diffSet: Set<string>
  side: 'a' | 'b'
}) {
  const hlColor = side === 'a' ? '#ffccc7' : '#b7eb8f'
  return (
    <div>
      {row._group ? (
        <div style={{ fontSize: 10, color: '#999', marginBottom: 2 }}>［{row._group}］</div>
      ) : null}
      {SPLIT_FIELDS.map(f => {
        const val = (row[f] ?? '') as string
        const oth = (other?.[f] ?? '') as string
        const isDiff = other != null && (val !== oth || diffSet.has(f))
        if (!val && !isDiff) return null
        return (
          <div key={f} style={{
            display: 'flex', gap: 4, lineHeight: 1.5,
            background: isDiff ? '#fffbe6' : 'transparent', borderRadius: 2, padding: isDiff ? '0 2px' : 0,
          }}>
            <span style={{ color: isDiff ? '#d4380d' : '#999', minWidth: 56, flexShrink: 0, fontWeight: isDiff ? 600 : 400 }}>
              {isDiff ? '● ' : ''}{f}
            </span>
            <span style={{ wordBreak: 'break-all' }}>
              {isDiff && other ? renderWordDiff(val, oth, hlColor) : (val || '-')}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function EmptySide({ text }: { text: string }) {
  return (
    <div style={{
      background: 'repeating-linear-gradient(45deg,#fafafa,#fafafa 6px,#f0f0f0 6px,#f0f0f0 12px)',
      color: '#999', textAlign: 'center', padding: '14px 8px', borderRadius: 3, fontSize: 12,
    }}>
      — {text} —
    </div>
  )
}

// 手动匹配即时预览：返回合并后的两侧行 + 模式；无有效手动匹配返回 null
function pairedSides(d: DiffRow, ctx: ActionCtx): { aRow: any; bRow: any; mode: 'same' | 'diff' } | null {
  const v = ctx.decisions[d.key]
  const tkey = ctx.targets[d.key]
  if ((v === 'reject_dup' || v === 'reject_pair') && tkey) {
    const t = ctx.diffs.find(x => x.key === tkey) || null
    const aRow = d.a_row || t?.a_row || null
    const bRow = d.b_row || t?.b_row || null
    return { aRow, bRow, mode: v === 'reject_dup' ? 'same' : 'diff' }
  }
  return null
}

// A/B 字段对比子表（合并视图用）：差异字段行高亮 + 词级高亮
function CompareSubTable({ oData, pData }: { oData: Record<string, string>; pData: Record<string, string> }) {
  const allKeys = SPLIT_FIELDS.filter(k => (oData[k] || '') || (pData[k] || ''))
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', background: '#fff' }}>
      <thead>
        <tr>
          <th style={{ ...cmpTh, width: 90 }}>字段</th>
          <th style={cmpTh}>A（旧版本）</th>
          <th style={cmpTh}>B（新版本）</th>
        </tr>
      </thead>
      <tbody>
        {allKeys.map(k => {
          const isDiff = (oData[k] || '') !== (pData[k] || '')
          return (
            <tr key={k} style={{ background: isDiff ? '#fffbe6' : '#fff' }}>
              <td style={{ ...cmpTd, color: isDiff ? '#d4380d' : '#888', fontWeight: isDiff ? 600 : 400 }}>
                {isDiff ? '● ' : ''}{k}
              </td>
              <td style={cmpTd}>{isDiff ? renderWordDiff(oData[k] || '', pData[k] || '', '#ffccc7') : (oData[k] || '-')}</td>
              <td style={cmpTd}>{isDiff ? renderWordDiff(pData[k] || '', oData[k] || '', '#b7eb8f') : (pData[k] || '-')}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

// 从 a_row/b_row 提取 SPLIT_FIELDS 映射，供 CompareSubTable 使用
function fieldMap(row: Record<string, any> | null): Record<string, string> {
  const m: Record<string, string> = {}
  if (row) SPLIT_FIELDS.forEach(f => { m[f] = (row[f] ?? '') as string })
  return m
}

function Btn({ on, color, onClick, title, children }: {
  on: boolean; color: string; onClick: () => void; title?: string; children: React.ReactNode
}) {
  return (
    <button onClick={onClick} title={title}
      style={{ ...btnStyle, background: on ? color : '#f0f0f0', color: on ? '#fff' : '#333' }}>
      {children}
    </button>
  )
}

const thStyle: React.CSSProperties = { padding: '8px 6px', textAlign: 'left', borderBottom: '2px solid #eee', whiteSpace: 'nowrap' }
const tdStyle: React.CSSProperties = { padding: '6px', borderBottom: '1px solid #f5f5f5' }
const btnStyle: React.CSSProperties = { padding: '2px 8px', border: 'none', borderRadius: 3, cursor: 'pointer', fontSize: 12 }
const linkBtn: React.CSSProperties = { background: 'none', border: 'none', color: '#1677ff', cursor: 'pointer', fontSize: 12, padding: 0 }
const cmpTh: React.CSSProperties = { padding: '4px 8px', textAlign: 'left', borderBottom: '1px solid #eee', background: '#fafafa', color: '#666', fontWeight: 600 }
const cmpTd: React.CSSProperties = { padding: '4px 8px', borderBottom: '1px solid #f5f5f5', verticalAlign: 'top', lineHeight: 1.6 }

function tokenize(s: string): string[] {
  if (!s) return []
  return s.split(/(\s+|[,，、;；])/).filter(t => t.length > 0)
}

function renderWordDiff(self: string, other: string, color: string): React.ReactNode {
  const selfTokens = tokenize(self)
  const otherSet = new Set(tokenize(other).map(t => t.trim()).filter(Boolean))
  return selfTokens.map((tok, i) => {
    const trimmed = tok.trim()
    const isUnique = trimmed && !otherSet.has(trimmed)
    return isUnique
      ? <span key={i} style={{ background: color, fontWeight: 700, borderRadius: 2, padding: '0 1px' }}>{tok}</span>
      : <span key={i}>{tok}</span>
  })
}
