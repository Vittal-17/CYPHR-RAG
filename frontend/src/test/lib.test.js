import { describe, it, expect } from 'vitest';
import { errorDetail } from '../lib/errors';
import {
  parseServerDate,
  groupChatsByRecency,
  splitFilename,
  formatBytes,
  pluralize,
} from '../lib/format';
import { splitSources } from '../lib/citations';
import { focusablesIn } from '../lib/focus';

describe('lib/errors: errorDetail', () => {
  it('extracts string detail from axios response data', () => {
    const error = { response: { data: { detail: 'Invalid credentials provided' } } };
    expect(errorDetail(error, 'Default error')).toBe('Invalid credentials provided');
  });

  it('falls back when detail is an array (FastAPI validation error)', () => {
    const error = {
      response: {
        data: {
          detail: [{ loc: ['body', 'email'], msg: 'field required', type: 'value_error' }],
        },
      },
    };
    expect(errorDetail(error, 'Validation error fallback')).toBe('Validation error fallback');
  });

  it('falls back when detail is empty, whitespace, or missing', () => {
    expect(errorDetail({ response: { data: { detail: '   ' } } }, 'Fallback')).toBe('Fallback');
    expect(errorDetail({ response: {} }, 'Fallback')).toBe('Fallback');
    expect(errorDetail(null, 'Fallback')).toBe('Fallback');
    expect(errorDetail(new Error('Network error'), 'Fallback')).toBe('Fallback');
  });
});

describe('lib/format', () => {
  describe('parseServerDate', () => {
    it('returns null for falsy, empty or non-date inputs', () => {
      expect(parseServerDate(null)).toBeNull();
      expect(parseServerDate('')).toBeNull();
      expect(parseServerDate('   ')).toBeNull();
      expect(parseServerDate({})).toBeNull();
      expect(parseServerDate('invalid-date')).toBeNull();
    });

    it('returns Date instance directly if valid', () => {
      const now = new Date();
      expect(parseServerDate(now)).toBe(now);
      expect(parseServerDate(new Date('invalid'))).toBeNull();
    });

    it('parses timestamps in milliseconds', () => {
      const timestamp = 1700000000000;
      const parsed = parseServerDate(timestamp);
      expect(parsed).toBeInstanceOf(Date);
      expect(parsed.getTime()).toBe(timestamp);
      expect(parseServerDate(NaN)).toBeNull();
    });

    it('appends Z to naive UTC date strings', () => {
      const naive = '2026-10-29T10:00:00';
      const parsed = parseServerDate(naive);
      expect(parsed.toISOString()).toBe('2026-10-29T10:00:00.000Z');
    });

    it('respects existing timezone designators', () => {
      const withZ = '2026-10-29T10:00:00Z';
      expect(parseServerDate(withZ).toISOString()).toBe('2026-10-29T10:00:00.000Z');

      const withOffset = '2026-10-29T10:00:00+02:00';
      expect(parseServerDate(withOffset).toISOString()).toBe('2026-10-29T08:00:00.000Z');
    });
  });

  describe('groupChatsByRecency', () => {
    it('groups chats into Today, Yesterday, Week, Month, and Older buckets', () => {
      const now = new Date();
      const createDate = (daysAgo) => {
        const d = new Date(now);
        d.setDate(d.getDate() - daysAgo);
        return d.toISOString();
      };

      const chats = [
        { chat_id: '1', title: 'New chat without date' },
        { chat_id: '2', title: 'Today chat', created_at: createDate(0) },
        { chat_id: '3', title: 'Yesterday chat', created_at: createDate(1) },
        { chat_id: '4', title: 'Last week chat', created_at: createDate(5) },
        { chat_id: '5', title: 'Last month chat', created_at: createDate(20) },
        { chat_id: '6', title: 'Older chat', created_at: createDate(60) },
      ];

      const groups = groupChatsByRecency(chats);
      const groupMap = Object.fromEntries(groups.map((g) => [g.id, g]));

      expect(groupMap.today.chats.map((c) => c.chat_id)).toEqual(['1', '2']);
      expect(groupMap.yesterday.chats.map((c) => c.chat_id)).toEqual(['3']);
      expect(groupMap.week.chats.map((c) => c.chat_id)).toEqual(['4']);
      expect(groupMap.month.chats.map((c) => c.chat_id)).toEqual(['5']);
      expect(groupMap.older.chats.map((c) => c.chat_id)).toEqual(['6']);
    });

    it('filters out empty buckets', () => {
      const chats = [{ chat_id: '1', created_at: new Date().toISOString() }];
      const groups = groupChatsByRecency(chats);
      expect(groups.length).toBe(1);
      expect(groups[0].id).toBe('today');
    });
  });

  describe('splitFilename', () => {
    it('separates stem and extension correctly', () => {
      expect(splitFilename('annual_report.pdf')).toEqual({ stem: 'annual_report', ext: '.pdf' });
      expect(splitFilename('archive.tar.gz')).toEqual({ stem: 'archive.tar', ext: '.gz' });
      expect(splitFilename('.gitignore')).toEqual({ stem: '.gitignore', ext: '' });
      expect(splitFilename('noextension')).toEqual({ stem: 'noextension', ext: '' });
      expect(splitFilename('trailingdot.')).toEqual({ stem: 'trailingdot.', ext: '' });
      expect(splitFilename('')).toEqual({ stem: '', ext: '' });
      expect(splitFilename(null)).toEqual({ stem: '', ext: '' });
    });
  });

  describe('formatBytes', () => {
    it('formats bytes into appropriate human units', () => {
      expect(formatBytes(0)).toBe('0 B');
      expect(formatBytes(512)).toBe('512 B');
      expect(formatBytes(1024)).toBe('1.0 KB');
      expect(formatBytes(1536)).toBe('1.5 KB');
      expect(formatBytes(1048576)).toBe('1.0 MB');
      expect(formatBytes(26214400)).toBe('25 MB');
      expect(formatBytes(1073741824)).toBe('1.0 GB');
      expect(formatBytes(-10)).toBe('');
      expect(formatBytes(NaN)).toBe('');
      expect(formatBytes(Infinity)).toBe('');
    });
  });

  describe('pluralize', () => {
    it('pluralizes nouns based on count', () => {
      expect(pluralize(1, 'document')).toBe('1 document');
      expect(pluralize(0, 'document')).toBe('0 documents');
      expect(pluralize(5, 'document')).toBe('5 documents');
      expect(pluralize(1, 'category', 'categories')).toBe('1 category');
      expect(pluralize(3, 'category', 'categories')).toBe('3 categories');
    });
  });
});

describe('lib/citations: splitSources', () => {
  it('returns plain text when there are no sources headings', () => {
    const text = 'Here is a helpful answer without any citations.';
    const result = splitSources(text);
    expect(result.body).toBe(text);
    expect(result.sources).toEqual([]);
  });

  it('correctly splits answers with standard source citations', () => {
    const content = `Based on the documents, revenue grew 25% year-over-year.

### 📚 Sources:
- **financials.pdf** (Page 3)
- **q3_presentation.pdf** (Page 12)`;

    const result = splitSources(content);
    expect(result.body).toBe('Based on the documents, revenue grew 25% year-over-year.');
    expect(result.sources).toEqual([
      { filename: 'financials.pdf', page: '3' },
      { filename: 'q3_presentation.pdf', page: '12' },
    ]);
  });

  it('handles variations like pg., p., and missing pages', () => {
    const content = `Key takeaways.

### Sources
* **whitepaper.pdf** (pg. 5)
+ notes.pdf (p 8)
- summary.pdf`;

    const result = splitSources(content);
    expect(result.sources).toEqual([
      { filename: 'whitepaper.pdf', page: '5' },
      { filename: 'notes.pdf', page: '8' },
      { filename: 'summary.pdf', page: null },
    ]);
  });

  it('deduplicates identical source entries', () => {
    const content = `Analysis.

### Sources:
- **report.pdf** (Page 4)
- **report.pdf** (Page 4)
- **report.pdf** (Page 7)`;

    const result = splitSources(content);
    expect(result.sources).toHaveLength(2);
    expect(result.sources).toEqual([
      { filename: 'report.pdf', page: '4' },
      { filename: 'report.pdf', page: '7' },
    ]);
  });

  it('returns untouched content if trailing lines do not match citation format', () => {
    const content = `First part.

### Sources:
This is just a regular paragraph discussing historical sources, not list items.`;

    const result = splitSources(content);
    expect(result.body).toBe(content);
    expect(result.sources).toEqual([]);
  });
});

describe('lib/focus', () => {
  it('finds focusable elements in DOM order and excludes hidden items', () => {
    document.body.innerHTML = `
      <div id="container">
        <a href="#link" id="link1">Link</a>
        <button id="btn1">Button 1</button>
        <button id="btn-disabled" disabled>Disabled</button>
        <input type="text" id="input1" />
        <div tabindex="0" id="div-focusable">Focusable div</div>
        <div tabindex="-1" id="div-negative">Negative tabindex</div>
        <div style="display: none">
          <button id="hidden-btn">Hidden button</button>
        </div>
      </div>
    `;

    const container = document.getElementById('container');
    const focusables = focusablesIn(container);
    const ids = focusables.map((el) => el.id);

    expect(ids).toContain('link1');
    expect(ids).toContain('btn1');
    expect(ids).toContain('input1');
    expect(ids).toContain('div-focusable');
    expect(ids).not.toContain('btn-disabled');
    expect(ids).not.toContain('div-negative');
    expect(ids).not.toContain('hidden-btn');
  });

  it('returns empty array when container is null', () => {
    expect(focusablesIn(null)).toEqual([]);
  });
});
