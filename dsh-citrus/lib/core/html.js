/**
 * 富文本 -> 纯文本。
 *
 * 模型要读的是字，不是标签：段落/换行保留，图片给 [图] 占位，
 * 脚本样式注释全扔掉，实体解码。和 citrus 的实现保持一致。
 */

const NAMED_ENTITIES = {
  amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ',
  hellip: '…', mdash: '—', ndash: '–', middot: '·', bull: '•',
  ldquo: '“', rdquo: '”', lsquo: '‘', rsquo: '’',
  laquo: '«', raquo: '»', copy: '©', reg: '®', trade: '™',
  times: '×', divide: '÷', plusmn: '±', deg: '°', sect: '§',
  para: '¶', dagger: '†', permil: '‰', euro: '€', pound: '£',
  yen: '¥', cent: '¢', curren: '¤', sup2: '²', sup3: '³',
  frac12: '½', frac14: '¼', frac34: '¾', inexact: '≈', asymp: '≈',
  ne: '≠', le: '≤', ge: '≥', equiv: '≡', infin: '∞', sum: '∑',
  prod: '∏', radic: '√', int: '∫', part: '∂', nabla: '∇',
  isin: '∈', notin: '∉', cap: '∩', cup: '∪', and: '∧', or: '∨',
  there4: '∴', sim: '∼', cong: '≅', tilde: '˜', prime: '′',
  larr: '←', rarr: '→', uarr: '↑', darr: '↓', harr: '↔',
  ensp: ' ', emsp: ' ', thinsp: ' ', zwnj: '', zwj: '',
  lrm: '', rlm: '', shy: '', iexcl: '¡', iquest: '¿', micro: 'µ'
};

const ENTITY_RE = /&(#x?[0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]{1,31});/g;
const BLOCK_TAGS = '(p|div|section|article|blockquote|pre|h[1-6]|tr|table|ul|ol|dl|figure|figcaption)';

/** 解 HTML 实体（命名 + 十进制 + 十六进制）；坏实体原样留着。 */
export function decodeEntities(text) {
  if (!text) return '';
  return String(text).replace(ENTITY_RE, (whole, body) => {
    if (body[0] === '#') {
      const hex = body[1] === 'x' || body[1] === 'X';
      const digits = hex ? body.slice(2) : body.slice(1);
      const code = Number.parseInt(digits, hex ? 16 : 10);
      if (!Number.isFinite(code) || code < 0 || code > 0x10ffff) return whole;
      try {
        return String.fromCodePoint(code);
      } catch {
        return whole;
      }
    }
    return Object.prototype.hasOwnProperty.call(NAMED_ENTITIES, body) ? NAMED_ENTITIES[body] : whole;
  });
}

/**
 * HTML -> 纯文本。
 * @param {string} html
 * @param {{ maxChars?: number, truncationNote?: string }} [options]
 */
export function htmlToText(html, options = {}) {
  let text = String(html || '');
  if (!text) return '';
  const maxChars = options.maxChars || 0;
  const note = options.truncationNote || '\n…（后面还有，已截断）';

  text = text.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '');
  text = text.replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, '');
  text = text.replace(/<noscript\b[^>]*>[\s\S]*?<\/noscript>/gi, '');
  text = text.replace(/<!--[\s\S]*?-->/g, '');

  text = text.replace(/<img\b[^>]*>/gi, '[图]');
  text = text.replace(/<video\b[^>]*>[\s\S]*?<\/video>/gi, '[视频]');
  text = text.replace(/<math\b[^>]*>[\s\S]*?<\/math>/gi, '[公式]');

  text = text.replace(/<br\s*\/?>/gi, '\n');
  text = text.replace(new RegExp('</' + BLOCK_TAGS + '\\s*>', 'gi'), '\n');
  text = text.replace(new RegExp('<' + BLOCK_TAGS + '\\b[^>]*>', 'gi'), '\n');
  text = text.replace(/<li\b[^>]*>/gi, '\n· ');
  text = text.replace(/<hr\s*\/?>/gi, '\n——\n');

  text = text.replace(/<[^>]+>/g, '');
  text = decodeEntities(text);

  text = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  text = text.replace(/[ \t\f\v\u00a0\u200b]+/g, ' ');
  text = text.replace(/ *\n */g, '\n');
  text = text.replace(/\n{3,}/g, '\n\n').trim();

  if (maxChars > 0 && text.length > maxChars) {
    text = text.slice(0, maxChars).replace(/\s+$/, '') + note;
  }
  return text;
}

/** 从正文里裁一段当摘要（列表用）。 */
export function plainExcerpt(html, limit = 160) {
  if (!html) return '';
  let text = htmlToText(html).replace(/\n/g, ' ');
  text = text.replace(/\s+/g, ' ').trim();
  if (limit > 0 && text.length > limit) {
    text = text.slice(0, limit).replace(/\s+$/, '') + '…';
  }
  return text;
}
