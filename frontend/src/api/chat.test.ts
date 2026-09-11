import { afterEach, describe, expect, it, vi } from 'vitest'

import { downloadAnswerPdf } from './chat'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('downloadAnswerPdf', () => {
  it('downloads the PDF generated for an assistant message', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(new Blob(['%PDF-test']), {
      status: 200,
      headers: { 'Content-Type': 'application/pdf' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await downloadAnswerPdf('message-1')

    expect(fetchMock).toHaveBeenCalledWith('/api/chat/messages/message-1/export.pdf')
    expect(result.type).toBe('application/pdf')
  })

  it('uses the standard API error for a failed export', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { code: 'CHAT_MESSAGE_NOT_FOUND', message: '回答不存在' },
    }), { status: 404, headers: { 'Content-Type': 'application/json' } })))

    await expect(downloadAnswerPdf('missing')).rejects.toMatchObject({ message: '回答不存在' })
  })
})
