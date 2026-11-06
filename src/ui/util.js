/**
 * WordPulse page helpers that don't depend on page state:
 * colour maths for the mood looks, and the original lyrics used by the browser preview.
 */
(function () {
  'use strict';

  function parseColor(c) {
    let m = /^#([0-9a-f]{6})$/i.exec(c);
    if (m) { const n = parseInt(m[1], 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
    m = /rgba?\(([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)/i.exec(c);
    return m ? [+m[1], +m[2], +m[3]] : [255, 45, 111];
  }
  function toHsl([r, g, b]) {
    r /= 255; g /= 255; b /= 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2;
    if (max === min) return [0, 0, l];
    const d = max - min, s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    const h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return [h * 60, s, l];
  }
  // each mood re-tunes the album colour instead of replacing it
  function moodColor(base, mood) {
    let [h, s, l] = toHsl(parseColor(base));
    if (mood === 'NEON')   { s = 1; l = 0.6; }
    if (mood === 'BRIGHT') { s = Math.max(s, 0.85); l = 0.6; }
    if (mood === 'HEAVY')  { h = (h > 180 ? h - 360 : h) * 0.25; s = 0.85; l = 0.5; }   // pull toward red
    if (mood === 'SMOOTH') { s = Math.min(s, 0.75); l = 0.62; }
    if (mood === 'SOFT')   { s = Math.min(s, 0.45); l = 0.7; }
    return `hsl(${((h % 360) + 360) % 360} ${Math.round(s * 100)}% ${Math.round(l * 100)}%)`;
  }

  function buildPreviewLyrics() {
    // Original placeholder lines, written for this preview.
    const ICONS = { night: '🌙', tell: '💬', stars: '⭐', burn: '🔥', call: '📞', morning: '☀️', heart: '❤️', wait: '⏳', see: '👁️', home: '🏠' };
    const text = [
      'Hold the night a little longer',
      'Tell me that the stars still burn',
      'Wait for me and I will see you',
      'Call me when the morning comes home',
    ];
    let t = 1.0;
    const lines = text.map(line => {
      const start = t;
      const words = line.split(' ').map(w => {
        const d = 0.32 + Math.min(0.35, w.length * 0.045);
        const word = { text: w, start_time: t, end_time: t + d, icon: ICONS[w.toLowerCase()] || '' };
        t += d;
        return word;
      });
      const ln = { text: line, start_time: start, end_time: t, words };
      t += 1.0;
      return ln;
    });
    return { lines, duration: t + 1 };
  }

  // rotate a colour's hue by `deg` (per-song colour variety)
  function hueShift(color, deg) {
    if (!deg) return color;
    const m = /^hsl\(([\d.]+) ([\d.]+)% ([\d.]+)%\)$/.exec(color);
    const [h, s, l] = m ? [+m[1], +m[2] / 100, +m[3] / 100] : toHsl(parseColor(color));
    return `hsl(${(((h + deg) % 360) + 360) % 360} ${Math.round(s * 100)}% ${Math.round(l * 100)}%)`;
  }

  // lines that repeat (the chorus, a hook): the same words twice or more
  function chorusLines(lines) {
    const norm = t => String(t || '').toLowerCase().replace(/[^a-z0-9\u00c0-\uffff ]+/g, '').replace(/\s+/g, ' ').trim();
    const count = new Map();
    lines.forEach(l => { const k = norm(l.text); if (k.length >= 8) count.set(k, (count.get(k) || 0) + 1); });
    const out = new Set();
    lines.forEach((l, i) => { if ((count.get(norm(l.text)) || 0) >= 2) out.add(i); });
    return out;
  }

  window.WVUtil = { parseColor, toHsl, moodColor, hueShift, chorusLines, buildPreviewLyrics };
})();
