import { useState } from 'react'
import { useTeam } from '../hooks/useTeam'
import TeamTaskModal from './TeamTaskModal'

const STATUS_META = {
  todo:        { label: '待开始',   color: '#8A7A6B', bg: '#F0EBE4' },
  in_progress: { label: '进行中',   color: '#B07D00', bg: '#F8F2E0' },
  waiting:     { label: '等待回复', color: '#C8643C', bg: '#F5E9E3' },
  done:        { label: '已完成',   color: '#4A8C6A', bg: '#EAF3ED' },
}

const STATUS_ORDER = ['todo', 'in_progress', 'waiting', 'done']

function cycleStatus(current) {
  const idx = STATUS_ORDER.indexOf(current)
  return STATUS_ORDER[(idx + 1) % STATUS_ORDER.length]
}

function Avatar({ member, size = 36 }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%',
      background: member.color, color: '#fff',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: size * 0.38, fontWeight: 700, flexShrink: 0,
    }}>
      {member.name.slice(0, 2)}
    </div>
  )
}

function MilestoneSection({ task, onAdd, onToggle, onDelete }) {
  const [input, setInput] = useState('')
  const milestones = task.milestones || []
  const done = milestones.filter(m => m.done).length

  const handleAdd = (e) => {
    e.preventDefault()
    if (!input.trim()) return
    onAdd(task.id, input)
    setInput('')
  }

  return (
    <div className="ms-section">
      {milestones.length > 0 && (
        <>
          <div className="ms-progress-wrap">
            <div className="ms-progress-bar" style={{ width: `${Math.round(done / milestones.length * 100)}%` }} />
          </div>
          <div className="ms-count">{done} / {milestones.length} 完成</div>
          <div className="ms-checklist">
            {milestones.map(m => (
              <div key={m.id} className={`ms-check-item${m.done ? ' done' : ''}`}>
                <input
                  type="checkbox"
                  checked={m.done}
                  onChange={() => onToggle(task.id, m.id)}
                  className="task-checkbox"
                />
                <span className="ms-check-title">{m.title}</span>
                <button className="task-btn delete ms-del" onClick={() => onDelete(task.id, m.id)}>✕</button>
              </div>
            ))}
          </div>
        </>
      )}
      <form className="ms-add-row" onSubmit={handleAdd}>
        <input
          className="ms-add-input"
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="添加 milestone..."
          maxLength={80}
        />
        <button type="submit" className="ms-add-btn">＋</button>
      </form>
    </div>
  )
}

function TaskRow({ task, onEdit, onDelete, onStatusChange, onAddMilestone, onToggleMilestone, onDeleteMilestone }) {
  const [expanded, setExpanded] = useState(false)
  const s = STATUS_META[task.status]
  const milestones = task.milestones || []
  const overdue = task.dueDate && task.status !== 'done' && new Date(task.dueDate) < new Date(new Date().toDateString())
  const msDone = milestones.filter(m => m.done).length

  return (
    <div className={`team-task-row${task.status === 'done' ? ' done' : ''}${expanded ? ' expanded' : ''}`}>
      <div className="team-task-main">
        <div className="team-task-left">
          <span className="team-task-type">{task.type === 'assigned' ? '📋' : '🔔'}</span>
          <div className="team-task-info">
            <span className="team-task-title">{task.title}</span>
            {task.notes && <span className="team-task-notes">{task.notes}</span>}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              {task.dueDate && (
                <span className={`team-task-due${overdue ? ' overdue' : ''}`}>
                  📅 {task.dueDate}{overdue ? ' · 已逾期' : ''}
                </span>
              )}
              {task.type === 'assigned' && milestones.length > 0 && (
                <span className="ms-badge" onClick={() => setExpanded(e => !e)}>
                  ◎ {msDone}/{milestones.length} milestones
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="team-task-right">
          {task.type === 'assigned' && (
            <button
              className="task-btn"
              onClick={() => setExpanded(e => !e)}
              title={expanded ? '折叠' : '展开 milestones'}
              style={{ color: expanded ? 'var(--accent)' : 'var(--text-3)' }}
            >
              {expanded ? '▲' : '▼'}
            </button>
          )}
          <button
            className="status-pill"
            style={{ color: s.color, background: s.bg }}
            onClick={() => onStatusChange(task.id, cycleStatus(task.status))}
            title="点击切换状态"
          >
            {s.label}
          </button>
          <button className="task-btn" onClick={() => onEdit(task)} title="编辑">✏️</button>
          <button className="task-btn delete" onClick={() => onDelete(task.id)} title="删除">🗑️</button>
        </div>
      </div>

      {expanded && task.type === 'assigned' && (
        <MilestoneSection
          task={task}
          onAdd={onAddMilestone}
          onToggle={onToggleMilestone}
          onDelete={onDeleteMilestone}
        />
      )}
    </div>
  )
}

function MemberCard({ member, tasks, onAddTask, onEdit, onDelete, onStatusChange, onDeleteMember, onAddMilestone, onToggleMilestone, onDeleteMilestone }) {
  const [collapsed, setCollapsed] = useState(false)
  const active = tasks.filter(t => t.status !== 'done').length
  const done = tasks.filter(t => t.status === 'done').length

  return (
    <div className="member-card">
      <div className="member-card-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Avatar member={member} />
          <div>
            <div className="member-name">{member.name}</div>
            <div className="member-stats">
              {active > 0 && <span style={{ color: '#f77f00' }}>{active} 进行中</span>}
              {active > 0 && done > 0 && <span style={{ color: '#ccc' }}> · </span>}
              {done > 0 && <span style={{ color: '#2ec4b6' }}>{done} 已完成</span>}
              {tasks.length === 0 && <span style={{ color: '#ccc' }}>暂无任务</span>}
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <button className="task-btn" onClick={() => onAddTask(member.id)} title="添加任务" style={{ fontSize: 16 }}>＋</button>
          <button className="task-btn" onClick={() => setCollapsed(c => !c)}>{collapsed ? '▶' : '▼'}</button>
          <button className="task-btn delete" onClick={() => {
            if (window.confirm(`确定删除成员「${member.name}」及其所有任务？`)) onDeleteMember(member.id)
          }} title="删除成员">🗑️</button>
        </div>
      </div>

      {!collapsed && (
        <div className="member-task-list">
          {tasks.length === 0 && <div className="team-empty">暂无任务，点击 ＋ 添加</div>}
          {tasks.map(task => (
            <TaskRow
              key={task.id}
              task={task}
              onEdit={onEdit}
              onDelete={onDelete}
              onStatusChange={onStatusChange}
              onAddMilestone={onAddMilestone}
              onToggleMilestone={onToggleMilestone}
              onDeleteMilestone={onDeleteMilestone}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export default function TeamView() {
  const { members, tasks, addMember, deleteMember, addTask, updateTask, deleteTask, addMilestone, toggleMilestone, deleteMilestone } = useTeam()
  const [modal, setModal] = useState(null)
  const [newMemberInput, setNewMemberInput] = useState('')
  const [showAddMember, setShowAddMember] = useState(false)

  const handleAddMember = (e) => {
    e.preventDefault()
    if (!newMemberInput.trim()) return
    addMember(newMemberInput)
    setNewMemberInput('')
    setShowAddMember(false)
  }

  const handleSaveTask = (data) => {
    if (modal.task) updateTask(modal.task.id, data)
    else addTask(data)
    setModal(null)
  }

  return (
    <div className="team-container">
      <div className="team-top-bar">
        <h2 className="team-heading">团队任务</h2>
        <button className="add-btn" onClick={() => setShowAddMember(s => !s)}>
          {showAddMember ? '取消' : '+ 添加成员'}
        </button>
      </div>

      {showAddMember && (
        <form className="add-member-form" onSubmit={handleAddMember}>
          <input
            autoFocus
            className="daily-add-input"
            value={newMemberInput}
            onChange={e => setNewMemberInput(e.target.value)}
            placeholder="成员姓名..."
            maxLength={20}
          />
          <button type="submit" className="daily-add-btn">确认添加</button>
        </form>
      )}

      {members.length === 0 && (
        <div className="team-empty-page">
          <div style={{ fontSize: 40, marginBottom: 12 }}>👥</div>
          <div>还没有团队成员，点击「添加成员」开始</div>
        </div>
      )}

      <div className="member-list">
        {members.map(member => (
          <MemberCard
            key={member.id}
            member={member}
            tasks={tasks.filter(t => t.memberId === member.id)}
            onAddTask={(mid) => setModal({ defaultMemberId: mid })}
            onEdit={(task) => setModal({ task })}
            onDelete={deleteTask}
            onStatusChange={(id, status) => updateTask(id, { status })}
            onDeleteMember={deleteMember}
            onAddMilestone={addMilestone}
            onToggleMilestone={toggleMilestone}
            onDeleteMilestone={deleteMilestone}
          />
        ))}
      </div>

      {modal && members.length > 0 && (
        <TeamTaskModal
          task={modal.task}
          members={members}
          defaultMemberId={modal.defaultMemberId}
          onSave={handleSaveTask}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  )
}
