// 轻量 Markdown 渲染（不引入外部依赖），覆盖助手回答中常见语法：
// 标题、段落、无序/有序列表、引用、代码块(带复制按钮)、表格、加粗/斜体/行内代码/链接，
// 并把 [n] 引用转换成可点击的引用按钮，由父组件处理点击。

export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

interface RenderContext {
  tokens: string[]
}

function codeToken(content: string, ctx: RenderContext): string {
  ctx.tokens.push(`<code>${escapeHtml(content)}</code>`)
  return `\u0001${ctx.tokens.length - 1}\u0001`
}

function isHr(line: string): boolean {
  return /^ {0,3}(-{3,}|\*{3,}|_{3,})\s*$/.test(line)
}

function headingOf(line: string): string | null {
  const match = /^(#{1,6})\s+(.*)$/.exec(line)
  if (!match) return null
  const level = match[1].length
  const content = inline(match[2])
  return `<h${level}>${content}</h${level}>`
}

function isCodeFence(line: string): boolean {
  return /^ {0,3}`{3,}/.test(line)
}

function inline(source: string): string {
  const ctx: RenderContext = { tokens: [] }
  let text = source

  // 先隔离行内代码，避免格式符号污染代码内容。
  const spans = text.split('`')
  text = spans
    .map((part, index) => {
      if (index % 2 === 1) return codeToken(part, ctx)
      return part
    })
    .join('')

  text = escapeHtml(text)
  // 移除图片，保留描述文字（本机服务不渲染外部图片）。
  text = text.replace(/!\[([^\]]*)]\([^)]*\)/g, (_match, alt: string) => alt || '')
  text = text.replace(
    /\[([^\]]+)]\((https?:[^)\s]+|[#/][^)\s]*)\)/g,
    (_match, label: string, url: string) => {
      if (!/^(https?:|#|\/)/i.test(url) || /javascript:/i.test(url)) return String(label)
      return `<a href="${url}" target="_blank" rel="noreferrer">${label}</a>`
    },
  )
  text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  text = text.replace(
    /(^|[\s(（])\*([^*\n]+)\*(?=[\s).,，。；;:：!?！？]|$)/g,
    (_match, pre: string, body: string) => `${pre}<em>${body}</em>`,
  )
  // [n] 编号引用 -> 引用按钮，交给 MarkdownView 事件委派打开引用抽屉。
  text = text.replace(/\[(\d{1,2})]/g, '<button type="button" class="citation" data-citation="$1">[$1]</button>')
  return text.replace(/\u0001(\d+)\u0001/g, (_match, index: string) => ctx.tokens[Number(index)])
}

function codeBlockHtml(language: string, content: string): string {
  const lines = content.replace(/\n+$/, '').split('\n')
  const lastLineHasSpaces = lines.length > 0 && /^\s+$/.test(lines[lines.length - 1] ?? '')
  const body = lastLineHasSpaces ? content.replace(/\s+$/, '') : content
  return [
    '<pre class="code-block">',
    `<button type="button" class="code-copy" title="复制代码">复制</button>`,
    `<code class="language-${escapeHtml(language)}">${escapeHtml(body)}</code>`,
    '</pre>',
  ].join('')
}

function cellText(raw: string): string {
  return inline(raw.trim())
}

function tableHtml(header: string[], rows: string[][]): string {
  const thead = `<thead><tr>${header.map((cell) => `<th>${cellText(cell)}</th>`).join('')}</tr></thead>`
  const tbody = rows
    .map((row) => `<tr>${row.map((cell) => `<td>${cellText(cell)}</td>`).join('')}</tr>`)
    .join('')
  return `<div class="md-table"><table>${thead}<tbody>${tbody}</tbody></table></div>`
}

function splitRow(line: string): string[] {
  const trimmed = line.trim()
  const withoutEdges = trimmed.replace(/^\|/, '').replace(/\|$/, '')
  return withoutEdges.split('|')
}

function isTableSeparator(line: string | undefined): boolean {
  if (!line) return false
  const cells = splitRow(line)
  return cells.length > 0 && cells.every((cell) => /^:?-{2,}:?$/.test(cell.trim()))
}

function toListItems(lines: string[]): string {
  return lines
    .map((line) => {
      const ordered = /^\s*(\d+)[.)]\s+/.exec(line)
      const bullet = /^\s*[-*+]\s+/.exec(line)
      const marker = ordered ? ordered[0] : bullet ? bullet[0] : ''
      const content = line.slice(marker.length)
      return `<li>${inline(content)}</li>`
    })
    .join('')
}

export function renderMarkdown(source: string): string {
  if (!source) return ''
  const lines = source.replace(/\r\n?/g, '\n').split('\n')
  const output: string[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index] ?? ''

    if (isCodeFence(line)) {
      const fence = /^ {0,3}(`{3,})/.exec(line)?.[1] ?? '```'
      const language = line.slice(line.indexOf(fence) + fence.length).trim()
      const closing = new RegExp(`^ {0,3}${fence.replace(/`/g, '`')}`)
      const body: string[] = []
      index += 1
      while (index < lines.length && !closing.test(lines[index] ?? '')) {
        body.push(lines[index] ?? '')
        index += 1
      }
      if (index < lines.length) index += 1
      output.push(codeBlockHtml(language, body.join('\n')))
      continue
    }

    if (!line.trim()) {
      index += 1
      continue
    }

    if (isHr(line)) {
      output.push('<hr>')
      index += 1
      continue
    }

    const heading = headingOf(line)
    if (heading) {
      output.push(heading)
      index += 1
      continue
    }

    if (line.trim().startsWith('|') && isTableSeparator(lines[index + 1])) {
      const header = splitRow(line)
      const rows: string[][] = []
      index += 2
      while (index < lines.length && (lines[index] ?? '').trim().startsWith('|') && lines[index]?.trim()) {
        rows.push(splitRow(lines[index] ?? ''))
        index += 1
      }
      output.push(tableHtml(header, rows))
      continue
    }

    if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line)
      const items: string[] = []
      while (index < lines.length) {
        const current = lines[index] ?? ''
        if (!current.trim()) break
        if (/^\s*([-*+]|\d+[.)])\s+/.test(current)) {
          items.push(current)
          index += 1
        } else if (/^\s{2,}\S/.test(current)) {
          items[items.length - 1] = `${items[items.length - 1] ?? ''}\n${current.trim()}`
          index += 1
        } else {
          break
        }
      }
      const tag = ordered ? 'ol' : 'ul'
      output.push(`<${tag}>${toListItems(items)}</${tag}>`)
      continue
    }

    if (/^\s*>\s?/.test(line)) {
      const quotes: string[] = []
      while (index < lines.length && /^\s*>\s?/.test(lines[index] ?? '')) {
        quotes.push((lines[index] ?? '').replace(/^\s*>\s?/, ''))
        index += 1
      }
      output.push(`<blockquote>${inline(quotes.join(' '))}</blockquote>`)
      continue
    }

    const paragraph: string[] = []
    while (index < lines.length) {
      const current = lines[index] ?? ''
      if (
        !current.trim() || isCodeFence(current) || headingOf(current) || isHr(current)
        || /^\s*([-*+]|\d+[.)])\s+/.test(current) || current.trim().startsWith('>')
      ) break
      paragraph.push(current)
      index += 1
    }
    output.push(`<p>${inline(paragraph.join('\n'))}</p>`)
  }

  return output.join('\n')
}
