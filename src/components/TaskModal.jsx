import { useState } from 'react'

export default function TaskModal({ task, defaultQuadrant, quadrants, onSave, onClose }) {
  const [title, setTitle] = useState(task?.title || '')
  const [desc, setDesc] = useState(task?.desc || '')
  const [dueDate, setDueDate] = useState(task?.dueDate || '')
  const [quadrant, setQuadrant] = useState(task?.quadrant || defaultQuadrant)

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!title.trim()) return
    onSave({ title: title.trim(), desc: desc.trim(), dueDate, quadrant })
  }

  return (
    <div className="modal-mask" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <h2>{task ? '编辑任务' : '新建任务'}</h2>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>任务标题 *</label>
            <input
              autoFocus
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder="输入任务内容..."
              maxLength={100}
            />
          </div>
          <div className="form-group">
            <label>描述（可选）</label>
            <textarea
              value={desc}
              onChange={e => setDesc(e.target.value)}
              placeholder="添加更多说明..."
              maxLength={300}
            />
          </div>
          <div className="form-group">
            <label>所属象限</label>
            <select value={quadrant} onChange={e => setQuadrant(e.target.value)}>
              {quadrants.map(q => (
                <option key={q.id} value={q.id}>{q.label}</option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label>截止日期（可选）</label>
            <input
              type="date"
              value={dueDate}
              onChange={e => setDueDate(e.target.value)}
            />
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
