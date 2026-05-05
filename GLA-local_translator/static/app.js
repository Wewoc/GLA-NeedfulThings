let config = {};
let debounceTimer = null;
let currentTranslation = '';
let isTranslating = false;

// ── Init ────────────────────────────────────────────────────────────────────

async function init() {
  config = await fetch('/config').then(r => r.json());

  // Sprach-Dropdowns befüllen
  const langs = config.languages;
  ['srcLang', 'tgtLang'].forEach(id => {
    const sel = document.getElementById(id);
    Object.entries(langs).forEach(([name, code]) => {
      const opt = document.createElement('option');
      opt.value = code;
      opt.textContent = name;
      sel.appendChild(opt);
    });
  });
  document.getElementById('srcLang').value = config.default_source_lang;
  document.getElementById('tgtLang').value = config.default_target_lang;

  // Final-Pass Buttons
  document.getElementById('deeplBtn').disabled    = !config.deepl_available;
  if (config.libretranslate_available) checkLibre();
  else document.getElementById('libreBtn').disabled = true;
  const mmBtn = document.getElementById('mymemoryBtn');
  mmBtn.disabled = !config.mymemory_available;
  if (!config.mymemory_available) mmBtn.dataset.forceDisabled = '1';
  document.getElementById('laraBtn').disabled     = !config.lara_available;
  if (config.lara_available) updateLaraUsage();
  document.getElementById('deeplStatus').textContent = config.deepl_available
    ? '⬡ DeepL available' : '⬡ DeepL not configured';

  document.getElementById('srcLang').addEventListener('change', () => { if (config.libretranslate_available) checkLibre(); });
  document.getElementById('tgtLang').addEventListener('change', () => { if (config.libretranslate_available) checkLibre(); });

  checkOllama();
  setInterval(checkOllama, 15000);
  setupInput();
}

async function checkOllama() {
  const dot    = document.getElementById('ollamaDot');
  const label  = document.getElementById('ollamaStatus');
  const sel    = document.getElementById('modelSelect');
  try {
    const s = await fetch('/ollama/status').then(r => r.json());
    if (s.online) {
      dot.className     = 'dot ok';
      label.textContent = 'Ollama online';
      const current = sel.value || config.ollama_model;
      sel.innerHTML = '';
      s.models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m;
        opt.textContent = m;
        if (m === current || m.startsWith(current.split(':')[0])) opt.selected = true;
        sel.appendChild(opt);
      });
      if (!sel.value && s.models.length) sel.value = s.models[0];
    } else {
      dot.className     = 'dot err';
      label.textContent = 'Ollama offline';
      sel.innerHTML = '<option>offline</option>';
    }
  } catch {
    dot.className     = 'dot err';
    label.textContent = 'Ollama not reachable';
  }
}

async function setModel(model) {
  if (!model) return;
  await fetch('/ollama/set_model', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model })
  });
  config.ollama_model = model;
  showToast(`Modell: ${model}`, 'ok');
}

// ── Input Handling ──────────────────────────────────────────────────────────

function setupInput() {
  const ta  = document.getElementById('srcText');
  const out = document.getElementById('tgtOutput');

  ta.addEventListener('scroll', () => {
    const ratio = ta.scrollTop / (ta.scrollHeight - ta.clientHeight || 1);
    out.scrollTop = ratio * (out.scrollHeight - out.clientHeight);
  });
  out.addEventListener('scroll', () => {
    const ratio = out.scrollTop / (out.scrollHeight - out.clientHeight || 1);
    ta.scrollTop = ratio * (ta.scrollHeight - ta.clientHeight);
  });

  ta.addEventListener('input', () => {
    updateCharCount('srcText', 'srcCount');
    const mode = document.getElementById('modeSelect').value;
    if (mode === 'debounce') {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(translateNow, (config.debounce_seconds || 1.5) * 1000);
    }
  });

  ta.addEventListener('keydown', (e) => {
    const mode = document.getElementById('modeSelect').value;
    if (mode === 'sentence' && e.key === 'Enter' && !e.shiftKey) {
      setTimeout(translateNow, 50);
    }
  });
}

function updateCharCount(taId, countId) {
  const len = document.getElementById(taId).value.length;
  document.getElementById(countId).textContent = `${len.toLocaleString('en')} chars`;
  const btn = document.getElementById('mymemoryBtn');
  if (btn && !btn.dataset.forceDisabled) {
    btn.disabled = !config.mymemory_available;
    if (len > 500) {
      btn.textContent = '★ MyMemory (chunked)';
      btn.title = 'Text will be split into 500-char chunks';
    } else {
      btn.textContent = '★ MyMemory - max. 500 characters';
      btn.title = 'Final pass via MyMemory';
    }
  }
}

// ── Translate ───────────────────────────────────────────────────────────────

const CHUNK_LIMITS = { ollama: 6000, deepl: 4900, mymemory: 480 };

async function translate(engine = 'ollama') {
  const text = document.getElementById('srcText').value.trim();
  if (!text || isTranslating) return;

  const src = document.getElementById('srcLang').value;
  const tgt = document.getElementById('tgtLang').value;
  if (src === tgt) { showToast('Source and target language are identical', 'err'); return; }

  const limit = CHUNK_LIMITS[engine];
  const needsChunking = limit && text.length > limit;

  isTranslating = true;
  const out = document.getElementById('tgtOutput');
  out.textContent = 'Translating …';
  out.className = 'output-area loading';

  try {
    if (needsChunking) {
      // Chunks vorbereiten
      const prepRes = await fetch('/translate/chunks/prepare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, engine })
      });
      const prepData = await prepRes.json();
      if (!prepRes.ok) throw new Error(prepData.detail || 'Error');

      const { chunks, total } = prepData;
      const results = [];
      let context = '';

      for (let i = 0; i < chunks.length; i++) {
        out.textContent = `Übersetze… (${i + 1} / ${total})\n\n${results.join('\n\n')}`;

        const res = await fetch('/translate/chunk', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            text: chunks[i],
            source_lang: src,
            target_lang: tgt,
            engine,
            context
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Error');

        results.push(data.translation);
        // letzter Absatz als Kontext für nächsten Chunk
        const paras = data.translation.split('\n\n');
        context = paras[paras.length - 1].slice(-300);

        out.textContent = results.join('\n\n');
      }

      currentTranslation = results.join('\n\n');

    } else {
      // Normaler Pfad — kein Chunking
      const res = await fetch('/translate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, source_lang: src, target_lang: tgt, engine })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Error');
      currentTranslation = data.translation;
    }

    out.textContent = currentTranslation;
    out.className = 'output-area';
    document.getElementById('tgtCount').textContent =
      `${currentTranslation.length.toLocaleString('en')} chars`;
    if (engine === 'lara') updateLaraUsage();
    document.getElementById('engineBadge').textContent = `via ${engine}`;

  } catch (err) {
    out.textContent = `⚠ ${err.message}`;
    out.className = 'output-area';
    showToast(err.message, 'err');
  } finally {
    isTranslating = false;
  }
}

function translateNow()   { translate('ollama'); }
function deeplFinal()     { translate('deepl'); }
function libreFinal()     { translate('libretranslate'); }
function mymemoryFinal()  { translate('mymemory'); }

async function checkLibre() {
  const src = document.getElementById('srcLang').value;
  const tgt = document.getElementById('tgtLang').value;
  const btn = document.getElementById('libreBtn');
  const statusEl = document.getElementById('libreStatus');
  const dotEl = document.getElementById('libreDot');
  const textEl = document.getElementById('libreStatusText');
  try {
    const s = await fetch(`/libretranslate/status?source=${src}&target=${tgt}`).then(r => r.json());
    if (!s.online) {
      btn.disabled = true;
      btn.textContent = '★ LibreTranslate (offline)';
      btn.title = 'LibreTranslate is not running';
      statusEl.style.display = 'none';
    } else if (!s.pair_available) {
      btn.disabled = true;
      btn.textContent = `★ LibreTranslate (${s.reason})`;
      btn.title = `Language pair not available: ${s.reason}`;
      dotEl.className = 'dot ok';
      textEl.textContent = 'LibreTranslate';
      statusEl.style.display = '';
    } else {
      btn.disabled = false;
      btn.textContent = '★ LibreTranslate';
      btn.title = 'Final pass via LibreTranslate';
      dotEl.className = 'dot ok';
      textEl.textContent = 'LibreTranslate';
      statusEl.style.display = '';
    }
  } catch {
    btn.disabled = true;
    btn.textContent = '★ LibreTranslate (offline)';
    statusEl.style.display = 'none';
  }
}

async function stopLibre() {
  try {
    const r = await fetch('/libretranslate/stop', { method: 'POST' });
    if (r.ok) {
      showToast('LibreTranslate stopped', 'ok');
      setTimeout(checkLibre, 1000);
    } else {
      const d = await r.json();
      showToast(d.detail || 'Stop failed', 'err');
    }
  } catch {
    showToast('Stop failed', 'err');
  }
}

async function updateLaraUsage() {
  try {
    const data = await fetch('/lara/usage').then(r => r.json());
    const btn = document.getElementById('laraBtn');
    const remaining = data.remaining.toLocaleString('de');
    const limit = data.limit.toLocaleString('de');
    btn.textContent = `★ Lara (${remaining} / ${limit})`;
    if (data.remaining <= 0) {
      btn.disabled = true;
      btn.title = 'Lara: Tageslimit erreicht';
    }
  } catch {}
}

function laraFinal() { translate('lara'); }

// ── Utils ───────────────────────────────────────────────────────────────────

function swapLangs() {
  const s = document.getElementById('srcLang');
  const t = document.getElementById('tgtLang');
  [s.value, t.value] = [t.value, s.value];
  if (config.libretranslate_available) checkLibre();
}

function clearAll() {
  document.getElementById('srcText').value = '';
  document.getElementById('tgtOutput').innerHTML = '<span class="placeholder-text">Translation appears here …</span>';
  currentTranslation = '';
  ['srcCount', 'tgtCount'].forEach(id =>
    document.getElementById(id).textContent = '0 chars');
}

async function exportMD() {
  const src = document.getElementById('srcText').value.trim();
  if (!src) { showToast('Kein Text zum Exportieren', 'err'); return; }
  if (!currentTranslation) { showToast('No translation yet', 'err'); return; }

  try {
    const res = await fetch('/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_text: src,
        target_text: currentTranslation,
        source_lang: document.getElementById('srcLang').value,
        target_lang: document.getElementById('tgtLang').value,
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail);
    showToast(`✓ Exportiert nach ${data.export_dir}`, 'ok');
  } catch (err) {
    showToast(err.message, 'err');
  }
}

async function openExportDir() {
  try {
    const r = await fetch('/export/open');
    if (!r.ok) {
      const d = await r.json();
      showToast(d.detail || 'Could not open folder', 'err');
    }
  } catch {
    showToast('Could not open folder', 'err');
  }
}

function showToast(msg, type = '') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = `toast show ${type}`;
  setTimeout(() => t.className = 'toast', 3000);
}

function copyTranslation() {
  if (!currentTranslation) { showToast('Keine Übersetzung vorhanden', 'err'); return; }
  navigator.clipboard.writeText(currentTranslation)
    .then(() => showToast('✓ In Zwischenablage kopiert', 'ok'))
    .catch(() => showToast('Kopieren fehlgeschlagen', 'err'));
}

init();