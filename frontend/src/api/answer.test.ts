import { afterEach, describe, expect, it, vi } from 'vitest'

import { streamAnswer } from './answer'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('streamAnswer task metadata', () => {
  it('exposes the answer job id before the stream finishes', async () => {
    let finish!: () => void
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        finish = () => {
          controller.enqueue(new TextEncoder().encode('event: done\ndata: {"type":"done"}\n\n'))
          controller.close()
        }
      },
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, {
      status: 200,
      headers: {
        'X-Chat-Session-Id': 'session-1',
        'X-Chat-Message-Id': 'message-1',
        'X-Answer-Job-Id': 'job-1',
      },
    })))

    const started = vi.fn()
    const pending = streamAnswer({
      question: '测试', useDeepseek: false, useHarness: false, history: [],
    }, new AbortController().signal, () => undefined, started)

    await vi.waitFor(() => expect(started).toHaveBeenCalledWith({
      sessionId: 'session-1', messageId: 'message-1', jobId: 'job-1',
    }))
    finish()
    await pending
  })
})
