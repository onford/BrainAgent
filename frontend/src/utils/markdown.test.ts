import { describe, expect, it } from 'vitest'
import { renderMarkdown } from './markdown'

describe('renderMarkdown', () => {
  it('renders common markdown and safe external links', () => {
    const html = renderMarkdown('## Result\n\n- **EEG**\n\n[paper](https://example.com)')

    expect(html).toContain('<h2>Result</h2>')
    expect(html).toContain('<strong>EEG</strong>')
    expect(html).toContain('target="_blank"')
    expect(html).toContain('rel="noopener noreferrer"')
  })

  it('does not render raw HTML', () => {
    const html = renderMarkdown('<script>alert(1)</script>')

    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;script&gt;')
  })
})
