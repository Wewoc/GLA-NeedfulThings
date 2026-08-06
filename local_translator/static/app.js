// ── app.js — Globaler State, Init, Input-Setup ──────────────────────────────
//
// Besitzt: globaler State (6 Variablen), init(), setupInput()
//
// Liest globalen State: alle
// Schreibt globalen State: config (initiales Befüllen), debounceTimer, mindsetDetected
//
// Ruft auf: Funktionen aus ui.js, engines.js, translate.js
//
// Muss als letztes Script geladen werden — init() setzt alle anderen voraus.

// ── Globaler State ───────────────────────────────────────────────────────────

let config = {};
let debounceTimer = null;
let currentTranslation = '';
let isTranslating = false;
let abortController = null;
let mindsetDetected = false;

// ── Init ─────────────────────────────────────────────────────────────────────

async function init() {
  config = await fetch('/config').then(r => r.json());

  // Sprach-Dropdowns befüllen
  ['srcLang', 'tgtLang'].forEach(id => {
    const sel = document.getElementById(id);
    Object.entries(config.languages).forEach(([name, code]) => {
      const opt = document.createElement('option');
      opt.value = code;
      opt.textContent = name;
      sel.appendChild(opt);
    });
  });
  document.getElementById('srcLang').value   = config.default_source_lang;
  document.getElementById('tgtLang').value   = config.default_target_lang;
  document.getElementById('modeSelect').value = config.default_mode || 'debounce';

  // Mindset-Dropdown befüllen
  const mindsetSel = document.getElementById('mindsetSelect');
  Object.entries(config.mindsets || {}).forEach(([key, label]) => {
    const opt = document.createElement('option');
    opt.value = key;
    opt.textContent = label;
    mindsetSel.appendChild(opt);
  });
  mindsetSel.value = config.default_mindset || 'general';

  // Final-Pass Buttons
  document.getElementById('deeplBtn').disabled = !config.deepl_available;

  if (config.libretranslate_available) checkLibre();
  else document.getElementById('libreBtn').disabled = true;

  const mmBtn = document.getElementById('mymemoryBtn');
  mmBtn.disabled = !config.mymemory_available;
  if (!config.mymemory_available) mmBtn.dataset.forceDisabled = '1';

  document.getElementById('laraBtn').disabled = !config.lara_available;
  if (config.lara_available) updateLaraUsage();

  // VRAM-Status
  updateVramStatus();
  setInterval(updateVramStatus, 10000);

  // Sprach-Dropdowns → LibreTranslate-Status
  document.getElementById('srcLang').addEventListener('change', () => {
    if (config.libretranslate_available) checkLibre();
    checkTerminology();
  });
  document.getElementById('tgtLang').addEventListener('change', () => {
    if (config.libretranslate_available) checkLibre();
    checkTerminology();
  });
  document.getElementById('mindsetSelect').addEventListener('change', () => {
    checkTerminology();
  });
  checkTerminology();

  // Ollama-Status
  checkOllama();
  setInterval(checkOllama, 30000);

  setupInput();
}

// ── Input-Setup ───────────────────────────────────────────────────────────────

function setupInput() {
  const ta  = document.getElementById('srcText');
  const out = document.getElementById('tgtOutput');

  // Synchronisiertes Scrollen
  ta.addEventListener('scroll', () => {
    const ratio = ta.scrollTop / (ta.scrollHeight - ta.clientHeight || 1);
    out.scrollTop = ratio * (out.scrollHeight - out.clientHeight);
  });
  out.addEventListener('scroll', () => {
    const ratio = out.scrollTop / (out.scrollHeight - out.clientHeight || 1);
    ta.scrollTop = ratio * (ta.scrollHeight - ta.clientHeight);
  });

  // Übersetzung im Debounce-Modus. Mindset-Detect passiert NICHT hier mehr
  // (siehe translate.js) - es soll erst laufen, wenn eine Übersetzung
  // tatsächlich startet, egal über welchen Trigger (Button/Enter/Debounce),
  // nicht bei jedem einzelnen Tastendruck unabhängig vom gewählten Modus.
  ta.addEventListener('input', () => {
    updateCharCount('srcText', 'srcCount');

    const mode = document.getElementById('modeSelect').value;
    if (mode === 'debounce') {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        translateNow();
      }, (config.debounce_seconds || 1.5) * 1000);
    }
  });

  // Sentence-Modus
  ta.addEventListener('keydown', (e) => {
    const mode = document.getElementById('modeSelect').value;
    if (mode === 'sentence' && e.key === 'Enter' && !e.shiftKey) {
      setTimeout(translateNow, 50);
    }
  });
}

init();