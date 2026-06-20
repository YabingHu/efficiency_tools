import { useState, useEffect } from 'react'

const STORAGE_KEY = 'daily-tasks'
const DATE_KEY = 'daily-tasks-date'

function todayStr() {
  return new Date().toISOString().slice(0, 10)
}

function load() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY)) || []
    const lastDate = localStorage.getItem(DATE_KEY)
    if (lastDate !== todayStr()) {
      // new day — reset all done flags
      const reset = saved.map(t => ({ ...t, done: false }))
      localStorage.setItem(STORAGE_KEY, JSON.stringify(reset))
      localStorage.setItem(DATE_KEY, todayStr())
      return reset
    }
    return saved
  } catch {
    return []
  }
}

function msUntilMidnight() {
  const now = new Date()
  const midnight = new Date(now)
  midnight.setHours(24, 0, 0, 0)
  return midnight - now
}

export function useDailyTasks() {
  const [tasks, setTasks] = useState(load)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(tasks))
    localStorage.setItem(DATE_KEY, todayStr())
  }, [tasks])

  useEffect(() => {
    const reset = () => {
      setTasks(prev => prev.map(t => ({ ...t, done: false })))
      localStorage.setItem(DATE_KEY, todayStr())
    }
    const timer = setTimeout(reset, msUntilMidnight())
    return () => clearTimeout(timer)
  }, [])

  const addTask = (title) => {
    setTasks(prev => [...prev, { id: Date.now().toString(), title: title.trim(), done: false }])
  }

  const toggleTask = (id) => {
    setTasks(prev => prev.map(t => t.id === id ? { ...t, done: !t.done } : t))
  }

  const deleteTask = (id) => {
    setTasks(prev => prev.filter(t => t.id !== id))
  }

  const reorderTask = (fromIndex, toIndex) => {
    setTasks(prev => {
      const next = [...prev]
      const [moved] = next.splice(fromIndex, 1)
      next.splice(toIndex, 0, moved)
      return next
    })
  }

  return { tasks, addTask, toggleTask, deleteTask, reorderTask }
}
