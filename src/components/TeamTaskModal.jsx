import { useState } from 'react'

const STATUS_OPTIONS = [
  { value: 'todo',        label: '待开始' },
  { value: 'in_progress', label: '进行中' },
  { value: 'waiting',     label: '等待回复' },
  { value: 'done',        label: '已完成' },
]

export default function TeamTaskModal({ task, members, defaultMemberId, onSave, onClose }) {
  const [title, setTitle]       = useState(task?.title || '')
  const [memberId, setMemberId] = useState(task?.memberId || defaultMemberId || members[0]?.id || '')
  const [type, setType]         = useState(task?.type || 'assigned')
  const [status, setStatus]     = useState(task?.status || 'todo')
  const [dueDate, setDueDate]   = useState(task?.dueDate || '')
  const [notes, setNotes]       = useState(task?.notes || '')
  const [milestones, setMilestones] = useState(task?.milestones || [])
  const [msInput, setMsInput]   = useState('')

  const addMilestone = () => {
    if (!msInput.trim()) return
    setMilestones(prev => [...prev, { id: Date.now().toString(), title: msInput.trim(), done: false }])
    setMsInput('')
  }

  const deleteMilestone = (id) => setMilestones(prev => prev.filter(m => m.id !== id))

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!title.trim() || !memberId) return
    onSave({ title: title.trim(), memberId, type, status, dueDate, notes: notes.trim(), milestones: type === 'assigned' ? milestones : [] })
  }

  return (
    <div className="modal-mask" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ width: 480 }}>
        <h2>{task ? '编辑任务' : '新建团队任务'}</h2>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>任务标题 *</label>
            <input autoFocus value={title} onChange={e => setTitle(e.target.value)} placeholder="任务内容..." maxLength={100} />
          </div>
          <div className="form-group">
            <label>负责人 *</label>
            <select value={memberId} onChange={e => setMemberId(e.target.value)}>
              {members.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          </div>
          <div className="form-group">
            <label>任务类型</label>
            <div style={{ display: 'flex', gap: 10 }}>
              {[
                { value: 'assigned', label: '📋 分配给他们' },
                { value: 'followup', label: '🔔 需要跟进' },
              ].map(opt => (
                <label key={opt.value} style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 14, padding: '8px 14px', border: `1.5px solid ${type === opt.value ? '#4361ee' : '#e0e0e0'}`, borderRadius: 8, background: type === opt.value ? '#eef1fd' : '#fff', fontWeight: type === opt.value ? 600 : 400, transition: 'all 0.15s' }}>
                  <input type="radio" name="type" value={opt.value} checked={type === opt.value} onChange={() => setType(opt.value)} style={{ display: 'none' }} />
                  {opt.label}
                </label>
              ))}
            </div>
          </div>

          {type === 'assigned' && (
            <div className="form-group">
              <label>Milestones</label>
              <div className="ms-list">
                {milestones.map(m => (
                  <div key={m.id} className="ms-item">
                    <span className="ms-dot" />
                    <span className="ms-item-title">{m.title}</span>
                    <button type="button" className="task-btn delete" onClick={() => deleteMilestone(m.id)}>✕</button>
                  </div>
                ))}
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                <input
                  className="daily-add-input"
                  style={{ fontSize: 13, padding: '7px 10px' }}
                  value={msInput}
                  onChange={e => setMsInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addMilestone())}
                  placeholder="添加 milestone..."
                  maxLength={80}
                />
                <button type="button" className="daily-add-btn" style={{ padding: '7px 14px', fontSize: 13 }} onClick={addMilestone}>添加</button>
              </div>
            </div>
          )}

          <div className="form-group">
            <label>状态</label>
            <select value={status} onChange={e => setStatus(e.target.value)}>
              {STATUS_OPTIONS.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
          <div className="form-group">
            <label>截止日期（可选）</label>
            <input type="date" value={dueDate} onChange={e => setDueDate(e.target.value)} />
          </div>
          <div className="form-group">
            <label>备注（可选）</label>
            <textarea value={notes} onChange={e => setNotes(e.target.value)} placeholder="补充说明..." maxLength={300} />
          </div>
          <div className="modal-actions">
            <button type="button" className="btn-cancel" onClick={onClose}>取消</button>
            <button type="submit" className="btn-save">保存</button>
          </div>
        </form>
      </div>
    </div>
  )
}
