import assert from 'node:assert/strict'
import test from 'node:test'
import { updateTaskMarkersInTree } from '../src/lib/task-marker-updates.ts'

test('a live task marker update reaches every occurrence without editing another owner or source Note', () => {
  const untouched = { task_id: 'second-owner', one_h_marker: 'KA' }
  const before = {
    departments: [{ days: [{ am_projects: [{ tasks: [{ task_id: 'first-owner', one_h_marker: null }, untouched] }],
      pm_fast_tasks: [{ task_id: 'first-owner', one_h_marker: null }] }] }],
    assigneeStates: { first: { taskId: 'first-owner', oneHMarker: null }, second: { taskId: 'second-owner', oneHMarker: 'KA' } },
    sourceNote: { id: 'source-note', one_h_marker: 'QUESTION' },
  }
  const update = { taskId: 'first-owner', marker: 'CLIENT_URGENT,M3', markerByGa: true, markerComment: 'Follow up' }
  const after = updateTaskMarkersInTree(before, update)
  const day = after.departments[0].days[0]
  assert.equal(day.am_projects[0].tasks[0].one_h_marker, 'CLIENT_URGENT,M3')
  assert.equal(day.pm_fast_tasks[0].one_h_marker_by_ga, true)
  assert.equal(day.am_projects[0].tasks[1], untouched)
  assert.equal(after.assigneeStates.first.oneHMarkerComment, 'Follow up')
  assert.equal(after.assigneeStates.second, before.assigneeStates.second)
  assert.equal(after.sourceNote, before.sourceNote)
  assert.equal(before.departments[0].days[0].am_projects[0].tasks[0].one_h_marker, null)
  assert.equal(updateTaskMarkersInTree(before, { ...update, taskId: 'unrelated' }), before)
})

test('clearing keeps the authoritative comment and does not change the independent copy', () => {
  const tasks = [{ id: 'first', one_h_marker: 'M3' }, { id: 'second', one_h_marker: 'KA' }]
  const next = updateTaskMarkersInTree(tasks, { taskId: 'first', marker: null, markerByGa: false, markerComment: 'Comment without a symbol' })
  assert.equal(next[0].one_h_marker, null)
  assert.equal(next[0].one_h_marker_comment, 'Comment without a symbol')
  assert.equal(next[1], tasks[1])
})
