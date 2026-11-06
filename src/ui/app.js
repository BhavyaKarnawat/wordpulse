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
  const drift = document.getElementById('drift');
  const trackTitle = document.getElementById('trackTitle');
  const trackArtist = document.getElementById('trackArtist');
  const albumArt = document.getElementById('albumArt');
  const progressFill = document.getElementById('progressFill');
  const progressBarWrap = document.getElementById('progressBarWrap');
  const segs = document.querySelectorAll('.seg');            // (older builds had one button per style)
  const styleSelect = document.getElementById('styleSelect');
  const fsArt = document.getElementById('fsArt');
  const pArt = document.getElementById('pArt');
  const player = document.getElementById('player');
  const btnPin = document.getElementById('btnPinToggle');
  const btnMode = document.getElementById('btnModeToggle');
  const btnDemo = document.getElementById('btnDemoToggle');
  const demoBadge = document.getElementById('demoBadge');

  const { moodColor, hueShift, chorusLines, buildPreviewLyrics } = window.WVUtil;   // util.js
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
    CONSTELLATION: 'style-constellation', BRANCHES: 'style-branches', WEB: 'style-web',
    CODE: 'style-code', CODE_VISUAL: 'style-code style-code-visual',
  };

  function setStyle(s, notify = true) {
    if (!STYLE_CLASS[s]) s = 'SHIP';
    style = s;
    // a style may use more than one class (Code Visual = the Code look + icons)
    Object.values(STYLE_CLASS).forEach(c => body.classList.remove(...c.split(' ')));
    body.classList.add(...STYLE_CLASS[s].split(' '));
    segs.forEach(b => b.classList.toggle('active', b.dataset.style === s));
    if (styleSelect && styleSelect.value !== s) styleSelect.value = s;
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
      const tuned = activeMood() ? moodColor(base, activeMood()) : base;
      root.setProperty('--hl', variant && variant.hue ? hueShift(tuned, variant.hue) : tuned);
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
    setLayout(s.fullscreen_layout || 'lyrics');
    applyArt();
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
    const moodStyle = mood && (s.shuffle || 'off') === 'off' && s.mood_styles ? moodStyleFor(mood) : '';
    if (moodStyle && STYLE_CLASS[moodStyle]) {
      if (style !== moodStyle) setStyle(moodStyle, false);
    } else if ((s.shuffle || 'off') === 'off' || s.display_style !== prev.display_style || s.shuffle !== prev.shuffle
               || (prev.mood && !mood)) {
      setStyle(baseStyle, false);
    }
    applyPalette();
    computeUnit();
  }

  // ---------- Variety: per-song randomness so a session doesn't repeat itself ----------
  let variant = null;
  const recentStyles = [];
  let moodPick = { key: '', style: '', chorus: '' };
  let chorus = new Set();
  const rnd = (a, b) => a + Math.random() * (b - a);
  const pick = arr => arr[Math.floor(Math.random() * arr.length)];

  function makeVariant() {
    const level = cfg.variety || 'subtle';
    if (level === 'off') return { level, tilt: 0, hue: 0, weight: 800, spacing: 0, motion: 1, enter: [0, 1], dir: 1, drift: 0, scatter: 1 };
    const lively = level === 'lively';
    return {
      level,
      tilt: rnd(-1, 1) * (lively ? 3.5 : 1.8),                       // slab tilt, degrees
      hue: rnd(-1, 1) * (lively ? 22 : 10),                          // colour shift, degrees of hue
      weight: pick(lively ? [700, 800, 900] : [800, 800, 900]),
      spacing: rnd(-0.015, lively ? 0.02 : 0.01),                    // extra letter spacing, em
      motion: rnd(lively ? 0.75 : 0.88, lively ? 1.3 : 1.12),         // how far / fast words travel
      enter: lively ? pick([[0, 1], [0, -1], [1, 0], [-1, 0]]) : pick([[0, 1], [0, 1], [0, -1]]),
      dir: Math.random() < 0.5 ? 1 : -1,                             // Orbit turn / Squeeze push direction
      drift: Math.floor(Math.random() * 3),                          // which Ship drift path
      scatter: rnd(0.7, lively ? 1.5 : 1.15),                        // how wildly Stamp scatters
    };
  }
  function applyVariant() {
    const st = body.style;
    st.setProperty('--v-tilt', (variant ? variant.tilt : 0).toFixed(2) + 'deg');
    st.setProperty('--v-weight', variant ? variant.weight : 800);
    st.setProperty('--v-spacing', (variant ? variant.spacing : 0).toFixed(3) + 'em');
    body.dataset.drift = variant ? variant.drift : 0;
    applyPalette();
  }
  function poolFor(mood) {
    const p = (cfg.mood_styles || {})[mood];
    return (Array.isArray(p) ? p : [p]).filter(x => STYLE_CLASS[x]);
  }
  // one style per song (and mood) from the mood's pool, avoiding the last few used
  function moodStyleFor(mood) {
    const key = currentTrackId + '|' + mood + '|' + (cfg.variety || '');
    if (moodPick.key !== key) {
      const pool = poolFor(mood);
      let first = '';
      if (pool.length && (cfg.variety || 'subtle') === 'off') first = pool[0];
      else if (pool.length) {
        const fresh = pool.filter(x => !recentStyles.includes(x));
        first = pick(fresh.length ? fresh : pool);
      }
      const others = pool.filter(x => x !== first);
      const freshOthers = others.filter(x => !recentStyles.includes(x));
      moodPick = { key, style: first, chorus: freshOthers.length ? pick(freshOthers) : others.length ? pick(others) : first };
      if (first) {
        recentStyles.push(first);
        while (recentStyles.length > Math.min(3, Math.max(1, pool.length - 1))) recentStyles.shift();
      }
    }
    return moodPick.style;
  }
  // Lively: the chorus gets its own style from the pool so verse and chorus feel different
  function chorusSwitch(loc) {
    if ((cfg.variety || 'subtle') !== 'lively' || !activeMood() || (cfg.shuffle || 'off') !== 'off' || loc.kind !== 'word') return;
    moodStyleFor(activeMood());
    const want = chorus.has(loc.li) ? moodPick.chorus : moodPick.style;
    if (want && STYLE_CLASS[want] && want !== style) setStyle(want, false);
  }

  // ---------- Fullscreen views: lyrics / player card / cover filling the screen ----------
  let layout = 'lyrics';
  function setLayout(next, animate) {
    if (next === layout) return;
    const from = layout;
    layout = next;
    // the card's cover grows to fill the screen when you go from the player to the album-art view
    if (animate && from === 'player' && next === 'art' && body.classList.contains('mode-fullscreen') && !reduceMotion()) {
      const r = pArt.getBoundingClientRect();
      fsArt.style.transition = 'none';
      Object.assign(fsArt.style, { left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px', borderRadius: '18px' });
      void fsArt.offsetWidth;
      fsArt.style.transition = '';
      requestAnimationFrame(() => Object.assign(fsArt.style, { left: '0px', top: '0px', width: '100vw', height: '100vh', borderRadius: '0px' }));
    } else {
      Object.assign(fsArt.style, { left: '', top: '', width: '', height: '', borderRadius: '' });
    }
    body.dataset.layout = next;
    layoutKey = '';
  }
  function cycleLayout() {
    const order = ['lyrics', 'player', 'art'];
    const next = order[(order.indexOf(layout) + 1) % order.length];
    setLayout(next, true);
    call('set_setting', 'fullscreen_layout', next);
  }
  function applyArt() {
    const sharp = cfg.art_hd || '';
    const thumb = track && track.thumbnail_base64 && track.thumbnail_base64.length > 20 ? track.thumbnail_base64 : '';
    const src = sharp || thumb;
    for (const img of [fsArt, pArt]) {
      if (src && img.dataset.src !== src) { img.dataset.src = src; img.src = src; }
      if (!src) { img.removeAttribute('src'); img.dataset.src = ''; }
    }
    body.classList.toggle('art-soft', !sharp);    // only a small thumbnail: soften it when it's full screen
  }
  document.querySelectorAll('[data-cmd]').forEach(b => b.addEventListener('click', () => {
    if (b.dataset.cmd === 'toggle_playback') {
      basePos += playing ? (performance.now() - baseTime) / 1000 : 0;
      baseTime = performance.now();
      playing = !playing;
      body.classList.toggle('is-playing', playing);
    }
    call(b.dataset.cmd);
  }));
  document.getElementById('pLyrics').addEventListener('click', () => { setLayout('art', true); call('set_setting', 'fullscreen_layout', 'art'); });
  document.getElementById('btnLayout').addEventListener('click', cycleLayout);
  document.getElementById('btnSettings').addEventListener('click', () => call('open_settings'));
  if (styleSelect) {
    styleSelect.innerHTML = Object.keys(STYLE_CLASS).map(k => `<option value="${k}">${k.charAt(0) + k.slice(1).toLowerCase().replace('_', ' ')}</option>`).join('');
    styleSelect.addEventListener('change', () => setStyle(styleSelect.value));
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
    document.getElementById('pTitle').textContent = trackTitle.textContent;
    document.getElementById('pArtist').textContent = trackArtist.textContent;
    if (t.thumbnail_base64 && t.thumbnail_base64.length > 20) albumArt.src = t.thumbnail_base64;
    else albumArt.removeAttribute('src');
    duration = t.duration || 0;
    const id = t.track_id || (t.artist + ' - ' + t.title);
    if (t.thumbnail_base64 && t.thumbnail_base64.length > 20) document.documentElement.style.setProperty('--art', `url("${t.thumbnail_base64}")`);
    else document.documentElement.style.removeProperty('--art');
    applyArt();
    if (id !== currentTrackId) {          // new song: take its position as-is
      currentTrackId = id;
      statusUntil = performance.now() + 6000;
      variant = makeVariant();
      applyVariant();
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
      chorus = lyrics && lyrics.lines ? chorusLines(lyrics.lines) : new Set();
      // if most of the song repeats there's no verse/chorus contrast to show
      if (lyrics && lyrics.lines && chorus.size > lyrics.lines.length * 0.6) chorus = new Set();
      if (cfg.variety && (!variant || variant.level !== cfg.variety)) { variant = makeVariant(); applyVariant(); }
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
        body.classList.toggle('is-playing', pb.status === 'PLAYING');
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
    if (layout === 'player' && body.classList.contains('mode-fullscreen')) return [];   // the card is the whole view
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
            r: (hash01(li * 31 + k) - 0.5) * 30 * (variant ? variant.scatter : 1), o: 0.42,
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
          const th = (k - wi) * step * (variant ? variant.dir : 1);
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

      case 'CONSTELLATION':
      case 'BRANCHES':
      case 'WEB':
        return graphLayout(loc, area);

      case 'CODE':
      case 'CODE_VISUAL':
        return codeLayout(loc, area);

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

  // ---------- Graph styles: Constellation, Branches, Web ----------
  // Positions are in "steps" (about one word apart); the view pans so the sung word stays centred.
  function graphPoints(kind, li, wi, n) {
    if (kind === 'WEB') {
      // the sung word is the hub; earlier words sit on rings around it, newest closest
      const pts = [];
      for (let k = 0; k < n; k++) {
        const back = wi - k;
        if (back <= 0) { pts.push({ x: 0, y: 0, parent: -1 }); continue; }
        const ring = Math.floor((back - 1) / 6);
        const ang = back * 2.39996 + li * 0.9;          // golden angle keeps them spread out
        const r = 1.7 + ring * 1.15;
        pts.push({ x: Math.cos(ang) * r * 1.35, y: Math.sin(ang) * r * 0.85, parent: back <= 6 ? wi : -2, ring });
      }
      return pts;
    }
    const pts = [{ x: 0, y: 0, parent: -1 }];
    let ang = hash01(li * 7 + 3) * Math.PI * 2;
    for (let k = 1; k < n; k++) {
      let parent = k - 1, len;
      if (kind === 'BRANCHES') {
        if (k >= 3 && k % 3 === 0) parent = k - 2;    // a fork every few words
        ang = -Math.PI / 2 + (k % 2 ? 0.65 : -0.65) * (0.75 + hash01(li * 29 + k) * 0.5);
        len = 1.35 + hash01(li * 41 + k) * 0.5;
      } else {
        ang += (hash01(li * 131 + k) - 0.5) * 2.4;     // a wandering path, like a star chart
        len = 1.5 + hash01(li * 17 + k) * 1.2;
      }
      pts.push({ x: pts[parent].x + Math.cos(ang) * len, y: pts[parent].y + Math.sin(ang) * len, parent });
    }
    return pts;
  }

  function lineSlot(key, a, b, o) {
    const dx = b.x - a.x, dy = b.y - a.y;
    return { key, kind: 'line', text: '', icon: '', role: 'past', x: a.x, y: a.y, s: 1, r: 0, o,
             len: Math.hypot(dx, dy), ang: Math.atan2(dy, dx) * 180 / Math.PI };
  }

  function graphLayout(loc, area) {
    const { li, words: W, wi } = loc;
    const pts = graphPoints(style, li, wi, W.length);
    const step = unit * (style === 'WEB' ? 0.95 : 0.85);
    const p0 = pts[wi];
    // centre the sung *word* (its star sits just above it): the node block is ~1.73em tall,
    // the star's centre is .35em from its top, so the word's middle is ~.52em below the star
    const lift = unit * 0.6 * 0.515;
    const P = k => ({ x: (pts[k].x - p0.x) * step, y: area.centre - lift + (pts[k].y - p0.y) * step });
    const slots = [];
    // older stars that have panned out of view fade away instead of sitting half-cut at the edge
    const halfW = innerWidth * 0.46;
    const onScreen = k => { const q = P(k); return Math.abs(q.x) < halfW && q.y > area.top + unit * 0.2 && q.y < area.bottom - unit * 0.35; };
    const fade = k => (k !== wi && !onScreen(k)) ? 0 : Math.max(0.28, 1 - (wi - k) * (style === 'WEB' ? 0.07 : 0.06));
    // lines first so the stars and words sit on top
    for (let k = 0; k <= wi; k++) {
      const p = pts[k];
      if (style === 'WEB') {
        if (k === wi) continue;
        if (p.parent === wi) slots.push(lineSlot(`${li}:sp${k}`, P(wi), P(k), 0.55 * fade(k)));
        const prev = k - 1;                                   // ring links between neighbours
        if (prev >= 0 && pts[prev].ring === p.ring && prev !== wi) slots.push(lineSlot(`${li}:rg${k}`, P(prev), P(k), 0.3 * Math.min(fade(k), fade(prev))));
      } else if (p.parent >= 0) {
        slots.push(lineSlot(`${li}:ln${k}`, P(p.parent), P(k), 0.6 * Math.min(fade(k), fade(p.parent))));
        if (style === 'CONSTELLATION' && k >= 2 && hash01(li * 53 + k) < 0.22) {
          slots.push(lineSlot(`${li}:x${k}`, P(k - 2), P(k), 0.35 * Math.min(fade(k), fade(k - 2))));   // the odd extra link
        }
      }
    }
    for (let k = 0; k <= wi; k++) {
      const q = P(k);
      const active = k === wi;
      slots.push(slot(li, k, W[k], active ? 'active' : 'past', {
        node: true, x: q.x, y: q.y, s: active ? 0.6 : 0.3, o: active ? 1 : fade(k),
      }));
    }
    return slots;
  }

  // ---------- Code styles: the line types itself out like code ----------
  const TOKEN_KINDS = ['kw', 'id', 'id', 'str', 'fn', 'id', 'num'];
  function codeLayout(loc, area) {
    const { li, words: W, wi } = loc;
    const all = (lyrics && lyrics.lines) || [];
    const first = Math.max(0, li - 3);
    const rows = [];
    for (let r = first; r <= li; r++) {
      const ws = r === li ? W : ((all[r] && all[r].words && all[r].words.length) ? all[r].words : [{ text: all[r] ? all[r].text : '' }]);
      rows.push({ idx: r, ws });
    }
    const tokText = (w, i, r) => {
      const kind = TOKEN_KINDS[Math.floor(hash01(r * 97 + i * 13) * TOKEN_KINDS.length)];
      const t = caps(w.text);
      return { kind, t: kind === 'str' ? `"${t}"` : kind === 'fn' ? `${t}()` : t };
    };
    const longest = rows.reduce((m, row) => Math.max(m, row.ws.reduce((n, w, i) => n + tokText(w, i, row.idx).t.length + 1, 0)), 10);
    const CW = 0.6;                                         // monospace character width, in em
    const s = Math.max(0.2, Math.min(0.44, (maxWordWidth() * 1.2) / (unit * CW * (longest + 6))));
    const em = unit * s;
    const lineH = em * 1.55;
    const left = -(CW * em * (longest + 6)) / 2;
    const slots = [];
    rows.forEach((row, ri) => {
      const current = row.idx === li;
      const y = area.centre + (ri - (rows.length - 1)) * lineH;
      slots.push({ key: `g${row.idx}`, kind: 'gutter', text: String(row.idx + 1).padStart(3, ' '), icon: '', role: 'past',
                   x: left, y, s, r: 0, o: current ? 0.7 : 0.35 });
      let col = 5;
      row.ws.forEach((w, i) => {
        if (current && i > wi) return;                        // not sung yet: not typed yet
        const tk = tokText(w, i, row.idx);
        const active = current && i === wi;
        slots.push(Object.assign(slot(row.idx, i, { text: tk.t, icon: '' }, active ? 'active' : 'past', {
          tok: tk.kind, x: left + col * CW * em, y, s, o: current ? 1 : 0.42,
          wipe: active ? Math.max(0.12, (W[i + 1] ? W[i + 1].start_time : (W[i].end_time || W[i].start_time + 0.5)) - W[i].start_time) : 0,
          chars: tk.t.length,
        })));
        col += tk.t.length + 1;
        if (active) {
          slots.push({ key: 'caret', kind: 'caret', text: '', icon: '', role: 'active', x: left + (col - 1) * CW * em + em * 0.08, y, s, r: 0, o: 1 });
          if (style === 'CODE_VISUAL' && w.icon) {
            slots.push({ key: `c${row.idx}:${i}`, kind: 'gutter', comment: true, text: `// ${w.icon}`, icon: '', role: 'past',
                         x: left + (col + 1) * CW * em, y, s, r: 0, o: 0.85 });
          }
        }
      });
    });
    return slots;
  }

  // How a word arrives and departs, per style
  function enterState(sl) {
    if (reduceMotion()) return { o: 0 };
    const m = (cfg.motion ?? 1) * (variant ? variant.motion : 1);
    const [ex, ey] = variant ? variant.enter : [0, 1];
    const dir = variant ? variant.dir : 1;
    const R = Math.min(innerWidth * 0.34, unit * 3.6) * m;
    if (sl.kind === 'line') return { len: 0 };                 // lines draw themselves in
    if (sl.kind === 'caret' || sl.kind === 'gutter' || sl.tok) return { o: 0 };
    if (sl.node) return { s: sl.s * 0.4, o: 0 };
    switch (style) {
      case 'POP':   return { s: sl.s * 0.35, o: 0 };
      case 'INKBLOT': return { s: sl.s * 0.9, o: 0 };
      case 'SQUEEZE': return { sx: 0.001, x: sl.x + dir * (sl.wpx || 0) / 2, o: 1 };
      case 'STAMP': return { s: sl.s * 2.6, o: 0, r: sl.r + 18 * dir };
      case 'LINE':  return { y: sl.y + unit * 0.3, o: 0 };
      case 'ORBIT': return { x: sl.x + dir * R * 0.9, z: -R, o: 0 };
      default:      return { x: sl.x + ex * unit * 0.55 * m, y: sl.y + ey * unit * 0.55 * m, s: sl.s * (1 - 0.1 * m), o: 0 };
    }
  }

  function leaveState(el) {
    const num = v => parseFloat(el.style.getPropertyValue(v)) || 0;
    if (reduceMotion()) return {};
    const m = (cfg.motion ?? 1) * (variant ? variant.motion : 1);
    const [ex, ey] = variant ? variant.enter : [0, 1];
    const dir = variant ? variant.dir : 1;
    const R = Math.min(innerWidth * 0.34, unit * 3.6);
    if (!el.classList.contains('w') || el.classList.contains('node') || el.classList.contains('tok')) return {};   // just fade
    switch (style) {
      case 'POP':   return { '--s': num('--s') * 1.5 };
      case 'INKBLOT': return { '--s': num('--s') * 1.06 };
      case 'SQUEEZE': return { '--sx': 0.001, '--x': (num('--x') - dir * (parseFloat(el.dataset.w) || 0) / 2) + 'px' };
      case 'STAMP': return { '--s': num('--s') * 0.8 };
      case 'LINE':  return { '--y': (num('--y') - unit * 0.4) + 'px' };
      case 'ORBIT': return { '--x': (num('--x') - dir * R * 0.9) + 'px', '--z': -R + 'px' };
      default:      return { '--x': (num('--x') - ex * unit * 0.9 * m) + 'px', '--y': (num('--y') - ey * unit * 0.9 * m) + 'px' };
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

  // ---------- Motion engine ----------
  // CSS transitions render at the screen's full refresh rate (144 frames a second on a 144 Hz screen)
  // for as long as anything moves, which while someone is singing is nearly always. Instead we tween
  // the layout variables ourselves at a capped rate (60 fps by default, 30 on battery) and draw nothing
  // at all while nothing moves.
  const UNITS = { x: 'px', y: 'px', z: 'px', s: '', r: 'deg', o: '', sx: '', len: 'px', ang: 'deg' };
  const moving = new Set();
  function bezier(x1, y1, x2, y2) {
    const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
    const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
    const fx = t => ((ax * t + bx) * t + cx) * t, fy = t => ((ay * t + by) * t + cy) * t;
    const dfx = t => (3 * ax * t + 2 * bx) * t + cx;
    return x => {
      if (x <= 0) return 0;
      if (x >= 1) return 1;
      let t = x;
      for (let i = 0; i < 6; i++) { const d = fx(t) - x, dd = dfx(t); if (Math.abs(d) < 1e-4 || !dd) break; t -= d / dd; }
      return fy(Math.min(1, Math.max(0, t)));
    };
  }
  const EASE = {
    glide: bezier(.22, 1, .36, 1), spring: bezier(.34, 1.56, .64, 1), slam: bezier(.2, 1.9, .45, 1),
    squeeze: bezier(.7, 0, .25, 1), hard: bezier(.6, 0, .2, 1), out: bezier(0, 0, .58, 1), in: bezier(.42, 0, 1, 1),
  };
  // [movement ms, movement easing, fade ms] per style / mood (the old CSS timings)
  function motionFor(el, leaving) {
    const mood = body.dataset.mood;
    if (el.classList.contains('caret')) return [180, EASE.glide, 180];
    if (el.classList.contains('ln')) return [550, EASE.glide, 400];
    if (mood === 'heavy') return [160, EASE.hard, 120];
    if (mood === 'neon') return [300, EASE.glide, 220];
    if (mood === 'smooth') return [780, EASE.glide, 600];
    if (mood === 'soft') return [950, EASE.glide, 800];
    switch (style) {
      case 'POP': return leaving ? [350, EASE.in, 300] : [620, EASE.spring, 220];
      case 'STAMP': return el.classList.contains('active') && !leaving ? [420, EASE.slam, 120] : [620, EASE.spring, 220];
      case 'SQUEEZE': return [460, EASE.squeeze, leaving ? 150 : 200];
      case 'LINE': return [450, EASE.glide, 300];
      case 'ORBIT': return [600, EASE.glide, 450];
      case 'INKBLOT': return [620, EASE.glide, 500];
    }
    if (mood === 'bright') return [500, EASE.spring, 300];
    return leaving ? [420, EASE.glide, 300] : [520, EASE.glide, 380];
  }
  function writeVars(el, v) {
    for (const k in v) {
      if (v[k] === undefined || !(k in UNITS)) continue;
      el.style.setProperty('--' + k, UNITS[k] ? (+v[k]).toFixed(2) + UNITS[k] : (+v[k]).toFixed(4));
    }
  }
  function setNow(el, vals) {
    el._v = Object.assign(el._v || {}, vals);
    writeVars(el, vals);
  }
  function animateTo(el, vals, leaving) {
    const cur = Object.assign({}, el._v || {});
    for (const k in vals) if (cur[k] === undefined) cur[k] = vals[k];
    let changed = false;
    for (const k in vals) if (Math.abs(cur[k] - vals[k]) > 1e-3) changed = true;
    if (!changed && !el._tw) { setNow(el, vals); return 0; }
    const [dur, ease, odur] = motionFor(el, leaving);
    if (reduceMotion()) {
      // calmer: positions snap, only the fade animates
      const snap = Object.assign({}, vals); delete snap.o;
      setNow(el, snap);
      el._tw = { from: cur, to: Object.assign({}, cur, snap, { o: vals.o ?? cur.o }), t0: performance.now(), dur: 1, ease: EASE.out, odur: 250 };
    } else {
      el._tw = { from: cur, to: Object.assign({}, cur, vals), t0: performance.now(), dur, ease, odur };
    }
    el.classList.add('mv');                  // own graphics layer only while it moves
    moving.add(el);
    return Math.max(dur, odur);
  }
  function stepMotion(now) {
    moving.forEach(el => {
      const tw = el._tw;
      if (!tw || !el.isConnected) { moving.delete(el); el.classList.remove('mv'); return; }
      const p = Math.min(1, (now - tw.t0) / tw.dur), po = Math.min(1, (now - tw.t0) / tw.odur);
      const e = tw.ease(p), eo = EASE.out(po);
      const v = {};
      for (const k in tw.to) {
        const a = tw.from[k], b = tw.to[k];
        v[k] = a === undefined ? b : a + (b - a) * (k === 'o' ? eo : e);
      }
      el._v = v;
      writeVars(el, v);
      if (p >= 1 && po >= 1) { el._tw = null; moving.delete(el); el.classList.remove('mv'); }
    });
  }
  function slotVals(sl) {
    const v = { x: sl.x || 0, y: sl.y || 0, z: sl.z || 0, s: sl.s, r: sl.r || 0, o: sl.o, sx: sl.sx == null ? 1 : sl.sx };
    if (sl.len != null) { v.len = sl.len; v.ang = sl.ang; }
    return v;
  }
  function cssToNums(obj) {           // leaveState speaks CSS ("--y": "120px"); the engine wants numbers
    const out = {};
    for (const k in obj) out[k.replace(/^--/, '')] = parseFloat(obj[k]);
    return out;
  }

  // Ship's slow 3D drift, computed here at 30 fps instead of a CSS animation at full refresh rate
  let lastDrift = 0;
  function driftFrame(now) {
    if (style !== 'SHIP' || reduceMotion() || body.classList.contains('lowpower')) {
      if (lastDrift) { drift.style.transform = ''; lastDrift = 0; }
      return false;
    }
    if (now - lastDrift < 33) return true;
    lastDrift = now;
    const m = (cfg.motion ?? 1) * (variant ? variant.motion : 1);
    const k = variant ? variant.drift : 0;
    const t = now / 1000;
    const speeds = [[0.17, 0.11], [0.13, 0.09], [0.21, 0.15]][k] || [0.17, 0.11];
    const rx = Math.sin(t * speeds[0] * 2 * Math.PI / 3) * 13 * m;
    const ry = Math.sin(t * speeds[1] * 2 * Math.PI / 3 + k) * 19 * m;
    const rz = Math.sin(t * 0.05 * 2 * Math.PI + k * 2) * 2.5 * m;
    const tz = -30 - 25 * Math.sin(t * 0.07 * 2 * Math.PI);
    drift.style.transform = `rotateX(${rx.toFixed(2)}deg) rotateY(${ry.toFixed(2)}deg) rotateZ(${rz.toFixed(2)}deg) translateZ(${tz.toFixed(1)}px)`;
    return true;
  }

  // frame-rate cap: battery 30, balanced 60, smooth = the screen's own rate
  function targetFps() {
    if (cfg.screensaver) return 60;
    if (cfg.battery_saver && cfg.on_battery) return 30;
    // a window attached to the desktop costs about twice as much per frame as a normal one,
    // so Balanced draws the desktop at 30 fps and fullscreen / floating at 60
    if ((cfg.frame_rate || 'balanced') === 'balanced') return mode === 'DESKTOP_WALLPAPER' ? 30 : 60;
    return { battery: 30, smooth: 1000 }[cfg.frame_rate] || 60;
  }

  // ---------- Keyed DOM reconciliation ----------
  const live = new Map(); // key -> element

  function makeWord(sl) {
    const el = document.createElement('div');
    if (sl.kind === 'line' || sl.kind === 'caret') {          // connector lines and the code cursor
      el.className = sl.kind === 'line' ? 'ln' : 'caret';
      return el;
    }
    el.className = 'w' + (sl.node ? ' node' : '') + (sl.tok ? ' tok tok-' + sl.tok : '') +
      (sl.kind === 'gutter' ? ' tok gutter' + (sl.comment ? ' comment' : '') : '');
    if (sl.node) {
      const star = document.createElement('span');
      star.className = 'star';
      star.textContent = '\u2726';
      el.appendChild(star);
    }
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

  function place(el, sl, immediate) {
    if (immediate) setNow(el, slotVals(sl));
    else animateTo(el, slotVals(sl));
    el.style.setProperty('--wipe', (sl.wipe || 0.2) + 's');
    if (sl.chars) el.style.setProperty('--chars', sl.chars);
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
      const ms = animateTo(el, Object.assign(cssToNums(leaveState(el)), { o: 0 }), true);
      setTimeout(() => el.remove(), (ms || 0) + 40);
    });

    slots.forEach(sl => {
      let el = live.get(sl.key);
      if (!el) {
        el = makeWord(sl);
        // start from the style's entry state (below / scaled / faded...), then glide in
        place(el, Object.assign({}, sl, enterState(sl), { role: sl.role === 'active' ? 'ghost' : sl.role }), true);
        el.classList.toggle('ghost', sl.role === 'active' || sl.role === 'ghost');
        stack.appendChild(el);
        void el.offsetWidth;          // so the slab / colour change below still fades in
        live.set(sl.key, el);
      }
      place(el, sl);
    });
  }

  function update(pos) {
    const loc = locate(pos);
    chorusSwitch(loc);
    if (cfg.shuffle === 'line' && loc.kind === 'word' && loc.li !== lastShuffleLine) {
      if (lastShuffleLine !== -1) pickShuffle();
      lastShuffleLine = loc.li;
    }
    const key = loc.kind === 'status' ? `status|${loc.text}` : loc.kind === 'word'
      ? `${loc.li}|${loc.wi}|${loc.prog > 0.55 ? 1 : 0}|${loc.prog > 0.4 ? 1 : 0}`
      : loc.kind === 'gap' ? `gap|${loc.nextIdx}|${loc.until <= 1.4 ? 1 : 0}` : `none|${track && track.title}`;
    const full = key + '|' + style + '|' + unit;
    if (full === layoutKey) return loc;
    layoutKey = full;
    const slots = layoutFor(loc);
    const remoldShown = style === 'REMOLD' ? renderRemold(loc) : (clearRemold(), false);
    body.classList.toggle('has-words', (slots.length > 0 || remoldShown) && loc.kind !== 'none');
    render(slots);
    return loc;
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
      call('report_perf', { fps: Math.round(perfFrames / ((now - perfStart) / 1000)), long_frames: perfLong, worst_ms: Math.round(perfWorst), overflow_px: Math.round(perfOverflow), centre_off_px: Math.round(perfCentreOff), style, variety: variant ? `${variant.level} enter=${variant.enter} dir=${variant.dir} drift=${variant.drift} hue=${Math.round(variant.hue)}` : 'none', words: stack.querySelectorAll('.w').length });
      perfStart = now; perfFrames = 0; perfLong = 0; perfWorst = 0; perfOverflow = -1e9; perfCentreOff = 0;
    }
  }

  // ---------- Frame loop ----------
  // Draw every frame only while something can change; otherwise check 4x a second.
  // (A paused song with a still word on screen used ~13% of a core before this.)
  // How long until something needs drawing: 0 = next frame (at the capped rate), otherwise sleep.
  function nextWake(loc, pos, drifting) {
    if (cfg.hidden) return 400;
    if (moving.size || body.classList.contains('controls-revealed') || body.classList.contains('morphing') ||
        body.classList.contains('drop') || remold.el && remold.letters.some(L => L.el.getAnimations().length)) return 0;
    if (!playing && !standalone) return 250;
    if (drifting || lastBeatVar > 0 || (beat.period && cfg.auto_mood && cfg.auto_mood !== 'off' && beat.conf >= 0.2 && !reduceMotion())) return 0;
    if (loc && loc.kind === 'word' && (style === 'LINE' || style === 'CODE' || style === 'CODE_VISUAL')) return 0;   // wipe / typing
    // nothing animating: sleep until the next word (or the next point where the layout changes)
    if (loc && loc.kind === 'word') {
      const w = loc.words, i = loc.wi;
      const start = w[i].start_time, next = i + 1 < w.length ? w[i + 1].start_time : (w[i].end_time || start + 0.6);
      const span = Math.max(0.05, next - start);
      const marks = [start + span * 0.4, start + span * 0.55, next].filter(t => t > pos);
      if (marks.length) return Math.max(0, Math.min(250, (Math.min(...marks) - pos) * 1000 - 8));
    }
    return 120;
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
    let wake = 0;
    try {
      wake = frame();
    } catch (e) {
      reportError((e && e.stack) || String(e));
      wake = 100;
    } finally {
      const fps = targetFps();
      if (wake > 0) setTimeout(() => requestAnimationFrame(tick), wake);
      else if (fps >= 120) requestAnimationFrame(tick);
      else setTimeout(() => requestAnimationFrame(tick), Math.max(0, 1000 / fps - 4));
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
    const now = performance.now();
    let loc = null, drifting = false;
    if (!cfg.hidden) {
      loc = update(pos);
      stepMotion(now);
      beatFrame(now);
      drifting = (playing || standalone) && driftFrame(now);
      progressFrame(loc);
    }
    if (cfg.debug) perfSample();
    const wake = nextWake(loc, pos, drifting);
    body.classList.toggle('idle', wake > 0 && !playing);
    return wake;
  }

  // Line's wipe and Code's typing follow the song's position (instead of CSS animations)
  function progressFrame(loc) {
    if (!loc || loc.kind !== 'word') return;
    const el = live.get(loc.li + ':' + loc.wi);
    if (!el) return;
    if (style === 'LINE') el.style.setProperty('--wp', loc.prog.toFixed(3));
    else if (style === 'CODE' || style === 'CODE_VISUAL') {
      const n = Math.max(1, parseInt(el.style.getPropertyValue('--chars')) || 1);
      el.style.setProperty('--tp', (Math.ceil(loc.prog * n) / n).toFixed(3));
    }
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
    else if (k === 'l' || k === 'L') cycleLayout();
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
