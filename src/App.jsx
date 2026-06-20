import { useState, useCallback, useEffect, useRef } from 'react'
import {
  DndContext, DragOverlay, PointerSensor,
  useSensor, useSensors, closestCenter,
} from '@dnd-kit/core'
import Quadrant from './components/Quadrant'
import TaskModal from './components/TaskModal'
import DailyTasks from './components/DailyTasks'
import TeamView from './components/TeamView'
import { useTasks } from './hooks/useTasks'
import './App.css'

const QUADRANTS = [
  { id: 'q1', label: '既紧急又重要', sub: '立即处理', className: 'quadrant-q1' },
  { id: 'q2', label: '重要但不紧急', sub: '计划安排', className: 'quadrant-q2' },
  { id: 'q3', label: '紧急但不重要', sub: '委托他人', className: 'quadrant-q3' },
  { id: 'q4', label: '既不紧急也不重要', sub: '尽量减少', className: 'quadrant-q4' },
]

// ── Export / Import ──────────────────────────────────────
function exportData() {
  const data = {
    tasks:       localStorage.getItem('quadrant-tasks'),
    dailyTasks:  localStorage.getItem('daily-tasks'),
    dailyDate:   localStorage.getItem('daily-tasks-date'),
    teamMembers: localStorage.getItem('team-members'),
    teamTasks:   localStorage.getItem('team-tasks'),
    history:     localStorage.getItem('quadrant-history'),
  }
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `quadrant-backup-${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(a.href)
}

function importData(file, onDone) {
  const reader = new FileReader()
  reader.onload = (e) => {
    try {
      const data = JSON.parse(e.target.result)
      if (data.tasks)       localStorage.setItem('quadrant-tasks', data.tasks)
      if (data.dailyTasks)  localStorage.setItem('daily-tasks', data.dailyTasks)
      if (data.dailyDate)   localStorage.setItem('daily-tasks-date', data.dailyDate)
      if (data.teamMembers) localStorage.setItem('team-members', data.teamMembers)
      if (data.teamTasks)   localStorage.setItem('team-tasks', data.teamTasks)
      if (data.history)     localStorage.setItem('quadrant-history', data.history)
      onDone()
    } catch {
      alert('文件格式错误，请选择正确的备份文件')
    }
  }
  reader.readAsText(file)
}

// ── Notifications ────────────────────────────────────────
function requestNotifications(tasks) {
  if (!('Notification' in window)) return
  const ask = () => {
    const today = new Date().toISOString().slice(0, 10)
    const urgent = tasks.filter(t => !t.done && t.dueDate && t.dueDate <= today)
    if (urgent.length === 0) return
    new Notification('四象限任务提醒', {
      body: `你有 ${urgent.length} 个任务今日到期或已逾期`,
      icon: '/favicon.svg',
    })
  }
  if (Notification.permission === 'granted') { ask() }
  else if (Notification.permission !== 'denied') {
    Notification.requestPermission().then(p => { if (p === 'granted') ask() })
  }
}

export default function App() {
  const { tasks, todayCompleted, addTask, updateTask, deleteTask, moveTask, reorderTasks, importTasks } = useTasks()
  const [tab, setTab]               = useState('quadrant')
  const [modalOpen, setModalOpen]   = useState(false)
  const [editingTask, setEditingTask] = useState(null)
  const [defaultQuadrant, setDefaultQuadrant] = useState('q1')
  const [activeId, setActiveId]     = useState(null)
  const [hideCompleted, setHideCompleted] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const [menuOpen, setMenuOpen]     = useState(false)
  const searchRef = useRef(null)
  const menuRef   = useRef(null)
  const fileRef   = useRef(null)

  // Notifications on mount
  useEffect(() => { requestNotifications(tasks) }, []) // eslint-disable-line

  // Close dropdowns on outside click
  useEffect(() => {
    const handler = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false)
      if (searchRef.current && !searchRef.current.contains(e.target)) {
        if (!e.target.closest('.search-results')) setSearchOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } })
  )

  const openAdd = useCallback((quadrantId) => {
    setEditingTask(null); setDefaultQuadrant(quadrantId); setModalOpen(true)
  }, [])

  const openEdit = useCallback((task) => {
    setEditingTask(task); setModalOpen(true)
  }, [])

  const handleSave = useCallback((data) => {
    if (editingTask) updateTask(editingTask.id, data)
    else addTask({ ...data, quadrant: data.quadrant || defaultQuadrant })
    setModalOpen(false)
  }, [editingTask, defaultQuadrant, addTask, updateTask])

  const handleDragStart = ({ active }) => setActiveId(active.id)

  const handleDragEnd = ({ active, over }) => {
    setActiveId(null)
    if (!over || active.id === over.id) return
    const activeTask = tasks.find(t => t.id === active.id)
    const overTask   = tasks.find(t => t.id === over.id)
    if (overTask) {
      if (activeTask.quadrant === overTask.quadrant) reorderTasks(active.id, over.id)
      else moveTask(active.id, overTask.quadrant)
    } else {
      const overQuadrant = over.data?.current?.quadrant ?? over.id
      if (overQuadrant && overQuadrant !== activeTask.quadrant) moveTask(active.id, overQuadrant)
    }
  }

  // Search
  const allSearchable = QUADRANTS.flatMap(q =>
    tasks.filter(t => t.quadrant === q.id).map(t => ({ ...t, quadrantLabel: q.label, quadrantClass: q.className }))
  )
  const searchResults = searchQuery.trim()
    ? allSearchable.filter(t => t.title.toLowerCase().includes(searchQuery.toLowerCase()) || t.desc?.toLowerCase().includes(searchQuery.toLowerCase()))
    : []

  const activeTask = tasks.find(t => t.id === activeId)

  return (
    <div className="app" onClick={() => setMenuOpen(false)}>
      <header className="header">
        {/* Logo */}
        <h1>
          <div className="logo-mark"><span /><span /><span /><span /></div>
          工作台
        </h1>

        {/* Tabs */}
        <div className="tabs">
          <button className={`tab-btn${tab === 'quadrant' ? ' active' : ''}`} onClick={() => setTab('quadrant')}>四象限</button>
          <button className={`tab-btn${tab === 'daily'    ? ' active' : ''}`} onClick={() => setTab('daily')}>每日任务</button>
          <button className={`tab-btn${tab === 'team'     ? ' active' : ''}`} onClick={() => setTab('team')}>团队任务</button>
        </div>

        {/* Right controls */}
        <div className="header-right">
          {todayCompleted > 0 && (
            <span className="today-badge">✓ 今日 {todayCompleted} 项</span>
          )}

          {/* Search */}
          <div className="search-wrap" ref={searchRef}>
            <button
              className="icon-btn"
              title="搜索"
              onClick={(e) => { e.stopPropagation(); setSearchOpen(s => !s); if (!searchOpen) setTimeout(() => searchRef.current?.querySelector('input')?.focus(), 50) }}
            >
              🔍
            </button>
            {searchOpen && (
              <div className="search-dropdown" onClick={e => e.stopPropagation()}>
                <input
                  className="search-input"
                  placeholder="搜索任务..."
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  autoFocus
                />
                {searchResults.length > 0 && (
                  <div className="search-results">
                    {searchResults.map(t => (
                      <div
                        key={t.id}
                        className="search-result-item"
                        onClick={() => { openEdit(t); setSearchOpen(false); setSearchQuery(''); setTab('quadrant') }}
                      >
                        <span className={`search-result-badge ${t.quadrantClass}`}>{t.quadrantLabel}</span>
                        <span className={`search-result-title${t.done ? ' done' : ''}`}>{t.title}</span>
                      </div>
                    ))}
                  </div>
                )}
                {searchQuery && searchResults.length === 0 && (
                  <div className="search-empty">没有找到匹配的任务</div>
                )}
              </div>
            )}
          </div>

          {/* Hide completed toggle — only on quadrant tab */}
          {tab === 'quadrant' && (
            <button
              className={`icon-btn${hideCompleted ? ' active' : ''}`}
              title={hideCompleted ? '显示已完成' : '隐藏已完成'}
              onClick={(e) => { e.stopPropagation(); setHideCompleted(h => !h) }}
            >
              {hideCompleted ? '👁' : '🙈'}
            </button>
          )}

          {/* Export / Import menu */}
          <div className="menu-wrap" ref={menuRef} onClick={e => e.stopPropagation()}>
            <button className="icon-btn" title="更多" onClick={() => setMenuOpen(m => !m)}>⋯</button>
            {menuOpen && (
              <div className="dropdown-menu">
                <button className="dropdown-item" onClick={() => { exportData(); setMenuOpen(false) }}>⬇ 导出数据</button>
                <button className="dropdown-item" onClick={() => fileRef.current?.click()}>⬆ 导入数据</button>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".json"
                  style={{ display: 'none' }}
                  onChange={e => {
                    const file = e.target.files[0]
                    if (!file) return
                    if (window.confirm('导入将覆盖当前所有数据，确认继续？')) {
                      importData(file, () => window.location.reload())
                    }
                    e.target.value = ''
                  }}
                />
              </div>
            )}
          </div>

          {tab === 'quadrant' && (
            <button className="add-btn" onClick={() => openAdd('q1')}>+ 新建任务</button>
          )}
        </div>
      </header>

      {tab === 'quadrant' && (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
        >
          <main className="board-shell">
            <div className="axis-top">
              <div />
              <div className="axis-top-label">紧急</div>
              <div className="axis-top-label">不紧急</div>
            </div>
            <div className="board-body">
              <div className="axis-left">
                <div className="axis-left-label">重要</div>
                <div className="axis-left-label">不重要</div>
              </div>
              <div className="board">
                {QUADRANTS.map(q => (
                  <Quadrant
                    key={q.id}
                    quadrant={q}
                    tasks={tasks.filter(t => t.quadrant === q.id)}
                    onAdd={() => openAdd(q.id)}
                    onEdit={openEdit}
                    onDelete={deleteTask}
                    onToggle={(id) => {
                      const t = tasks.find(t => t.id === id)
                      if (t) updateTask(id, { done: !t.done })
                    }}
                    activeId={activeId}
                    hideCompleted={hideCompleted}
                  />
                ))}
              </div>
            </div>
          </main>

          <DragOverlay dropAnimation={null}>
            {activeTask && (
              <div className="task-card" style={{ opacity: 0.9, boxShadow: '0 8px 24px rgba(60,40,20,0.18)', transform: 'rotate(1.5deg)' }}>
                <div className="task-title">{activeTask.title}</div>
              </div>
            )}
          </DragOverlay>
        </DndContext>
      )}

      {tab === 'daily' && <DailyTasks />}
      {tab === 'team'  && <TeamView />}

      {modalOpen && (
        <TaskModal
          task={editingTask}
          defaultQuadrant={defaultQuadrant}
          quadrants={QUADRANTS}
          onSave={handleSave}
          onClose={() => setModalOpen(false)}
        />
      )}
    </div>
  )
}
