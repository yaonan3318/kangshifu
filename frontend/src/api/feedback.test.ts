import { afterEach, describe, expect, it, vi } from 'vitest'

import { assignFeedbackCase, submitFeedback, updateFeedbackCase, verifyFeedbackCase } from './feedback'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('feedback API', () => {
  it('submits REPORT as feedback_type while keeping the rating', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ ok: true, id: 'f1' }), { status: 201, headers: { 'Content-Type': 'application/json' } },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await submitFeedback({ messageId: 'm1', rating: 'DOWN', feedbackType: 'REPORT', reasons: ['举报敏感或错误内容'] })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/feedback')
    expect(init.method).toBe('POST')
    const body = JSON.parse(init.body as string)
    expect(body.feedback_type).toBe('REPORT')
    expect(body.rating).toBe('DOWN')
  })

  it('uses PATCH for case status and POST for assignment and verification', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(
      JSON.stringify({ id: 'c1' }), { status: 200, headers: { 'Content-Type': 'application/json' } },
    )))
    vi.stubGlobal('fetch', fetchMock)

    await updateFeedbackCase('c1', { status: 'PROCESSING' })
    await assignFeedbackCase('c1', { assignee_id: null, priority: 'HIGH' })
    await verifyFeedbackCase('c1', '已修复')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/admin/feedback/cases/c1')
    expect(fetchMock.mock.calls[0][1].method).toBe('PATCH')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/admin/feedback/cases/c1/assign')
    expect(fetchMock.mock.calls[2][0]).toBe('/api/admin/feedback/cases/c1/verify')
  })
})
