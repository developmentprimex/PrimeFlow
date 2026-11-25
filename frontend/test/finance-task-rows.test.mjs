import assert from 'node:assert/strict'
import test from 'node:test'
import { financeTaskAlignment, financeTaskMatchesDates, financeTaskMatchesPerson } from '../src/lib/finance-task-rows.ts'

test('Finance includes tasks active on any day of the selected interval', () => {
  const task = { startDateIso: '2026-11-23', dueDateIso: '2026-11-27' }
  assert.equal(financeTaskMatchesDates(task, '2026-11-25', '2026-11-25'), true)
  assert.equal(financeTaskMatchesDates(task, '2026-11-25', ''), true)
  assert.equal(financeTaskMatchesDates(task, '2026-11-29', '2026-11-27'), true)
  assert.equal(financeTaskMatchesDates(task, '2026-11-28', '2026-11-28'), false)
  assert.equal(financeTaskMatchesDates({ startDateIso: '', dueDateIso: '2026-11-25' }, '', '2026-11-25'), true)
})

test('Finance keeps BZ participants visible alongside all assigned people', () => {
  const labels = new Map([['finance', 'Haxhere Spahiu'], ['other', 'Gane Arifaj']])
  const alignment = financeTaskAlignment(['other'], { requires_alignment: true, alignment_user_ids: ['finance', 'other'], alignment_time: '11:50:00' }, labels)
  assert.deepEqual(alignment, { userIds: ['other', 'finance'], withLabel: 'Gane Arifaj, Haxhere Spahiu', time: '11:50' })
  assert.equal(financeTaskMatchesPerson({ assigneeIds: ['other'], alignment }, 'finance'), true)
  assert.equal(financeTaskMatchesPerson({ assigneeIds: ['other'], alignment }, 'other'), true)
  assert.equal(financeTaskMatchesPerson({ assigneeIds: ['other'], alignment }, 'unrelated'), false)
  assert.equal(financeTaskAlignment([], undefined, labels).withLabel, '')
})
