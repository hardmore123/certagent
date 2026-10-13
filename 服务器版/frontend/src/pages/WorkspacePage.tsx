import { useEffect, useRef, useState } from 'react'
import { apiUrl, createJob, getResult, listJobs, type AuditReport } from '../lib/api'

/**
 * 文件头校验（思路 C）：读文件前几个字节判断真实格式
 * - 真 .docx = ZIP archive，文件头 "PK\x03\x04" = "504B0304"
 * - 真 .doc  = OLE2 复合文档，文件头 "D0\xCF\x11\xE0" = "D0CF11E0"
 * - JSON fixture 由后缀判断
 * - 其它文件头（如透明加密的 .docx，磁盘字节是密文）→ 放行，交给后端解密服务兜底
 * 避免 .doc 重命名成 .docx 后被前端放过、后端又解析失败
 */
async function checkFileFormat(file: File): Promise<{ ok: boolean; format: string; msg?: string }> {
  const lower = file.name.toLowerCase()
  // JSON fixture 走后缀判断（不读 magic bytes，避免编码问题）
  if (lower.endsWith('.json')) {
    return { ok: true, format: 'json' }
  }
  // 读前 8 字节
  const buf = new Uint8Array(await file.slice(0, 8).arrayBuffer())
  const hex = Array.from(buf).map(b => b.toString(16).padStart(2, '0').toUpperCase()).join('')
  // 真 .docx
  if (hex.startsWith('504B0304') || hex.startsWith('504B0506') || hex.startsWith('504B0708')) {
    return { ok: true, format: 'docx' }
  }
  // 真 .doc（OLE2 复合文档）→ 不允许上传
  if (hex.startsWith('D0CF11E0')) {
    return {
      ok: false,
      format: 'doc',
      msg: `检测到这是 .doc 格式（OLE 复合文档），不是 .docx。请用 Word 打开后「文件 → 另存为 .docx」再上传（不要只改后缀名）。`,
    }
  }
  // 其它文件头（透明加密 .docx 的密文字节 / 未知）→ 放行，后端 _load_one 会调解密服务还原；
  // 若既不是合法 docx 也解不开，后端会抛清晰错误，不会静默产出错误结果。
  return { ok: true, format: 'encrypted-or-unknown' }
}

interface Job {
  job_id: string; status: string; stage: string; progress: number;
  file_orig: string; file_plm: string; diff_count: number; error: string;
}

async function downloadFile(jobId: string, type: 'merged' | 'compare', filename: string) {
  const token = localStorage.getItem('token')
  const resp = await fetch(apiUrl(`/jobs/${jobId}/result/${type}`), {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!resp.ok) {
    alert('下载失败: ' + resp.statusText)
    return
  }
  const blob = await resp.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export default function WorkspacePage({ onReview }: { onReview: (id: string) => void }) {
  const [jobs, setJobs] = useState<Job[]>([])
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [audits, setAudits] = useState<Record<string, AuditReport>>({})
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [fuzzyLlm, setFuzzyLlm] = useState(false)
  const origRef = useRef<HTMLInputElement>(null)
  const plmRef = useRef<HTMLInputElement>(null)

  const fetchJobs = async () => {
    try {
      const list = await listJobs()
      setJobs(list)
      // 为已完成且尚未取过审计报告的任务拉取一次
      list.filter(j => j.status === 'done').forEach(j => {
        setAudits(prev => {
          if (prev[j.job_id]) return prev
          getResult(j.job_id).then(r => {
            if (r.audit) setAudits(p => ({ ...p, [j.job_id]: r.audit as AuditReport }))
          }).catch(() => { })
          return prev
        })
      })
    } catch { }
  }

  useEffect(() => {
    fetchJobs()
    const timer = setInterval(fetchJobs, 3000)
    return () => clearInterval(timer)
  }, [])

  const handleUpload = async () => {
    const orig = origRef.current?.files?.[0]
    const plm = plmRef.current?.files?.[0]
    if (!orig || !plm) { setError('请选择两份文件'); return }

    // 思路 C：文件头校验，杜绝 .doc 伪装 .docx
    setUploading(true)
    setError('')
    try {
      const origCheck = await checkFileFormat(orig)
      if (!origCheck.ok) {
        setError(`【原始清单】${orig.name} → ${origCheck.msg}`)
        setUploading(false)
        return
      }
      const plmCheck = await checkFileFormat(plm)
      if (!plmCheck.ok) {
        setError(`【PLM清单】${plm.name} → ${plmCheck.msg}`)
        setUploading(false)
        return
      }
      await createJob(orig, plm, fuzzyLlm)
      await fetchJobs()
    } catch (err: any) {
      setError(err.message)
    } finally {
      setUploading(false)
    }
  }

  const statusColor = (s: string) => {
    if (s === 'done') return '#52c41a'
    if (s === 'failed') return '#ff4d4f'
    if (s === 'review') return '#fa8c16'
    return '#1677ff'
  }

  return (
    <div style={{ maxWidth: 900, margin: '40px auto', padding: 24 }}>
      <h2>工作台</h2>

      {/* 上传区 */}
      <div style={{ border: '1px dashed #d9d9d9', padding: 20, borderRadius: 8, marginBottom: 24 }}>
        <h4>上传清单</h4>
        <div style={{
          background: '#fffbe6', border: '1px solid #ffe58f', borderRadius: 4,
          padding: '8px 12px', marginBottom: 12, fontSize: 13, color: '#874d00',
        }}>
          ⚠️ 服务器暂不支持 <b>.doc</b> 格式自动转换。
          请先用 Word 打开 → <b>「另存为 .docx」</b> → 再上传。
        </div>
        <div style={{ marginBottom: 8 }}>
          <label>输入 A（原始清单·人工整理 / 旧版本·变更前）：</label>
          <input type="file" ref={origRef} accept=".docx,.json" />
        </div>
        <div style={{ marginBottom: 8 }}>
          <label>输入 B（PLM 导出·新品 / 新版本·变更后）：</label>
          <input type="file" ref={plmRef} accept=".docx,.json" />
        </div>
        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 13, cursor: 'pointer', userSelect: 'none' }}>
            <input type="checkbox" checked={fuzzyLlm} onChange={e => setFuzzyLlm(e.target.checked)} style={{ marginRight: 6 }} />
            🤖 启用 AI 智能配对
          </label>
          <span style={{ fontSize: 12, color: '#999', marginLeft: 8 }}>
            对规则未能匹配的残余行，用 AI 提名"疑似同一件"（结果仍需人工确认，会稍慢一点）
          </span>
        </div>
        {error && <div style={{ color: 'red', marginBottom: 8 }}>{error}</div>}
        <button onClick={handleUpload} disabled={uploading}
          style={{ padding: '8px 24px', background: '#1677ff', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>
          {uploading ? '上传中...' : (fuzzyLlm ? '开始整合（含AI配对）' : '开始整合')}
        </button>
      </div>

      {/* 任务列表 */}
      <h4>任务列表</h4>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ background: '#fafafa' }}>
            <th style={{ padding: 8, textAlign: 'left', borderBottom: '1px solid #eee' }}>任务ID</th>
            <th style={{ padding: 8, textAlign: 'left', borderBottom: '1px solid #eee' }}>文件</th>
            <th style={{ padding: 8, textAlign: 'left', borderBottom: '1px solid #eee' }}>状态</th>
            <th style={{ padding: 8, textAlign: 'left', borderBottom: '1px solid #eee' }}>进度</th>
            <th style={{ padding: 8, textAlign: 'left', borderBottom: '1px solid #eee' }}>操作</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map(j => {
            const audit = audits[j.job_id]
            return (
            <>
            <tr key={j.job_id} style={{ borderBottom: '1px solid #f0f0f0' }}>
              <td style={{ padding: 8, fontSize: 12, fontFamily: 'monospace' }}>{j.job_id.slice(0, 8)}</td>
              <td style={{ padding: 8, fontSize: 12 }}>{j.file_orig} + {j.file_plm}</td>
              <td style={{ padding: 8 }}>
                <span style={{ color: statusColor(j.status), fontWeight: 600 }}>{j.status}</span>
                {j.stage && <span style={{ color: '#888', marginLeft: 8 }}>{j.stage}</span>}
              </td>
              <td style={{ padding: 8 }}>
                <div style={{ width: 100, height: 8, background: '#f0f0f0', borderRadius: 4 }}>
                  <div style={{ width: `${j.progress * 100}%`, height: '100%', background: statusColor(j.status), borderRadius: 4 }} />
                </div>
              </td>
              <td style={{ padding: 8 }}>
                {j.status === 'review' && (
                  <button onClick={() => onReview(j.job_id)}
                    style={{ padding: '4px 12px', background: '#fa8c16', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>
                    确认差异
                  </button>
                )}
                {j.status === 'done' && (
                  <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
                    <button onClick={() => downloadFile(j.job_id, 'merged', '整合版关键件清单.docx')}
                      style={{ padding: '4px 8px', background: '#52c41a', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}>
                      下载清单
                    </button>
                    <button onClick={() => downloadFile(j.job_id, 'compare', '变更前后对照表.docx')}
                      style={{ padding: '4px 8px', background: '#1677ff', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}>
                      下载对照表
                    </button>
                    {audit && (
                      <span onClick={() => setExpanded(p => ({ ...p, [j.job_id]: !p[j.job_id] }))}
                        title="点击查看数据守恒审计详情"
                        style={{
                          padding: '3px 8px', borderRadius: 10, fontSize: 12, cursor: 'pointer',
                          color: '#fff', background: auditColor(audit.status), whiteSpace: 'nowrap',
                        }}>
                        {auditBadge(audit)} {expanded[j.job_id] ? '▲' : '▼'}
                      </span>
                    )}
                  </div>
                )}
                {j.status === 'failed' && (
                  <span style={{ color: '#ff4d4f', fontSize: 12 }}>{j.error?.slice(0, 50)}</span>
                )}
              </td>
            </tr>
            {j.status === 'done' && audit && expanded[j.job_id] && (
              <tr key={j.job_id + '-audit'}>
                <td colSpan={5} style={{ padding: '12px 16px', background: '#fafafa', borderBottom: '1px solid #f0f0f0' }}>
                  <AuditPanel audit={audit} />
                </td>
              </tr>
            )}
            </>
          )})}
          {jobs.length === 0 && (
            <tr><td colSpan={5} style={{ padding: 24, textAlign: 'center', color: '#999' }}>暂无任务</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function auditColor(status: string): string {
  if (status === 'ok') return '#52c41a'
  if (status === 'warning') return '#fa8c16'
  return '#ff4d4f' // critical
}

function auditBadge(_audit: AuditReport): string {
  return '审计面板'
}

function AuditPanel({ audit }: { audit: AuditReport }) {
  const lostTotal = (audit.lost_orig?.length || 0) + (audit.lost_plm?.length || 0)
  const tc = audit.type_counts || {}
  const nSame = tc['same'] || 0
  const nChanged = tc['changed'] || 0
  const nPlm = tc['only_plm'] || 0
  const nOrig = tc['only_orig'] || 0
  const accent = auditColor(audit.status)
  const row: React.CSSProperties = { fontSize: 13, color: '#333', margin: '2px 0', fontFamily: 'monospace' }
  const mark = (ok: boolean) => (
    <span style={{ marginLeft: 6, color: ok ? '#52c41a' : '#ff4d4f', fontWeight: 700 }}>{ok ? '✓' : '✗'}</span>
  )
  const abnormal = lostTotal > 0 || (audit.missing_in_output?.length || 0) > 0
  return (
    <div style={{ maxWidth: 560 }}>
      <div style={{ marginBottom: 8 }}>
        <span style={{ fontWeight: 600, fontSize: 13, marginRight: 8 }}>审计面板</span>
        <span style={{ padding: '2px 10px', borderRadius: 4, background: accent, color: '#fff', fontWeight: 600, fontSize: 12 }}>
          {audit.status === 'ok' ? '通过' : audit.status === 'warning' ? '提醒' : '异常'}
        </span>
        {audit.repaired && <span style={{ marginLeft: 8, fontSize: 12, color: '#888' }}>丢失行已补录到附录</span>}
      </div>

      <div style={row}>A旧 {audit.input_orig_rows} ＝ 同{nSame} ＋ 异{nChanged} ＋ A独{nOrig}{mark(audit.a_conserved)}</div>
      <div style={row}>B新 {audit.input_plm_rows} ＝ 同{nSame} ＋ 异{nChanged} ＋ B独{nPlm}{mark(audit.b_conserved)}</div>
      <div style={row}>输出 {audit.output_rows}／应{audit.kept_count}{mark(audit.kept_count === audit.output_rows)}<span style={{ color: '#aaa' }}> （同/异各合一行）</span></div>

      {abnormal && (
        <div style={{ fontSize: 12, color: '#ff4d4f', marginTop: 6 }}>
          {lostTotal > 0 && <span style={{ marginRight: 12 }}>引擎丢 {lostTotal}</span>}
          {(audit.missing_in_output?.length || 0) > 0 && <span>输出缺 {audit.missing_in_output.length}</span>}
        </div>
      )}

      {audit.status !== 'ok' && (
        <div style={{ fontSize: 12, color: '#666', marginTop: 6, lineHeight: 1.5 }}>
          {audit.recommendations?.map((r, i) => <div key={i}>· {r}</div>)}
        </div>
      )}
    </div>
  )
}
