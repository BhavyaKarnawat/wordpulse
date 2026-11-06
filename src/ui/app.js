/**
 * WordPulse — word-by-word lyric stage.
 *
 * Each visible word is a persistent, keyed element. On every word change we
 * compute a layout for the current style and let CSS transitions glide the
 * words to their new slots, so the stack moves instead of being redrawn.
 */
(function () {
  'use strict';

  // ---------- State ----------
  let lyrics = null;
  let track = null;
  let style = 'SHIP';
  let mode = 'FULLSCREEN_AMBIENT';
  let alwaysOnTop = false;
  let demoMode = false;
  let basePos = 0;
  let baseTime = performance.now();
  let playing = false;
  let duration = 0;
  let offsetMs = 0;
  let stateVersion = -1;
  let syncing = false;
  let layoutKey = '';
  let standalone = false;
  let hideTimer = null;
  let unit = 100;
  let currentTrackId = '';
  let lastPos = 0;

  const body = document.getElementById('appBody');
  const stack = document.getElementById('stack');
  const trackTitle = document.getElementById('trackTitle');
  const trackArtist = document.getElementById('trackArtist');
  const albumArt = document.getElementById('albumArt');
  const progressFill = document.getElementById('progressFill');
  const progressBarWrap = document.getElementById('progressBarWrap');
  const segs = document.querySelectorAll('.seg');
  const btnPin = document.getElementById('btnPinToggle');
  const btnMode = document.getElementById('btnModeToggle');
  const btnDemo = document.getElementById('btnDemoToggle');
  const demoBadge = document.getElementById('demoBadge');

  const { moodColor, buildPreviewLyrics } = window.WVUtil;   // util.js
  const api = () => (window.pywebview && window.pywebview.api) || null;
  const call = (name, ...args) => { const a = api(); if (a && a[name]) a[name](...args).catch(() => {}); };

  // ---------- Sizing ----------
  const measureCtx = document.createElement('canvas').getContext('2d');
  let FONT_FAMILY = '"Segoe UI Variable Display", "Segoe UI", sans-serif';
  const widthCache = new Map();
  let cfg = {};                       // saved settings + live state from Python
  const caps = t => (cfg.uppercase ? String(t).toUpperCase() : t);
  function emWidth(text) {
    text = caps(text);
    let w = widthCache.get(text);
    if (w === undefined) {
      measureCtx.font = `900 100px ${FONT_FAMILY}`;
      w = measureCtx.measureText(text).width / 100;
      widthCache.set(text, w);
    }
    return Math.max(w, 0.6);
  }

  function computeUnit() {
    const floating = mode === 'DESKTOP_OVERLAY';
    unit = Math.min(innerWidth * (floating ? 0.13 : 0.105), innerHeight * (floating ? 0.22 : 0.16)) * (cfg.font_scale || 1);
    document.documentElement.style.setProperty('--u', unit + 'px');
    layoutKey = '';
  }
  addEventListener('resize', computeUnit);

  // ---------- Convex lens displacement map ----------
  (function buildLensMap() {
    const N = 320, k = 0.42;
    const c = document.createElement('canvas');
    c.width = c.height = N;
    const ctx = c.getContext('2d');
    const img = ctx.createImageData(N, N);
    // Small scale = each 8-bit step moves ~1px, so edges stay smooth. Must match index.html.
    const scale = 0.17;
    for (let y = 0; y < N; y++) {
      for (let x = 0; x < N; x++) {
        const px = (x / (N - 1)) * 2 - 1;
        const py = (y / (N - 1)) * 2 - 1;
        const r2 = px * px + py * py;
        const f = r2 < 1 ? k * (1 - r2) : 0;
        // sample closer to the centre -> magnify the middle, compress the rim
        const ox = (-f * px * 0.5) / scale;
        const oy = (-f * py * 0.5) / scale;
        const i = (y * N + x) * 4;
        img.data[i] = Math.round((0.5 + ox) * 255);
        img.data[i + 1] = Math.round((0.5 + oy) * 255);
        img.data[i + 2] = 128;
        img.data[i + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    const href = c.toDataURL();
    const fe = document.getElementById('lensMap');
    fe.setAttribute('href', href);
    fe.setAttributeNS('http://www.w3.org/1999/xlink', 'xlink:href', href);
  })();

  // ---------- Style / mode ----------
  const STYLE_CLASS = {
    SHIP: 'style-ship', FISHEYE: 'style-fisheye', FISHEYE_VISUAL: 'style-fisheye-visual', VISUAL: 'style-visual',
    POP: 'style-pop', STAMP: 'style-stamp', LINE: 'style-line', ORBIT: 'style-orbit',
    INKBLOT: 'style-inkblot', SQUEEZE: 'style-squeeze', REMOLD: 'style-remold',
  };

  function setStyle(s, notify = true) {
    if (!STYLE_CLASS[s]) s = 'SHIP';
    style = s;
    Object.values(STYLE_CLASS).forEach(c => body.classList.remove(c));
    body.classList.add(STYLE_CLASS[s]);
    segs.forEach(b => b.classList.toggle('active', b.dataset.style === s));
    layoutKey = '';
    if (notify) call('set_display_style', s);
  }

  const MODES = ['DESKTOP_WALLPAPER', 'FULLSCREEN_AMBIENT', 'DESKTOP_OVERLAY'];
  let wallpaperLoaded = false;

  async function loadWallpaper() {
    const a = api();
    if (wallpaperLoaded || !a || !a.get_wallpaper) return;
    wallpaperLoaded = true;
    try {
      const url = await a.get_wallpaper();
      if (url) document.documentElement.style.setProperty('--wall', `url("${url}")`);
    } catch (_) { wallpaperLoaded = false; }
  }

  function setMode(m, notify = true) {
    if (!MODES.includes(m)) m = 'DESKTOP_WALLPAPER';
    mode = m;
    body.classList.toggle('mode-wallpaper', m === 'DESKTOP_WALLPAPER');
    body.classList.toggle('mode-fullscreen', m === 'FULLSCREEN_AMBIENT');
    body.classList.toggle('mode-floating', m === 'DESKTOP_OVERLAY');
    if (m === 'DESKTOP_WALLPAPER' || cfg.fullscreen_bg === 'wallpaper') loadWallpaper();
    computeUnit();
    if (notify) call('set_display_mode', m);
  }

  function setPin(on, notify = true) {
    alwaysOnTop = on;
    btnPin.classList.toggle('active', on);
    if (notify) call('toggle_always_on_top', on);
  }

  function setDemo(on) {
    demoMode = on;
    demoBadge.textContent = on ? 'DEMO' : 'LIVE';
    demoBadge.classList.toggle('demo-active', on);
  }

  function revealChrome() {
    body.classList.add('controls-revealed');
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => body.classList.remove('controls-revealed'), 2600);
  }
  addEventListener('mousemove', revealChrome);
  document.addEventListener('mouseleave', () => body.classList.remove('controls-revealed'));

  // ---------- Palette ----------
  let lastPalette = null;
  function applyPalette(p) {
    if (p) lastPalette = p;
    const root = document.documentElement.style;
    if (cfg.auto_theme === false) {
      root.setProperty('--hl', cfg.highlight_color);
      root.setProperty('--lyric', cfg.lyric_color);
      root.setProperty('--secondary', cfg.secondary_color);
    } else {
      root.removeProperty('--lyric');
      root.removeProperty('--secondary');
      const base = (lastPalette && lastPalette.highlight) || '#ff2d6f';
      root.setProperty('--hl', activeMood() ? moodColor(base, activeMood()) : base);
    }
  }

  // ---------- Mood ----------
  function activeMood() {
    return cfg.auto_mood === 'full' && cfg.mood ? cfg.mood : '';
  }
  const BEAT_GAIN = { NEON: 1, HEAVY: 1, BRIGHT: 0.8, SMOOTH: 0.35, SOFT: 0 };
  const beat = { period: 0, last: 0, conf: 0, dropAt: 0, lastDropSeen: null };
  function applyBeat(b) {
    if (!b || !b.bpm || !b.period || b.beat_age == null) { beat.period = 0; return; }
    const now = performance.now();
    const fresh = now - b.beat_age * 1000;
    const per = b.period * 1000;
    if (beat.period && Math.abs(per - beat.period) < 15) {
      // keep our clock unless it has drifted; snap the phase gently
      const predicted = beat.last + Math.round((fresh - beat.last) / per) * per;
      const err = fresh - predicted;
      beat.last = predicted + err * 0.3;
    } else {
      beat.last = fresh;
    }
    beat.period = per;
    beat.conf = b.confidence || 0;
    if (b.drop_age != null && b.drop_age < 0.6 && beat.lastDropSeen !== Math.round(now / 1000 - b.drop_age)) {
      beat.lastDropSeen = Math.round(now / 1000 - b.drop_age);
      triggerDrop();
    }
  }
  let dropTimer = 0;
  function triggerDrop() {
    const m = activeMood() || 'BRIGHT';
    if (cfg.auto_mood === 'off' || reduceMotion() || !(m === 'NEON' || m === 'HEAVY')) return;
    body.classList.remove('drop'); void body.offsetWidth; body.classList.add('drop');
    clearTimeout(dropTimer); dropTimer = setTimeout(() => body.classList.remove('drop'), 520);
  }
  let lastBeatVar = -1;
  function beatFrame(now) {
    let v = 0;
    if (beat.period && cfg.auto_mood && cfg.auto_mood !== 'off' && beat.conf >= 0.2 && !reduceMotion()) {
      const since = ((now - beat.last) % beat.period + beat.period) % beat.period;
      const gain = (BEAT_GAIN[activeMood() || 'BRIGHT'] ?? 0.8) * (cfg.beat_strength ?? 1);
      v = Math.exp(-since / 110) * gain;              // sharp attack on the beat, ~0.1 s decay
    }
    if (Math.abs(v - lastBeatVar) > 0.01 || (v === 0 && lastBeatVar !== 0)) {
      lastBeatVar = v;
      stack.style.setProperty('--beat', v.toFixed(3));
    }
  }

  // ---------- Settings from Python ----------
  const POSITIONS = {
    center: [0.5, 0.5], top: [0.5, 0.24], bottom: [0.5, 0.76],
    'top-left': [0.3, 0.24], 'top-right': [0.7, 0.24], 'bottom-left': [0.3, 0.76], 'bottom-right': [0.7, 0.76],
  };
  function anchor() {
    if (cfg.position === 'custom') return [cfg.custom_x ?? 0.5, cfg.custom_y ?? 0.5];
    return POSITIONS[cfg.position] || POSITIONS.center;
  }
  function reduceMotion() {
    return cfg.reduce_motion === 'on' || (cfg.reduce_motion !== 'off' && !!cfg.system_reduce_motion)
      || (!!cfg.screensaver && false);
  }
  let baseStyle = 'SHIP';
  function applySettings(s) {
    const prev = cfg;
    cfg = s;
    const root = document.documentElement.style;
    if (s.font_family && s.font_family !== prev.font_family) {
      FONT_FAMILY = `"${s.font_family}", "Segoe UI Variable Display", "Segoe UI", sans-serif`;
      root.setProperty('--font', FONT_FAMILY);
      widthCache.clear(); rawCache.clear();
    }
    if (s.uppercase !== prev.uppercase) { widthCache.clear(); rawCache.clear(); }
    body.classList.toggle('upper', !!s.uppercase);
    body.dataset.slab = s.slab_shape || 'sharp';
    root.setProperty('--wall-dim', s.wall_dim ?? 0.35);
    body.classList.toggle('wall-blur', !!s.wall_blur);
    body.classList.toggle('album-bg', !!s.album_background);
    body.dataset.fsbg = s.fullscreen_bg || 'black';
    if (s.fullscreen_bg === 'wallpaper') loadWallpaper();
    root.setProperty('--motion', s.motion ?? 1);
    body.classList.toggle('reduce-motion', reduceMotion());
    body.classList.toggle('lowpower', !!(s.battery_saver && s.on_battery));
    body.classList.toggle('lyrics-hidden', !!s.hidden);
    const [ax] = anchor();
    root.setProperty('--ox', ((ax - 0.5) * innerWidth) + 'px');
    offsetMs = (s.timing_offset_ms || 0) + (s.song_offset_ms || 0);
    baseStyle = s.display_style || baseStyle;
    const mood = activeMood();
    body.dataset.mood = mood ? mood.toLowerCase() : '';
    const moodStyle = mood && (s.shuffle || 'off') === 'off' && s.mood_styles ? s.mood_styles[mood] : '';
    if (moodStyle && STYLE_CLASS[moodStyle]) {
      if (style !== moodStyle) setStyle(moodStyle, false);
    } else if ((s.shuffle || 'off') === 'off' || s.display_style !== prev.display_style || s.shuffle !== prev.shuffle
               || (prev.mood && !mood)) {
      setStyle(baseStyle, false);
    }
    applyPalette();
    computeUnit();
  }

  // ---------- Shuffle ----------
  let lastShuffleLine = -1;
  function pickShuffle() {
    const pool = (cfg.shuffle_pool && cfg.shuffle_pool.length ? cfg.shuffle_pool : Object.keys(STYLE_CLASS))
      .filter(x => STYLE_CLASS[x]);
    const choices = pool.length > 1 ? pool.filter(x => x !== style) : pool;
    setStyle(choices[Math.floor(Math.random() * choices.length)], false);
  }

  // ---------- Status messages (finding lyrics / none found) ----------
  let statusUntil = 0;

  // ---------- Track ----------
  function applyTrack(t) {
    track = t;
    trackTitle.textContent = t.display_title || t.title || 'Waiting for music';
    trackArtist.textContent = t.display_artist || t.artist || '';
    if (t.thumbnail_base64 && t.thumbnail_base64.length > 20) albumArt.src = t.thumbnail_base64;
    else albumArt.removeAttribute('src');
    duration = t.duration || 0;
    const id = t.track_id || (t.artist + ' - ' + t.title);
    if (t.thumbnail_base64 && t.thumbnail_base64.length > 20) document.documentElement.style.setProperty('--art', `url("${t.thumbnail_base64}")`);
    else document.documentElement.style.removeProperty('--art');
    if (id !== currentTrackId) {          // new song: take its position as-is
      currentTrackId = id;
      statusUntil = performance.now() + 6000;
      if (cfg.shuffle === 'song') pickShuffle();
      playing = t.status === 'PLAYING';
      basePos = t.position || 0;
      baseTime = performance.now();
      lastPos = 0;
    }
  }

  // Blend a reported position into our own clock. Small drift is eased in over
  // several polls; only real jumps (seek, pause, buffering) snap.
  function correctClock(reported, isPlaying) {
    const now = performance.now();
    const predicted = basePos + (playing ? (now - baseTime) / 1000 : 0);
    const drift = reported - predicted;
    if (!isPlaying || !playing || Math.abs(drift) > 0.6) {
      basePos = reported;
      if (Math.abs(drift) > 0.6) lastPos = 0; // allow a backwards seek
    } else {
      basePos = predicted + drift * 0.12;
    }
    baseTime = now;
    playing = isPlaying;
  }

  // ---------- Backend sync ----------
  async function syncFullState() {
    const a = api();
    if (!a) return;
    try {
      const st = await a.get_state();
      if (!st) return;
      stateVersion = st.version;
      const s = st.settings || {};
      if (s.display_mode) setMode(s.display_mode, false);
      if (typeof s.always_on_top === 'boolean') setPin(s.always_on_top, false);
      if (typeof s.mock_mode === 'boolean') setDemo(s.mock_mode);
      applySettings(s);
      if (st.track && st.track.title) applyTrack(st.track);
      if (st.palette) applyPalette(st.palette);
      lyrics = st.lyrics || null;
      layoutKey = '';
    } catch (e) {
      console.warn('get_state failed', e);
    }
  }

  async function pollPlayback() {
    const a = api();
    if (syncing || !a) return;
    syncing = true;
    try {
      const pb = await a.get_playback();
      if (pb) {
        if (pb.version !== stateVersion) await syncFullState();
        correctClock(pb.position, pb.status === 'PLAYING');
        applyBeat(pb.status === 'PLAYING' ? pb.beat : null);
      }
    } catch (_) { /* transient during track changes */ }
    finally { syncing = false; }
  }

  addEventListener('pywebviewready', async () => {
    standalone = false;
    await syncFullState();
    // fast while playing (smooth timing), slow while paused or hidden
    (function loop() { pollPlayback().finally(() => setTimeout(loop, playing && !cfg.hidden ? 150 : 600)); })();
  });

  // ---------- Timeline lookup ----------
  function locate(pos) {
    const lines = lyrics && lyrics.lines;
    const src = lyrics && lyrics.source;
    if (src === 'Loading') return { kind: 'status', text: 'Finding lyrics…' };
    if (src === 'None') return performance.now() < statusUntil ? { kind: 'status', text: 'No lyrics found' } : { kind: 'none' };
    if (src === 'Offline') return performance.now() < statusUntil ? { kind: 'status', text: 'Offline \u2014 lyrics will appear when you\u2019re back online' } : { kind: 'none' };
    if (!lines || !lines.length) return { kind: 'none' };
    if (lyrics && lyrics.is_synced === false && lyrics.has_word_sync === false && lines.every(l => !l.start_time)) {
      return performance.now() < statusUntil ? { kind: 'status', text: 'These lyrics have no timing yet' } : { kind: 'none' };
    }

    if (pos < lines[0].start_time) {
      return { kind: 'gap', next: lines[0], nextIdx: 0, until: lines[0].start_time - pos };
    }
    let li = lines.length - 1;
    for (let i = 0; i < lines.length; i++) {
      const nextStart = i + 1 < lines.length ? lines[i + 1].start_time : Infinity;
      if (pos >= lines[i].start_time && pos < nextStart) { li = i; break; }
    }
    const line = lines[li];
    const words = line.words && line.words.length ? line.words : [{ text: line.text, start_time: line.start_time, end_time: line.end_time }];
    const next = lines[li + 1];

    // long instrumental gap after the line has finished
    const lineEnd = Math.max(line.end_time || 0, words[words.length - 1].end_time || 0);
    if (next && pos > lineEnd + 1.2 && next.start_time - pos > 0.9) {
      return { kind: 'gap', next, nextIdx: li + 1, until: next.start_time - pos };
    }

    let wi = 0;
    for (let w = 0; w < words.length; w++) { if (pos >= words[w].start_time) wi = w; else break; }
    const wEnd = wi + 1 < words.length ? words[wi + 1].start_time : (words[wi].end_time || words[wi].start_time + 0.6);
    const span = Math.max(0.05, wEnd - words[wi].start_time);
    const prog = Math.min(1, Math.max(0, (pos - words[wi].start_time) / span));
    return { kind: 'word', li, words, wi, prog, next, lineEnded: pos > lineEnd };
  }

  // ---------- Layout per style ----------
  // Each slot: { key, text, icon, role: past|active|ghost, s, x, y, z, r, o, italic, wipe }
  // Every style pins the sung word to the centre of the visible area.

  function slot(li, wi, w, role, extra) {
    return Object.assign({ key: li + ':' + wi, text: w.text, icon: w.icon || '', role, s: 1, x: 0, y: 0, r: 0, o: 1, italic: false }, extra);
  }

  // Visible area in stack coordinates (0 = screen centre): above the taskbar on the
  // desktop, and inside the lens box for the fisheye styles (the filter clips outside it).
  function safeArea() {
    const H = innerHeight;
    let top = -H / 2, bottom = H / 2;
    if (mode === 'DESKTOP_WALLPAPER' && screen.height && screen.availHeight < screen.height) {
      const r = H / screen.height;
      const availTop = screen.availTop || 0;
      top += availTop * r;
      bottom -= (screen.height - availTop - screen.availHeight) * r;
    }
    if (style === 'FISHEYE' || style === 'FISHEYE_VISUAL') {
      top = Math.max(top, -H * 0.42);
      bottom = Math.min(bottom, H * 0.42);
    }
    // Ship's 3D drift tilts the wall, so its outer rows need extra headroom
    const margin = H * (style === 'SHIP' ? 0.09 : 0.045);
    top += margin; bottom -= margin;
    const [, ay] = anchor();
    const want = -H / 2 + ay * H;                       // where the chosen position puts the sung word
    const centre = Math.max(top + unit * 0.6, Math.min(bottom - unit * 0.6, want));
    return { top, bottom, centre: (top < bottom) ? centre : (top + bottom) / 2 };
  }

  const rowH = s => unit * s;   // visual row height incl. slab

  // Vertical stack around the sung word: rows above grow upward, rows below grow
  // downward. If a side doesn't fit it shrinks; the sung word never moves.
  function stackAroundActive(slots, gap) {
    const area = safeArea();
    const ai = slots.findIndex(s => s.role === 'active');
    if (ai < 0) return slots;
    const a = slots[ai];
    const maxActive = area.bottom - area.top;
    if (rowH(a.s) > maxActive) a.s = maxActive / unit;
    a.y = area.centre;

    const side = (list, dir) => {
      if (!list.length) return;
      const room = dir < 0 ? (a.y - rowH(a.s) / 2) - area.top : area.bottom - (a.y + rowH(a.s) / 2);
      const need = list.reduce((sum, s) => sum + rowH(s.s) * (1 + gap), 0);
      const k = need > room ? Math.max(0.2, room / need) : 1;
      let edge = a.y + dir * rowH(a.s) / 2;
      list.forEach(s => {
        s.s *= k;
        const h = rowH(s.s);
        edge += dir * h * gap;
        s.y = edge + dir * h / 2;
        edge += dir * h;
      });
    };
    side(slots.slice(0, ai).reverse(), -1);  // nearest first, going up
    side(slots.slice(ai + 1), 1);            // nearest first, going down
    return slots;
  }

  // 0..1 pseudo-random from an integer, stable per word
  const hash01 = n => { const x = Math.sin(n * 12.9898 + 78.233) * 43758.5453; return x - Math.floor(x); };

  const ICON_STYLES = new Set(['VISUAL', 'FISHEYE_VISUAL', 'POP', 'STAMP']);
  function maxWordWidth() {
    const [ax] = anchor();
    // a word is centred on the anchor, so it can be at most twice the distance to the nearer edge
    const room = 2 * Math.min(ax, 1 - ax) * innerWidth * 0.92;
    const icon = ICON_STYLES.has(style) ? unit * 1.1 : 0;   // room for the icon beside the word
    return Math.max(unit * 1.5, Math.min(innerWidth * ((cfg.max_width_pct || 78) / 100), room - icon, unit * 7.2));
  }

  function layoutFor(loc) {
    const area = safeArea();
    if (loc.kind === 'status') {
      return [{ key: 'status:' + loc.text, text: loc.text, icon: '', role: 'ghost', s: 0.34, x: 0, y: area.centre, r: 0, o: 0.75 }];
    }
    if (loc.kind === 'none') {
      if (mode === 'DESKTOP_WALLPAPER') return []; // plain desktop until music plays
      const label = track && track.title ? track.title : 'Play something';
      return [{ key: 'idle:' + label, text: label, icon: '', role: 'ghost', s: 0.42, x: 0, y: area.centre, r: 0, o: 0.8 }];
    }
    if (loc.kind === 'gap') {
      if (loc.until > 1.4 || !loc.next) return [];
      const w = (loc.next.words && loc.next.words[0]) || { text: loc.next.text };
      return [slot(loc.nextIdx, 0, w, 'ghost', { s: 0.6, y: area.centre, o: 0.55 })];
    }

    const { li, words: W, wi, prog } = loc;
    const showGhost = wi + 1 < W.length && prog > 0.55;
    const maxW = maxWordWidth();
    const fit = (text, lo, hi) => Math.max(lo, Math.min(hi, maxW / (emWidth(text) * unit)));
    const wordSpan = k => {
      const end = k + 1 < W.length ? W[k + 1].start_time : (W[k].end_time || W[k].start_time + 0.6);
      return Math.max(0.08, end - W[k].start_time);
    };
    const slots = [];

    switch (style) {
      case 'SHIP': {
        // justified typographic wall: every row scaled to the same column width
        for (let k = Math.max(0, wi - 3); k < wi; k++) {
          const d = wi - k;
          slots.push(slot(li, k, W[k], 'past', { s: fit(W[k].text, 0.38, 1.55), o: d >= 3 ? 0.6 : 1 }));
        }
        slots.push(slot(li, wi, W[wi], 'active', { s: fit(W[wi].text, 0.38, 1.55) }));
        if (showGhost) slots.push(slot(li, wi + 1, W[wi + 1], 'ghost', { s: fit(W[wi + 1].text, 0.3, 0.9) * 0.6, o: 0.5 }));
        return stackAroundActive(slots, -0.06);
      }

      case 'FISHEYE':
      case 'FISHEYE_VISUAL': {
        // convex stack: the sung word sits closest to the glass
        const SCALE = [1.32, 0.8, 0.52];
        const OPAC = [1, 0.95, 0.5];
        for (let d = 2; d >= 1; d--) {
          const k = wi - d;
          if (k >= 0) slots.push(slot(li, k, W[k], 'past', { s: SCALE[d], o: OPAC[d], italic: d === 2, z: -40 * d }));
        }
        slots.push(slot(li, wi, W[wi], 'active', { s: Math.min(SCALE[0], fit(W[wi].text, 0.5, SCALE[0])), r: -1.5, z: 30 }));
        for (let d = 1; d <= 2; d++) {
          const k = wi + d;
          if (k < W.length && (d === 1 || prog > 0.4)) {
            slots.push(slot(li, k, W[k], 'ghost', { s: SCALE[d] * 0.92, o: d === 1 ? 0.75 : 0.4, z: -40 * d }));
          }
        }
        return stackAroundActive(slots, 0.02);
      }

      case 'INKBLOT':
      case 'SQUEEZE': {
        const s = fit(W[wi].text, 0.7, 2.0);
        slots.push(slot(li, wi, W[wi], 'active', { s, y: area.centre, wpx: emWidth(W[wi].text) * unit * s }));
        return slots;
      }

      case 'REMOLD':
        return [];

      case 'POP': {
        // one word at a time, big, springing in
        slots.push(slot(li, wi, W[wi], 'active', { s: fit(W[wi].text, 0.7, 2.1), y: area.centre }));
        return slots;
      }

      case 'STAMP': {
        // each word slams onto the centre; earlier words of the line stay scattered around it
        const rx = Math.min(innerWidth * 0.36, unit * 4.2);
        const ry = (area.bottom - area.top) * 0.36;
        for (let k = Math.max(0, wi - 7); k < wi; k++) {
          const ang = k * 2.39996 + li * 0.7;          // golden angle spreads them evenly
          const rad = 0.72 + 0.28 * hash01(li * 97 + k);
          slots.push(slot(li, k, W[k], 'past', {
            s: Math.min(0.5, fit(W[k].text, 0.28, 0.5)),
            x: Math.cos(ang) * rx * rad, y: area.centre + Math.sin(ang) * ry * rad,
            r: (hash01(li * 31 + k) - 0.5) * 30, o: 0.42,
          }));
        }
        slots.push(slot(li, wi, W[wi], 'active', {
          s: fit(W[wi].text, 0.6, 1.5), y: area.centre, r: (hash01(li * 13 + wi) - 0.5) * 10,
        }));
        return slots;
      }

      case 'LINE': {
        // the whole line; the slab wipes across each word while it is sung
        const maxRow = innerWidth * 0.84;
        const longest = W.reduce((m, w) => Math.max(m, emWidth(w.text)), 0);
        const s = Math.min(0.62, Math.max(0.36, maxRow / (unit * Math.max(4, longest * 3))));
        const space = unit * s * 0.32;
        const rows = [[]];
        let rowW = 0;
        W.forEach((w, k) => {
          const wpx = emWidth(w.text) * unit * s;
          if (rowW > 0 && rowW + space + wpx > maxRow) { rows.push([]); rowW = 0; }
          rows[rows.length - 1].push({ k, wpx });
          rowW += (rowW > 0 ? space : 0) + wpx;
        });
        const lineH = unit * s * 1.22;
        const activeRow = rows.findIndex(r => r.some(c => c.k === wi));
        rows.forEach((row, ri) => {
          const total = row.reduce((sum, c) => sum + c.wpx, 0) + space * (row.length - 1);
          let x = -total / 2;
          row.forEach(c => {
            const role = c.k < wi ? 'past' : c.k === wi ? 'active' : 'ghost';
            slots.push(slot(li, c.k, W[c.k], role, {
              s, x: x + c.wpx / 2, y: area.centre + (ri - activeRow) * lineH,
              o: role === 'ghost' ? 0.6 : 1, wipe: role === 'active' ? wordSpan(c.k) : 0,
            }));
            x += c.wpx + space;
          });
        });
        return slots;
      }

      case 'ORBIT': {
        // the line rides a carousel that turns to bring the sung word to the front
        const R = Math.min(innerWidth * 0.34, unit * 3.6);
        const step = 0.5;
        W.forEach((w, k) => {
          const th = (k - wi) * step;
          if (Math.abs(th) > 1.45) return;
          const c = Math.cos(th);
          const role = k < wi ? 'past' : k === wi ? 'active' : 'ghost';
          slots.push(slot(li, k, w, role, {
            s: role === 'active' ? fit(w.text, 0.5, 1.15) : Math.min(0.8, fit(w.text, 0.35, 0.8)),
            x: Math.sin(th) * R, z: (c - 1) * R, y: area.centre,
            o: role === 'active' ? 1 : c * c * 0.85,
          }));
        });
        return slots;
      }

      default: {
        // VISUAL: the two words before the sung word gather above it, the next one waits below
        if (wi >= 2) slots.push(slot(li, wi - 2, W[wi - 2], 'past', { s: Math.min(0.72, fit(W[wi - 2].text, 0.4, 0.72)), italic: true, r: -2.5 }));
        if (wi >= 1) slots.push(slot(li, wi - 1, W[wi - 1], 'past', { s: fit(W[wi - 1].text, 0.6, 1.35) }));
        slots.push(slot(li, wi, W[wi], 'active', { s: Math.min(0.95, fit(W[wi].text, 0.5, 0.95)), r: -2 }));
        if (showGhost) slots.push(slot(li, wi + 1, W[wi + 1], 'ghost', { s: 0.62, o: 0.45 }));
        return stackAroundActive(slots, 0.04);
      }
    }
  }

  // How a word arrives and departs, per style
  function enterState(sl) {
    if (reduceMotion()) return { o: 0 };
    const m = cfg.motion ?? 1;
    const R = Math.min(innerWidth * 0.34, unit * 3.6) * m;
    switch (style) {
      case 'POP':   return { s: sl.s * 0.35, o: 0 };
      case 'INKBLOT': return { s: sl.s * 0.9, o: 0 };
      case 'SQUEEZE': return { sx: 0.001, x: sl.x + (sl.wpx || 0) / 2, o: 1 };
      case 'STAMP': return { s: sl.s * 2.6, o: 0, r: sl.r + 18 };
      case 'LINE':  return { y: sl.y + unit * 0.3, o: 0 };
      case 'ORBIT': return { x: sl.x + R * 0.9, z: -R, o: 0 };
      default:      return { y: sl.y + unit * 0.55 * m, s: sl.s * (1 - 0.1 * m), o: 0 };
    }
  }

  function leaveState(el) {
    const num = v => parseFloat(el.style.getPropertyValue(v)) || 0;
    if (reduceMotion()) return {};
    const m = cfg.motion ?? 1;
    const R = Math.min(innerWidth * 0.34, unit * 3.6);
    switch (style) {
      case 'POP':   return { '--s': num('--s') * 1.5 };
      case 'INKBLOT': return { '--s': num('--s') * 1.06 };
      case 'SQUEEZE': return { '--sx': 0.001, '--x': (num('--x') - (parseFloat(el.dataset.w) || 0) / 2) + 'px' };
      case 'STAMP': return { '--s': num('--s') * 0.8 };
      case 'LINE':  return { '--y': (num('--y') - unit * 0.4) + 'px' };
      case 'ORBIT': return { '--x': (num('--x') - R * 0.9) + 'px', '--z': -R + 'px' };
      default:      return { '--y': (num('--y') - unit * 0.9 * m) + 'px' };
    }
  }

  // ---------- Goo (ink / clay) blur, only while a morph is happening ----------
  let gooRaf = 0;
  function startGoo(peakPx, ms) {
    const blur = document.getElementById('gooBlur');
    if (!blur || reduceMotion() || body.classList.contains('lowpower')) return;
    cancelAnimationFrame(gooRaf);
    body.classList.add('morphing');
    const t0 = performance.now();
    const step = () => {
      const p = (performance.now() - t0) / ms;
      if (p >= 1) {
        blur.setAttribute('stdDeviation', '0');
        body.classList.remove('morphing');   // crisp text and no filter cost at rest
        return;
      }
      blur.setAttribute('stdDeviation', (peakPx * Math.sin(Math.PI * p)).toFixed(2));
      gooRaf = requestAnimationFrame(step);
    };
    gooRaf = requestAnimationFrame(step);
  }

  // ---------- Remold: the old word's letters rearrange into the new word ----------
  const remold = { el: null, slab: null, txt: null, letters: [], key: '' };
  const rawCache = new Map();
  function rawEm(text) {            // unclamped width in em at the remold weight
    let w = rawCache.get(text);
    if (w === undefined) {
      measureCtx.font = `800 100px ${FONT_FAMILY}`;
      w = measureCtx.measureText(text).width / 100;
      rawCache.set(text, w);
    }
    return w;
  }

  function layoutLetters(text) {
    const track = -0.035;                       // matches the CSS letter-spacing
    const total = rawEm(text) + track * Math.max(0, text.length - 1);
    const xs = [];
    for (let j = 0; j < text.length; j++) {
      const left = rawEm(text.slice(0, j)) + track * j;
      xs.push(left + rawEm(text[j]) / 2 - total / 2);
    }
    return { xs, total };
  }

  function setLetter(el, x, scale, blurEm, opacity) {
    el.style.setProperty('--lx', x + 'em');
    el.style.setProperty('--ls', scale);
    el.style.setProperty('--lb', blurEm + 'em');
    el.style.opacity = opacity;
  }

  function clearRemold() {
    if (!remold.el) return;
    const el = remold.el;
    el.style.opacity = 0;
    setTimeout(() => el.remove(), 400);
    Object.assign(remold, { el: null, slab: null, txt: null, letters: [], key: '' });
  }

  function renderRemold(loc) {
    if (loc.kind !== 'word') { clearRemold(); return false; }
    if (!remold.el) {
      const el = document.createElement('div'); el.className = 'rm';
      const slab = document.createElement('div'); slab.className = 'rm-slab';
      const txt = document.createElement('div'); txt.className = 'rm-txt';
      el.append(slab, txt);
      stack.appendChild(el);
      Object.assign(remold, { el, slab, txt, letters: [], key: '' });
    }
    const key = loc.li + ':' + loc.wi;
    if (remold.key === key) return true;
    const first = !remold.key;
    remold.key = key;

    const text = caps(loc.words[loc.wi].text);
    const area = safeArea();
    const maxW = maxWordWidth();
    const s = Math.max(0.7, Math.min(2.0, maxW / (Math.max(rawEm(text), 0.6) * unit)));
    remold.el.style.fontSize = (unit * s) + 'px';
    remold.el.style.setProperty('--y', area.centre + 'px');

    const { xs, total } = layoutLetters(text);
    remold.slab.style.width = (total + 0.16) + 'em';

    // match each new letter to the closest unused old letter with the same character
    const old = remold.letters, n = old.length, m = text.length;
    const used = new Array(n).fill(false);
    const next = [];
    for (let j = 0; j < m; j++) {
      const ch = text[j];
      const pj = m > 1 ? j / (m - 1) : 0.5;
      let best = -1, bestD = 1e9;
      for (let i = 0; i < n; i++) {
        if (used[i] || old[i].ch.toLowerCase() !== ch.toLowerCase()) continue;
        const d = Math.abs((n > 1 ? i / (n - 1) : 0.5) - pj);
        if (d < bestD) { bestD = d; best = i; }
      }
      if (best >= 0 && bestD < 0.5) {
        used[best] = true;                      // same letter: slide it to its new spot
        const L = old[best];
        L.ch = ch; L.el.textContent = ch; L.x = xs[j];
        setLetter(L.el, xs[j], 1, 0, 1);
        next.push(L);
      } else {
        // new letter: sprout out of the nearest old letter
        const el = document.createElement('span');
        el.className = 'rm-l';
        el.textContent = ch;
        const fromX = n ? old[Math.round(pj * (n - 1))].x : xs[j];
        setLetter(el, fromX, first ? 1 : 0.2, first ? 0 : 0.06, 0);
        el.style.transition = 'none';
        remold.txt.appendChild(el);
        void el.offsetWidth;
        el.style.transition = '';
        setLetter(el, xs[j], 1, 0, 1);
        next.push({ ch, el, x: xs[j] });
      }
    }
    // leftover old letters melt into the nearest new position
    old.forEach((L, i) => {
      if (used[i]) return;
      const j = Math.round((n > 1 ? i / (n - 1) : 0.5) * Math.max(0, m - 1));
      setLetter(L.el, xs[Math.max(0, Math.min(m - 1, j))] || 0, 0.2, 0.06, 0);
      setTimeout(() => L.el.remove(), 520);
    });
    remold.letters = next;
    // no full-word blur here: only the sprouting / melting letters soften, so text stays readable
    return true;
  }

  // ---------- Keyed DOM reconciliation ----------
  const live = new Map(); // key -> element

  function makeWord(sl) {
    const el = document.createElement('div');
    el.className = 'w';
    const t = document.createElement('span');
    t.className = 't';
    t.textContent = sl.text;
    el.appendChild(t);
    if (sl.icon) {
      const ic = document.createElement('span');
      ic.className = 'ic';
      ic.textContent = sl.icon;
      el.appendChild(ic);
    }
    return el;
  }

  function place(el, sl) {
    el.style.setProperty('--x', sl.x + 'px');
    el.style.setProperty('--y', sl.y + 'px');
    el.style.setProperty('--z', (sl.z || 0) + 'px');
    el.style.setProperty('--s', sl.s);
    el.style.setProperty('--r', sl.r + 'deg');
    el.style.setProperty('--o', sl.o);
    el.style.setProperty('--wipe', (sl.wipe || 0.2) + 's');
    el.style.setProperty('--sx', sl.sx == null ? 1 : sl.sx);
    if (sl.wpx) el.dataset.w = sl.wpx;
    el.classList.toggle('active', sl.role === 'active');
    el.classList.toggle('past', sl.role === 'past');
    el.classList.toggle('ghost', sl.role === 'ghost');
    el.classList.toggle('italic', !!sl.italic);
  }

  let lastActiveKey = '';
  function render(slots) {
    const keep = new Set(slots.map(s => s.key));
    const activeSlot = slots.find(s => s.role === 'active');
    const activeKey = activeSlot ? activeSlot.key : '';
    if (style === 'INKBLOT' && activeKey && lastActiveKey && activeKey !== lastActiveKey) startGoo(unit * 0.07, 620);
    lastActiveKey = activeKey;

    live.forEach((el, key) => {
      if (keep.has(key)) return;
      live.delete(key);
      el.classList.add('leaving');
      Object.entries(leaveState(el)).forEach(([k, v]) => el.style.setProperty(k, v));
      el.style.setProperty('--o', 0);
      setTimeout(() => el.remove(), 460);
    });

    slots.forEach(sl => {
      let el = live.get(sl.key);
      if (!el) {
        el = makeWord(sl);
        // enter from just below its slot
        place(el, Object.assign({}, sl, enterState(sl), { role: sl.role === 'active' ? 'ghost' : sl.role }));
        el.style.transition = 'none';
        stack.appendChild(el);
        void el.offsetWidth;
        el.style.transition = '';
        live.set(sl.key, el);
      }
      place(el, sl);
    });
  }

  function update(pos) {
    const loc = locate(pos);
    if (cfg.shuffle === 'line' && loc.kind === 'word' && loc.li !== lastShuffleLine) {
      if (lastShuffleLine !== -1) pickShuffle();
      lastShuffleLine = loc.li;
    }
    const key = loc.kind === 'status' ? `status|${loc.text}` : loc.kind === 'word'
      ? `${loc.li}|${loc.wi}|${loc.prog > 0.55 ? 1 : 0}|${loc.prog > 0.4 ? 1 : 0}`
      : loc.kind === 'gap' ? `gap|${loc.nextIdx}|${loc.until <= 1.4 ? 1 : 0}` : `none|${track && track.title}`;
    const full = key + '|' + style + '|' + unit;
    if (full === layoutKey) return;
    layoutKey = full;
    const slots = layoutFor(loc);
    const remoldShown = style === 'REMOLD' ? renderRemold(loc) : (clearRemold(), false);
    body.classList.toggle('has-words', (slots.length > 0 || remoldShown) && loc.kind !== 'none');
    render(slots);
  }

  // ---------- Frame timing (reported to Python for diagnostics) ----------
  let perfLast = 0, perfStart = 0, perfFrames = 0, perfLong = 0, perfWorst = 0, perfOverflow = -1e9, perfCentreOff = 0;
  function perfSample() {
    const now = performance.now();
    if (perfLast) {
      const dt = now - perfLast;
      perfFrames++;
      if (dt > 25) perfLong++;
      if (dt > perfWorst) perfWorst = dt;
    } else perfStart = now;
    perfLast = now;
    // every 15th frame: how far does any settled, visible word stick out of the safe area?
    if (perfFrames % 15 === 0) {
      const { top, bottom, centre } = safeArea();
      const cy = innerHeight / 2;
      if (remold.el && remold.txt.children.length && remold.letters.length) {
        // Remold draws loose letters: measure the settled word as a whole
        const rs = remold.letters.map(L => L.el.getBoundingClientRect());
        const settled = remold.letters.every(L => L.el.getAnimations().length === 0);
        const t = Math.min(...rs.map(r => r.top)), b = Math.max(...rs.map(r => r.bottom));
        perfOverflow = Math.max(perfOverflow, b - (cy + bottom), (cy + top) - t);
        if (settled) perfCentreOff = Math.max(perfCentreOff, Math.abs((t + b) / 2 - (cy + centre)));
      }
      stack.querySelectorAll('.w:not(.leaving)').forEach(el => {
        if (parseFloat(getComputedStyle(el).opacity) < 0.3) return;
        const r = el.getBoundingClientRect();
        perfOverflow = Math.max(perfOverflow, r.bottom - (cy + bottom), (cy + top) - r.top);
        if (el.classList.contains('active') && el.getAnimations().length === 0) {  // settled, not mid-glide
          perfCentreOff = Math.max(perfCentreOff, Math.abs((r.top + r.bottom) / 2 - (cy + centre)));
        }
      });
    }
    if (now - perfStart > 10000) {
      call('report_perf', { fps: Math.round(perfFrames / ((now - perfStart) / 1000)), long_frames: perfLong, worst_ms: Math.round(perfWorst), overflow_px: Math.round(perfOverflow), centre_off_px: Math.round(perfCentreOff), style, words: stack.querySelectorAll('.w').length });
      perfStart = now; perfFrames = 0; perfLong = 0; perfWorst = 0; perfOverflow = -1e9; perfCentreOff = 0;
    }
  }

  // ---------- Frame loop ----------
  // Draw every frame only while something can change; otherwise check 4x a second.
  // (A paused song with a still word on screen used ~13% of a core before this.)
  function needsFrames() {
    if (cfg.hidden) return false;
    if (playing || standalone) return true;
    if (body.classList.contains('controls-revealed') || body.classList.contains('morphing') || body.classList.contains('drop')) return true;
    // a word still gliding into place, a fade still running (the endless Ship drift doesn't count)
    return document.getAnimations().some(a => a.playState === 'running' && a.effect && a.effect.getTiming().iterations !== Infinity);
  }
  // An error in one frame must never stop the animation for good: log it (rarely) and carry on.
  let lastErrorAt = 0;
  function reportError(msg) {
    const now = performance.now();
    if (now - lastErrorAt < 5000) return;
    lastErrorAt = now;
    call('report_error', 'lyrics: ' + msg);
  }
  addEventListener('error', e => reportError(e.message));
  addEventListener('unhandledrejection', e => reportError(String(e.reason)));
  function tick() {
    let busy = true;
    try {
      busy = frame();
    } catch (e) {
      reportError((e && e.stack) || String(e));
    } finally {
      if (busy) requestAnimationFrame(tick);
      else setTimeout(() => requestAnimationFrame(tick), 250);
    }
  }
  function frame() {
    let pos = basePos + (playing ? (performance.now() - baseTime) / 1000 : 0) + offsetMs / 1000;
    if (standalone && duration && pos > duration) { basePos = 0; baseTime = performance.now(); pos = 0; }
    if (duration > 0) pos = Math.min(pos, duration);
    // never tick backwards on tiny corrections (that is what makes words flicker)
    if (playing && pos < lastPos && lastPos - pos < 0.6) pos = lastPos;
    lastPos = pos;
    if (duration > 0 && body.classList.contains('controls-revealed')) {
      progressFill.style.width = Math.max(0, Math.min(100, (pos / duration) * 100)) + '%';
    }
    if (!cfg.hidden) { update(pos); beatFrame(performance.now()); }
    perfSample();
    const busy = needsFrames();
    body.classList.toggle('idle', !busy);
    return busy;
  }

  // ---------- Screensaver: any real input ends it ----------
  let ssStart = null;
  addEventListener('mousemove', e => {
    if (!cfg.screensaver) return;
    if (!ssStart) { ssStart = [e.screenX, e.screenY]; return; }
    if (Math.hypot(e.screenX - ssStart[0], e.screenY - ssStart[1]) > 12) call('exit_screensaver');
  });
  ['keydown', 'mousedown', 'wheel', 'touchstart'].forEach(ev => addEventListener(ev, () => { if (cfg.screensaver) call('exit_screensaver'); }));

  // ---------- Controls ----------
  segs.forEach(b => b.addEventListener('click', () => setStyle(b.dataset.style)));
  btnPin.addEventListener('click', () => setPin(!alwaysOnTop));
  btnMode.addEventListener('click', () => setMode(MODES[(MODES.indexOf(mode) + 1) % MODES.length]));
  btnDemo.addEventListener('click', () => { setDemo(!demoMode); call('toggle_mock_mode', demoMode); });

  progressBarWrap.addEventListener('click', e => {
    if (!duration) return;
    const r = progressBarWrap.getBoundingClientRect();
    basePos = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * duration;
    baseTime = performance.now();
    call('seek', basePos);
  });

  addEventListener('keydown', e => {
    const k = e.key;
    if (k === '1') setStyle('SHIP');
    else if (k === '2') setStyle('FISHEYE');
    else if (k === '3') setStyle('FISHEYE_VISUAL');
    else if (k === '4') setStyle('VISUAL');
    else if (k === '5') setStyle('POP');
    else if (k === '6') setStyle('STAMP');
    else if (k === '7') setStyle('LINE');
    else if (k === '8') setStyle('ORBIT');
    else if (k === '9') setStyle('INKBLOT');
    else if (k === '0') setStyle('SQUEEZE');
    else if (k === '-') setStyle('REMOLD');
    else if (k === 'F11' || k === 'Tab') { e.preventDefault(); btnMode.click(); }
    else if (k === 't' || k === 'T') btnPin.click();
    else if (k === 'd' || k === 'D') btnDemo.click();
    else if (e.code === 'Space') {
      e.preventDefault();
      basePos += playing ? (performance.now() - baseTime) / 1000 : 0;
      baseTime = performance.now();
      playing = !playing;
      call('toggle_playback');
    }
    else if (k === 'ArrowRight' || k === 'n' || k === 'N') call('next_track');
    else if (k === 'ArrowLeft' || k === 'p' || k === 'P') call('prev_track');
  });

  // ---------- Standalone browser preview (no Python backend) ----------
  // (preview lyrics live in util.js)
  setStyle('SHIP', false);
  computeUnit();
  requestAnimationFrame(tick);

  setTimeout(() => {
    if (api()) return;
    standalone = true;
    const prev = buildPreviewLyrics();
    applyTrack({ title: 'Preview', artist: 'WordPulse', duration: prev.duration, position: 0, status: 'PLAYING' });
    lyrics = { lines: prev.lines };
    layoutKey = '';
  }, 500);
})();
