// ── engines.js — Engine-Status und Modell-Verwaltung ────────────────────────
//
// Besitzt: checkOllama, updateVramStatus, setModel,
//          checkLibre, stopLibre, updateLaraUsage
//
// Liest globalen State: config
// Schreibt globalen State: config.ollama_model (setModel)
// Ruft auf: showToast (ui.js), updatePipelineGray (ui.js)
//
// HTML-onchange-Abhängigkeiten:
//   setModel via onchange="setModel(this.value)" → muss global verfügbar sein

async function checkOllama() {
  const dot   = document.getElementById('ollamaDot');
  const label = document.getElementById('ollamaStatus');
  const sel   = document.getElementById('modelSelect');
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

      // S2-Dropdown mit derselben Modellliste befüllen
      ['s2ModelSelect'].forEach(id => {
        const s2sel = document.getElementById(id);
        const prev  = s2sel.value;
        s2sel.innerHTML = '<option value="">— disabled —</option>';
        s.models.forEach(m => {
          const opt = document.createElement('option');
          opt.value = m;
          opt.textContent = m;
          s2sel.appendChild(opt);
        });
        if (prev) s2sel.value = prev;
      });
      if (config.pipeline_s2_model && !document.getElementById('s2ModelSelect').value)
        document.getElementById('s2ModelSelect').value = config.pipeline_s2_model;
      updatePipelineGray();

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

async function updateVramStatus() {
  const el = document.getElementById('vramStatus');
  if (!el) return;
  try {
    const data   = await fetch('/ollama/vram').then(r => r.json());
    const used   = data.vram_used_bytes;
    const total  = data.vram_total_bytes;
    const usedGB = (used / 1073741824).toFixed(1);

    if (!data.loaded || data.loaded.length === 0) {
      el.textContent = total
        ? `GPU idle / ${(total / 1073741824).toFixed(0)} GB`
        : 'GPU idle';
      return;
    }
    const modelName = data.loaded[0].name.split(':')[0];
    el.textContent = total
      ? `VRAM: ${modelName} (${usedGB} / ${(total / 1073741824).toFixed(0)} GB)`
      : `VRAM: ${modelName} (${usedGB} GB)`;
  } catch {
    const el2 = document.getElementById('vramStatus');
    if (el2) el2.textContent = '';
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
  showToast(`Model: ${model}`, 'ok');
}

async function checkLibre() {
  const src     = document.getElementById('srcLang').value;
  const tgt     = document.getElementById('tgtLang').value;
  const btn     = document.getElementById('libreBtn');
  const statusEl = document.getElementById('libreStatus');
  const dotEl   = document.getElementById('libreDot');
  const textEl  = document.getElementById('libreStatusText');
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
    const data      = await fetch('/lara/usage').then(r => r.json());
    const btn       = document.getElementById('laraBtn');
    const remaining = data.remaining.toLocaleString('de');
    const limit     = data.limit.toLocaleString('de');
    btn.textContent = `★ Lara (${remaining} / ${limit})`;
    if (data.remaining <= 0) {
      btn.disabled = true;
      btn.title = 'Lara: daily limit reached';
    }
  } catch {}
}

async function checkTerminology() {
  const src     = document.getElementById('srcLang').value;
  const tgt     = document.getElementById('tgtLang').value;
  const mindset = document.getElementById('mindsetSelect').value;
  const dot     = document.getElementById('termDot');
  const label   = document.getElementById('termStatus');
  if (!dot || !label) return;
  try {
    const s = await fetch(
      `/terminology/status?source=${src}&target=${tgt}&mindset=${mindset}`
    ).then(r => r.json());
    if (s.active) {
      dot.className     = 'dot ok';
      label.textContent = `Term ${s.src_lang}→${s.tgt_lang}`;
    } else {
      dot.className = 'dot';
      const missing = [];
      if (!s.src_available) missing.push(s.src_lang);
      if (!s.tgt_available) missing.push(s.tgt_lang);
      label.textContent = `Term (${missing.join('+')} n/a)`;
    }
  } catch {
    dot.className     = 'dot';
    label.textContent = 'Term';
  }
}