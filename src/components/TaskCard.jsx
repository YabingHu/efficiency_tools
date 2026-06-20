import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

function isOverdue(dueDate) {
  if (!dueDate) return false
  return new Date(dueDate) < new Date(new Date().toDateString())
}

export default function TaskCard({ task, onEdit, onDelete, onToggle, isDragging }) {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({
    id: task.id,
    data: { task, quadrant: task.quadrant },
  })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`task-card${task.done ? ' done' : ''}`}
      {...attributes}
    >
      <div className="task-top">
        <input
          type="checkbox"
          className="task-checkbox"
          checked={task.done}
          onChange={onToggle}
          onPointerDown={e => e.stopPropagation()}
        />
        <span className="task-title" {...listeners}>{task.title}</span>
        <div className="task-actions">
          <button className="task-btn" onClick={onEdit} onPointerDown={e => e.stopPropagation()} title="编辑">✏️</button>
          <button className="task-btn delete" onClick={onDelete} onPointerDown={e => e.stopPropagation()} title="删除">🗑️</button>
        </div>
      </div>
      {task.desc && <div className="task-desc">{task.desc}</div>}
      {task.dueDate && (
        <div className={`task-due${isOverdue(task.dueDate) && !task.done ? ' overdue' : ''}`}>
          📅 {task.dueDate}{isOverdue(task.dueDate) && !task.done ? ' · 逾期' : ''}
        </div>
      )}
    </div>
  )
}
