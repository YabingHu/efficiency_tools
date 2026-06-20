import { useState, useEffect } from 'react'
import { arrayMove } from '@dnd-kit/sortable'

const STORAGE_KEY = 'quadrant-tasks'
const HISTORY_KEY = 'quadrant-history'

function load() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY)) || [] } catch { return [] }
}

function todayStr() {
  return new Date().toISOString().slice(0, 10)
}

function bumpHistory() {
  try {
    const h = JSON.parse(localStorage.getItem(HISTORY_KEY) || '{}')
    h[todayStr()] = (h[todayStr()] || 0) + 1
    localStorage.setItem(HISTORY_KEY, JSON.stringify(h))
  } catch {}
}

function getTodayCompleted() {
  try {
    const h = JSON.parse(localStorage.getItem(HISTORY_KEY) || '{}')
    return h[todayStr()] || 0
  } catch { return 0 }
}

export function useTasks() {
  const [tasks, setTasks] = useState(load)
  const [todayCompleted, setTodayCompleted] = useState(getTodayCompleted)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(tasks))
  }, [tasks])

  const addTask = (data) => {
    setTasks(prev => [...prev, { id: Date.now().toString(), done: false, createdAt: new Date().toISOString(), ...data }])
  }

  const updateTask = (id, data) => {
    setTasks(prev => prev.map(t => {
      if (t.id !== id) return t
      const next = { ...t, ...data }
      if (!t.done && next.done) {
        bumpHistory()
        setTodayCompleted(getTodayCompleted)
      }
      return next
    }))
  }

  const deleteTask = (id) => {
    setTasks(prev => prev.filter(t => t.id !== id))
  }

  const moveTask = (id, quadrant) => {
    setTasks(prev => prev.map(t => t.id === id ? { ...t, quadrant } : t))
  }

  const reorderTasks = (activeId, overId) => {
    setTasks(prev => {
      const oldIndex = prev.findIndex(t => t.id === activeId)
      const newIndex = prev.findIndex(t => t.id === overId)
      return arrayMove(prev, oldIndex, newIndex)
    })
  }

  const importTasks = (imported) => {
    setTasks(imported)
  }

  return { tasks, todayCompleted, addTask, updateTask, deleteTask, moveTask, reorderTasks, importTasks }
}
