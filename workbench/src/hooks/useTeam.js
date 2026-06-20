import { useState, useEffect } from 'react'

const MEMBERS_KEY = 'team-members'
const TASKS_KEY = 'team-tasks'

const MEMBER_COLORS = ['#4361ee', '#ef233c', '#f77f00', '#2ec4b6', '#9b5de5', '#0077b6']

function loadMembers() {
  try { return JSON.parse(localStorage.getItem(MEMBERS_KEY)) || [] } catch { return [] }
}

function loadTasks() {
  try { return JSON.parse(localStorage.getItem(TASKS_KEY)) || [] } catch { return [] }
}

export function useTeam() {
  const [members, setMembers] = useState(loadMembers)
  const [tasks, setTasks] = useState(loadTasks)

  useEffect(() => { localStorage.setItem(MEMBERS_KEY, JSON.stringify(members)) }, [members])
  useEffect(() => { localStorage.setItem(TASKS_KEY, JSON.stringify(tasks)) }, [tasks])

  const addMember = (name) => {
    const color = MEMBER_COLORS[members.length % MEMBER_COLORS.length]
    setMembers(prev => [...prev, { id: Date.now().toString(), name: name.trim(), color }])
  }

  const deleteMember = (id) => {
    setMembers(prev => prev.filter(m => m.id !== id))
    setTasks(prev => prev.filter(t => t.memberId !== id))
  }

  const addTask = (task) => {
    setTasks(prev => [...prev, { id: Date.now().toString(), status: 'todo', createdAt: new Date().toISOString(), ...task }])
  }

  const updateTask = (id, data) => {
    setTasks(prev => prev.map(t => t.id === id ? { ...t, ...data } : t))
  }

  const deleteTask = (id) => {
    setTasks(prev => prev.filter(t => t.id !== id))
  }

  const addMilestone = (taskId, title) => {
    setTasks(prev => prev.map(t => t.id === taskId
      ? { ...t, milestones: [...(t.milestones || []), { id: Date.now().toString(), title: title.trim(), done: false }] }
      : t
    ))
  }

  const toggleMilestone = (taskId, milestoneId) => {
    setTasks(prev => prev.map(t => t.id === taskId
      ? { ...t, milestones: t.milestones.map(m => m.id === milestoneId ? { ...m, done: !m.done } : m) }
      : t
    ))
  }

  const deleteMilestone = (taskId, milestoneId) => {
    setTasks(prev => prev.map(t => t.id === taskId
      ? { ...t, milestones: t.milestones.filter(m => m.id !== milestoneId) }
      : t
    ))
  }

  return { members, tasks, addMember, deleteMember, addTask, updateTask, deleteTask, addMilestone, toggleMilestone, deleteMilestone }
}
