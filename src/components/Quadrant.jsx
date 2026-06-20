import { useDroppable } from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { useState } from 'react'
import TaskCard from './TaskCard'

export default function Quadrant({ quadrant, tasks, onAdd, onEdit, onDelete, onToggle, activeId, hideCompleted }) {
  const { setNodeRef, isOver } = useDroppable({
    id: quadrant.id,
    data: { quadrant: quadrant.id },
  })

  const activeTasks = tasks.filter(t => !t.done)
  const doneTasks = tasks.filter(t => t.done)
  const visibleTasks = hideCompleted ? activeTasks : tasks

  return (
    <div
      ref={setNodeRef}
      className={`quadrant ${quadrant.className}${isOver ? ' drag-over' : ''}`}
    >
      <div className="quadrant-header">
        <span className="quadrant-badge">{quadrant.label}</span>
        <span className="quadrant-sub">{quadrant.sub}</span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {doneTasks.length > 0 && (
            <span className="quadrant-done-count">✓ {doneTasks.length}</span>
          )}
          {activeTasks.length > 0 && (
            <span className="quadrant-count">{activeTasks.length}</span>
          )}
        </div>
      </div>

      <SortableContext items={visibleTasks.map(t => t.id)} strategy={verticalListSortingStrategy}>
        <div className="task-list">
          {visibleTasks.length === 0 && (
            <div className="empty-hint">
              {hideCompleted && doneTasks.length > 0
                ? `${doneTasks.length} 项已完成`
                : '拖入任务\n或点击下方添加'}
            </div>
          )}
          {visibleTasks.map(task => (
            <TaskCard
              key={task.id}
              task={task}
              onEdit={() => onEdit(task)}
              onDelete={() => onDelete(task.id)}
              onToggle={() => onToggle(task.id)}
              isDragging={activeId === task.id}
            />
          ))}
        </div>
      </SortableContext>

      <button className="quadrant-add-btn" onClick={onAdd}>+ 添加任务</button>
    </div>
  )
}
