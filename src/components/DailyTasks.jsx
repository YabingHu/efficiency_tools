import { useState, useRef } from 'react'
import { useDailyTasks } from '../hooks/useDailyTasks'

export default function DailyTasks() {
  const { tasks, addTask, toggleTask, deleteTask, reorderTask } = useDailyTasks()
  const [input, setInput] = useState('')
  const [draggingIndex, setDraggingIndex] = useState(null)
  const dragOverIndex = useRef(null)

  const done = tasks.filter(t => t.done).length
  const total = tasks.length
  const pct = total === 0 ? 0 : Math.round((done / total) * 100)

  const handleAdd = (e) => {
    e.preventDefault()
    if (!input.trim()) return
    addTask(input)
    setInput('')
  }

  const handleDragStart = (index) => setDraggingIndex(index)
  const handleDragEnter = (index) => { dragOverIndex.current = index }
  const handleDragEnd = () => {
    if (draggingIndex !== null && dragOverIndex.current !== null && draggingIndex !== dragOverIndex.current) {
      reorderTask(draggingIndex, dragOverIndex.current)
    }
    setDraggingIndex(null)
    dragOverIndex.current = null
  }

  return (
    <div className="daily-container">
      <div className="daily-header">
        <div className="daily-title-row">
          <h2 className="daily-title">每日任务</h2>
          <span className="daily-date">{new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' })}</span>
        </div>
        <div className="daily-progress-bar-wrap">
          <div className="daily-progress-bar" style={{ width: `${pct}%` }} />
        </div>
        <div className="daily-progress-text">
          {total === 0 ? '还没有任务' : `${done} / ${total} 已完成 · ${pct}%`}
        </div>
      </div>

      <div className="daily-list">
        {tasks.length === 0 && (
          <div className="daily-empty">添加你每天要做的事，每天凌晨自动重置</div>
        )}
        {tasks.map((task, index) => (
          <div
            key={task.id}
            className={`daily-item${task.done ? ' done' : ''}${draggingIndex === index ? ' dragging' : ''}`}
            draggable
            onDragStart={() => handleDragStart(index)}
            onDragEnter={() => handleDragEnter(index)}
            onDragEnd={handleDragEnd}
            onDragOver={e => e.preventDefault()}
          >
            <span className="drag-handle">⠿</span>
            <input
              type="checkbox"
              checked={task.done}
              onChange={() => toggleTask(task.id)}
              className="task-checkbox"
            />
            <span className="daily-item-title">{task.title}</span>
            <button
              className="task-btn delete"
              onClick={() => deleteTask(task.id)}
              title="删除"
            >🗑️</button>
          </div>
        ))}
      </div>

      <form className="daily-add-form" onSubmit={handleAdd}>
        <input
          className="daily-add-input"
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="添加每日任务..."
          maxLength={80}
        />
        <button type="submit" className="daily-add-btn">添加</button>
      </form>
    </div>
  )
}
