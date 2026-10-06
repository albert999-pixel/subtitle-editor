// ── State ──────────────────────────────────────────────────
let rows = [];       // [{text, preservedCase: Set<number>, reviewReasons?: string[]}]
let trMode = 'auto'; // 'auto' | 'punct'
let wordTimings = [];
let mode = 'edit';   // 'edit' | 'highlight'
let srtContent = '';
let selectedFile = null;
let statusTimer = null;
let history = [];    // стек для отмены
let historyIndex = -1;
let editHistoryTimer = null;
let aiProposal = null;
let aiView = 'packed';

function saveHistory() {
  clearTimeout(editHistoryTimer);
  editHistoryTimer = null;
  // Обрезаем всё что после текущего индекса (если делали undo и потом новое действие)
  history = history.slice(0, historyIndex + 1);
  // Сохраняем глубокую копию
  history.push(rows.map(SubtitleAI.cloneRow));
  historyIndex++;
  // Не храним больше 50 шагов
  if (history.length > 50) { history.shift(); historyIndex--; }
}

function undo() {
  if (historyIndex <= 0) return;
  historyIndex--;
  rows = history[historyIndex].map(SubtitleAI.cloneRow);
  renderRows();
}

function redo() {
  if (historyIndex >= history.length - 1) return;
  historyIndex++;
  rows = history[historyIndex].map(SubtitleAI.cloneRow);
  renderRows();
}

// ── Init ───────────────────────────────────────────────────
async function init() {
  const cfg = await fetch('/api/config').then(r => r.json());
  document.getElementById('transcriptionProvider').value = cfg.provider || 'local';
  document.getElementById('groqModel').value = cfg.groq_model || 'whisper-large-v3-turbo';
  updateKeyStatus(cfg.groq_key_set);
  updateProviderUI();
  loadLocalModels();
}

function updateProviderUI() {
  const cloud = document.getElementById('transcriptionProvider').value === 'groq';
  document.getElementById('localSection').style.display = cloud ? 'none' : '';
  document.getElementById('groqSection').style.display = cloud ? '' : 'none';
}
function updateKeyStatus(saved) {
  document.getElementById('groqKeyStatus').textContent = saved
    ? 'Ключ сохранён на этом компьютере. Пустое поле оставляет его без изменений.'
    : 'Ключ не сохранён';
}
async function saveTranscriptionSettings(clearKey = false) {
  const status = document.getElementById('transcriptionSettingsStatus');
  const input = document.getElementById('groqKey');
  const payload = {
    provider: document.getElementById('transcriptionProvider').value,
    groq_model: document.getElementById('groqModel').value,
  };
  if (clearKey) payload.groq_api_key = '';
  else if (input.value.trim()) payload.groq_api_key = input.value.trim();
  try {
    const res = await fetch('/api/config', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.detail || data.error || 'Не удалось сохранить настройки');
    input.value = '';
    const cfg = await fetch('/api/config').then(r => r.json());
    updateKeyStatus(cfg.groq_key_set);
    status.textContent = clearKey ? 'Ключ удалён' : 'Настройки сохранены';
    return true;
  } catch (error) {
    status.textContent = error.message;
    return false;
  }
}
function clearGroqKey() { return saveTranscriptionSettings(true); }

// ── File ───────────────────────────────────────────────────
document.getElementById('fi').addEventListener('change', e => { if (e.target.files[0]) pickFile(e.target.files[0]); });
const uz = document.getElementById('uploadZone');
uz.addEventListener('dragover', e => { e.preventDefault(); uz.classList.add('drag-over'); });
uz.addEventListener('dragleave', () => uz.classList.remove('drag-over'));
uz.addEventListener('drop', e => { e.preventDefault(); uz.classList.remove('drag-over'); if (e.dataTransfer.files[0]) pickFile(e.dataTransfer.files[0]); });

function pickFile(f) {
  try {
    const extension = f.name.slice(f.name.lastIndexOf('.')).toLowerCase();
    const supported = ['.mp3', '.m4a', '.mp4', '.wav', '.flac', '.ogg', '.webm'];
    if (!supported.includes(extension) || !f.size) {
      removeFile();
      setStatus('error', !f.size
        ? 'Файл пустой. Выбери аудиофайл с записью.'
        : 'Выбери аудиофайл: MP3, M4A, MP4, WAV, FLAC, OGG или WEBM. SRT — файл субтитров, его нельзя транскрибировать.');
      return;
    }
    selectedFile = f;
    document.getElementById('fileName').textContent = f.name;
    document.getElementById('fileChip').classList.add('show');
    document.getElementById('trBtn').disabled = false;
    setStatus('', '');
  } catch(err) {
    alert('pickFile error: ' + err.message);
  }
}
function removeFile() {
  selectedFile = null;
  document.getElementById('fi').value = '';
  document.getElementById('fileChip').classList.remove('show');
  document.getElementById('trBtn').disabled = true;
  setStatus('', '');
}
function setStatus(type, msg) {
  const bar = document.getElementById('statusBar');
  bar.className = type ? `status show ${type}` : 'status';
  bar.innerHTML = msg;
}


async function loadLocalModels() {
  const sel = document.getElementById('localModelSelect');
  try {
    const res = await fetch('/api/local-models');
    const data = await res.json();
    sel.innerHTML = '';
    if (!data.models || !data.models.length) {
      sel.innerHTML = '<option value="">Нет моделей в папке models/</option>';
    } else {
      data.models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m; opt.textContent = m;
        sel.appendChild(opt);
      });
    }
  } catch (e) {
    sel.innerHTML = '<option value="">Ошибка загрузки моделей</option>';
  }
  // Разблокируем кнопку если файл уже выбран
  if (selectedFile) document.getElementById('trBtn').disabled = false;
}

// ── Transcription ──────────────────────────────────────────
async function startTranscription() {
  if (!selectedFile) return;
  const button = document.getElementById('trBtn');
  button.disabled = true;
  try {
    if (!await saveTranscriptionSettings()) throw new Error('Проверь настройки транскрибации');
    const provider = document.getElementById('transcriptionProvider').value;
    const model = document.getElementById('localModelSelect').value;
    if (provider === 'local' && !model) throw new Error('Выбери локальную модель или переключись на Groq');
    const form = new FormData();
    form.append('file', selectedFile);
    form.append('model', model);
    form.append('provider', provider);
    form.append('groq_model', document.getElementById('groqModel').value);
    const res = await fetch('/api/transcribe', {method:'POST', body:form});
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.detail || data.error || 'Не удалось начать транскрибацию');
    setStatus('processing', '<span class="spin">⟳</span> Транскрибирую...');
    clearInterval(statusTimer);
    statusTimer = setInterval(pollStatus, 800);
  } catch (error) {
    setStatus('error', '');
    document.getElementById('statusBar').textContent = error.message;
    button.disabled = false;
  }
}
async function pollStatus() {
  const d = await fetch('/api/status').then(r => r.json());
  if (d.status === 'processing') {
    setStatus('processing', `<span class="spin">⟳</span> ${d.message}`);
  } else if (d.status === 'done') {
    clearInterval(statusTimer);
    setStatus('done', '✅ ' + d.message);
    wordTimings = d.words;
    initRows(d.text);
    reloadPlayer();
    document.getElementById('buildBtn').disabled = false;
    document.getElementById('trBtn').disabled = false;
  } else if (d.status === 'error') {
    clearInterval(statusTimer);
    setStatus('error', '');
    document.getElementById('statusBar').textContent = '❌ ' + d.message;
    document.getElementById('trBtn').disabled = false;
  }
}

// ── Rows init ──────────────────────────────────────────────
function initRows(text) {
  rows = [];

  if (trMode === 'punct') {
    // Разбивка по знакам препинания
    // Разбиваем после . ! ? , — оставляем знак в конце строки
    const parts = text.split(/(?<=[.!?,])\s+/);
    for (const part of parts) {
      const trimmed = part.trim();
      if (trimmed) rows.push({ text: trimmed, preservedCase: new Set() });
    }
    // Если по каким-то причинам ничего не разбилось — fallback на авто
    if (rows.length <= 1 && text.length > 40) {
      rows = [];
      initRowsAuto(text);
      return;
    }
  } else {
    initRowsAuto(text);
    return;
  }

  history = []; historyIndex = -1;
  saveHistory();
  renderRows();
}

function initRowsAuto(text) {
  const words = text.split(' ').filter(w => w.trim());
  const maxChars = parseInt(document.getElementById('maxChars').value) || 24;
  rows = [];
  let cur = [], len = 0;
  for (const w of words) {
    const add = len + w.length + (cur.length ? 1 : 0);
    if (add > maxChars && cur.length) {
      rows.push({ text: cur.join(' '), preservedCase: new Set() });
      cur = [w]; len = w.length;
    } else {
      cur.push(w);
      len += w.length + (cur.length > 1 ? 1 : 0);
    }
  }
  if (cur.length) rows.push({ text: cur.join(' '), preservedCase: new Set() });
  history = []; historyIndex = -1;
  saveHistory();
  renderRows();
}

// ── Mode ───────────────────────────────────────────────────
function setMode(m) {
  if (editHistoryTimer) saveHistory();
  mode = m;
  document.getElementById('modeEdit').classList.toggle('active', m === 'edit');
  document.getElementById('modeCase').classList.toggle('active', m === 'highlight');
  document.getElementById('modeAI').classList.toggle('active', m === 'ai');
  document.getElementById('aiPanel').style.display = m === 'ai' ? '' : 'none';
  document.getElementById('subList').style.display = m === 'ai' ? 'none' : '';
  document.getElementById('clearCaseSelection').style.display = m === 'highlight' ? '' : 'none';
  document.getElementById('selectAllCaseWords').style.display = m === 'highlight' ? '' : 'none';
  document.getElementById('applyLowercase').style.display = m === 'highlight' ? '' : 'none';
  document.getElementById('caseHint').style.display = m === 'highlight' ? '' : 'none';
  renderRows();
}

// ── Render ─────────────────────────────────────────────────
function renderRows() {
  const list = document.getElementById('subList');
  list.innerHTML = '';

  if (!rows.length) {
    list.appendChild(document.getElementById('emptyState'));
    document.getElementById('emptyState').style.display = 'flex';
    return;
  }

  rows.forEach((row, ri) => {
    const charCount = row.text.length;
    const maxCh = parseInt(document.getElementById('maxChars').value) || 24;
    const isOver = charCount > maxCh;

    const wrap = document.createElement('div');
    wrap.className = 'sub-row';

    // Number
    const num = document.createElement('div');
    num.className = 'row-num' + (row.reviewReasons?.length ? ' needs-review' : '');
    if (row.reviewReasons?.length) num.title = 'Обрати внимание: ' + row.reviewReasons.join('; ');
    num.textContent = ri + 1;

    // Content
    let content;
    if (mode !== 'highlight') {
      content = document.createElement('input');
      content.type = 'text';
      content.className = 'row-edit-input' + (isOver ? ' over' : '');
      content.value = row.text;
      content.addEventListener('input', () => {
        rows[ri].preservedCase = SubtitleCase.remapSelection(rows[ri].text, content.value, rows[ri].preservedCase);
        rows[ri].text = content.value;
        const cc = wrap.querySelector('.char-cnt');
        const over = content.value.length > (parseInt(document.getElementById('maxChars').value) || 24);
        cc.textContent = content.value.length;
        cc.className = 'char-cnt' + (over ? ' over' : '');
        content.className = 'row-edit-input' + (over ? ' over' : '');
        document.getElementById('subCount').textContent = `${rows.length} субтитров`;
        // Сохраняем в историю через 600мс после остановки печати
        clearTimeout(editHistoryTimer);
        editHistoryTimer = setTimeout(() => saveHistory(), 600);
      });
      content.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
          e.preventDefault();
          // Split at cursor
          const pos = content.selectionStart;
          const before = content.value.slice(0, pos).trim();
          const after = content.value.slice(pos).trim();
          const boundary = (before.match(/\S+/g) || []).length;
          const selected = rows[ri].preservedCase;
          rows[ri].text = before;
          rows[ri].preservedCase = new Set([...selected].filter(i => i < boundary));
          rows.splice(ri + 1, 0, { text: after, preservedCase: new Set([...selected].filter(i => i >= boundary).map(i => i - boundary)), reviewReasons: SubtitleAI.reviewReasons(rows[ri]) });
          saveHistory();
          renderRows();
          // Focus next row
          setTimeout(() => {
            const inputs = document.querySelectorAll('.row-edit-input');
            if (inputs[ri + 1]) inputs[ri + 1].focus();
          }, 10);
        } else if (e.key === 'Backspace' && content.value === '') {
          // Пустая строка — удаляем и переходим на предыдущую
          e.preventDefault();
          if (rows.length > 1) {
            rows.splice(ri, 1);
            saveHistory();
            renderRows();
            setTimeout(() => {
              const inputs = document.querySelectorAll('.row-edit-input');
              const focusIdx = Math.min(ri, inputs.length - 1);
              if (inputs[focusIdx]) {
                inputs[focusIdx].focus();
                const len = inputs[focusIdx].value.length;
                inputs[focusIdx].setSelectionRange(len, len);
              }
            }, 10);
          }
        } else if (e.key === 'Backspace' && content.selectionStart === 0 && content.selectionEnd === 0 && ri > 0) {
          // Курсор в начале строки — объединяем с предыдущей
          e.preventDefault();
          const prevLen = rows[ri - 1].text.length;
          const offset = (rows[ri - 1].text.match(/\S+/g) || []).length;
          rows[ri - 1].text = (rows[ri - 1].text + ' ' + rows[ri].text).trim();
          rows[ri].preservedCase.forEach(wi => rows[ri - 1].preservedCase.add(wi + offset));
          rows[ri - 1].reviewReasons = SubtitleAI.reviewReasons(rows[ri - 1], rows[ri]);
          rows.splice(ri, 1);
          saveHistory();
          renderRows();
          setTimeout(() => {
            const inputs = document.querySelectorAll('.row-edit-input');
            if (inputs[ri - 1]) {
              inputs[ri - 1].focus();
              inputs[ri - 1].setSelectionRange(prevLen, prevLen);
            }
          }, 10);
        } else if (e.key === 'Delete' && content.selectionStart === content.value.length && ri < rows.length - 1) {
          // Курсор в конце строки — объединяем со следующей
          e.preventDefault();
          const curLen = rows[ri].text.length;
          const offset = (rows[ri].text.match(/\S+/g) || []).length;
          rows[ri + 1].preservedCase.forEach(wi => rows[ri].preservedCase.add(wi + offset));
          rows[ri].text = (rows[ri].text + ' ' + rows[ri + 1].text).trim();
          rows[ri].reviewReasons = SubtitleAI.reviewReasons(rows[ri], rows[ri + 1]);
          rows.splice(ri + 1, 1);
          saveHistory();
          renderRows();
          setTimeout(() => {
            const inputs = document.querySelectorAll('.row-edit-input');
            if (inputs[ri]) {
              inputs[ri].focus();
              inputs[ri].setSelectionRange(curLen, curLen);
            }
          }, 10);
        } else if (e.key === 'ArrowUp') {
          // Переходим на строку выше, сохраняем позицию курсора
          e.preventDefault();
          const pos = content.selectionStart;
          const inputs = document.querySelectorAll('.row-edit-input');
          if (inputs[ri - 1]) {
            inputs[ri - 1].focus();
            const p = Math.min(pos, inputs[ri - 1].value.length);
            inputs[ri - 1].setSelectionRange(p, p);
          }
        } else if (e.key === 'ArrowDown') {
          // Переходим на строку ниже, сохраняем позицию курсора
          e.preventDefault();
          const pos = content.selectionStart;
          const inputs = document.querySelectorAll('.row-edit-input');
          if (inputs[ri + 1]) {
            inputs[ri + 1].focus();
            const p = Math.min(pos, inputs[ri + 1].value.length);
            inputs[ri + 1].setSelectionRange(p, p);
          }
        }
      });
    } else {
      // Highlight mode — chips
      content = document.createElement('div');
      content.className = 'row-chips';
      const words = row.text.match(/\S+/g) || [];
      words.forEach((w, wi) => {
        const chip = document.createElement('span');
        chip.className = 'chip' + (row.preservedCase.has(wi) ? ' on' : '');
        chip.textContent = w;
        chip.title = row.preservedCase.has(wi) ? 'Регистр этого слова сохраняется' : 'Сохранить регистр';
        chip.setAttribute('role', 'button');
        chip.setAttribute('aria-pressed', String(row.preservedCase.has(wi)));
        chip.tabIndex = 0;
        chip.addEventListener('keydown', event => {
          if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); event.stopPropagation(); chip.click(); }
        });
        chip.addEventListener('click', () => {
          if (row.preservedCase.has(wi)) row.preservedCase.delete(wi);
          else row.preservedCase.add(wi);
          saveHistory();
          renderRows();
        });
        content.appendChild(chip);
      });
    }

    // Side buttons
    const side = document.createElement('div');
    side.className = 'row-side';

    const splitBtn = document.createElement('button');
    splitBtn.className = 'side-btn';
    splitBtn.title = 'Добавить строку ниже';
    splitBtn.textContent = '+';
    splitBtn.addEventListener('click', () => {
      rows.splice(ri + 1, 0, { text: '', preservedCase: new Set() });
      saveHistory();
      renderRows();
      setTimeout(() => {
        const inputs = document.querySelectorAll('.row-edit-input');
        if (inputs[ri + 1]) inputs[ri + 1].focus();
      }, 10);
    });

    const delBtn = document.createElement('button');
    delBtn.className = 'side-btn del';
    delBtn.title = 'Удалить строку';
    delBtn.textContent = '×';
    delBtn.addEventListener('click', () => { rows.splice(ri, 1); saveHistory(); renderRows(); });

    const playRowBtn = document.createElement('button');
    playRowBtn.className = 'side-btn play';
    playRowBtn.title = 'Перейти в плеере';
    playRowBtn.innerHTML = '&#9654;';
    playRowBtn.addEventListener('click', () => seekToRow(ri));

    side.appendChild(playRowBtn);
    side.appendChild(splitBtn);
    side.appendChild(delBtn);

    // Char count
    const cc = document.createElement('div');
    cc.className = 'char-cnt' + (isOver ? ' over' : '');
    cc.textContent = charCount;

    wrap.appendChild(num);
    wrap.appendChild(content);
    wrap.appendChild(side);
    wrap.appendChild(cc);
    list.appendChild(wrap);
  });

  document.getElementById('subCount').textContent = `${rows.length} субтитров`;
}

function clearCaseSelection() { rows.forEach(r => r.preservedCase.clear()); saveHistory(); renderRows(); }
function selectAllCaseWords() { rows.forEach(r => (r.text.match(/\S+/g) || []).forEach((_, i) => r.preservedCase.add(i))); saveHistory(); renderRows(); }

function lowercaseUnselected() {
  if (!rows.length) return;
  rows.forEach(row => {
    row.text = SubtitleCase.lowercaseExcept(row.text, row.preservedCase);
  });
  saveHistory();
  renderRows();
  toast('Строчные применены. Регистр выделенных слов сохранён.');
}

function splitInputSignature() {
  return JSON.stringify({texts:rows.map(row => row.text), max:parseInt(document.getElementById('maxChars').value) || 24});
}
async function requestAISplit() {
  if (editHistoryTimer) saveHistory();
  const button = document.getElementById('aiSuggest');
  const status = document.getElementById('aiStatus');
  const signature = splitInputSignature();
  const snapshot = JSON.parse(signature);
  const previousEnds = aiProposal?.signature === signature ? SubtitleAI.variant(aiProposal.data, aiView).ends : null;
  button.disabled = true;
  document.getElementById('aiRegenerate').disabled = true;
  status.textContent = 'Groq делит текст на смысловые фразы…';
  try {
    const res = await fetch('/api/ai-split', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({texts:snapshot.texts, max_chars:snapshot.max, previous_ends:previousEnds})});
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Не удалось получить разбивку');
    if (splitInputSignature() !== signature) throw new Error('Текст или лимит изменился во время запроса. Получи новое предложение.');
    aiProposal = {signature, data};
    document.getElementById('aiRawResponse').textContent = data.raw_response || '(пустой ответ)';
    document.getElementById('aiRawPanel').style.display = 'block';
    const warnings = document.getElementById('aiWarnings');
    warnings.replaceChildren();
    (data.warnings || []).forEach(message => {
      const item = document.createElement('li');
      item.textContent = message;
      warnings.appendChild(item);
    });
    warnings.style.display = data.warnings?.length ? 'block' : 'none';
    document.getElementById('aiRawPanel').open = Boolean(data.warnings?.length);
    document.getElementById('aiActions').style.display = 'flex';
    document.getElementById('aiViewSwitch').style.display = 'flex';
    renderAIPreview();
  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = false;
    document.getElementById('aiRegenerate').disabled = false;
  }
}
function setAIView(view) {
  aiView = view;
  renderAIPreview();
}
function renderAIPreview() {
  if (!aiProposal) return;
  const data = aiProposal.data;
  const selected = SubtitleAI.variant(data, aiView);
  const preview = document.getElementById('aiPreview');
  preview.replaceChildren();
  document.getElementById('aiViewPacked').classList.toggle('active', aiView === 'packed');
  document.getElementById('aiViewGroups').classList.toggle('active', aiView === 'groups');
  document.getElementById('aiViewPacked').setAttribute('aria-pressed', String(aiView === 'packed'));
  document.getElementById('aiViewGroups').setAttribute('aria-pressed', String(aiView === 'groups'));
  selected.lines.forEach((text, index) => {
    const item = document.createElement('div');
    item.className = 'sub-row';
    const notes = selected.notes[index];
    item.textContent = `${index + 1}. ${text} (${Array.from(text).length}/${data.max_chars}${notes.length ? ' · ' + notes.join('; ') : ''})`;
    if (notes.length) { item.style.border = '1px solid #e8a849'; item.style.color = '#e8a849'; }
    preview.appendChild(item);
  });
  const count = selected.notes.filter(notes => notes.length).length;
  document.getElementById('aiStatus').textContent = `${aiView === 'groups' ? 'Чанки GPT OSS без объединения' : 'Титры, собранные программой'}: ${selected.lines.length}. Строк с предупреждениями: ${count}. При применении их номера будут отмечены красным кружком. Все исходные слова сохранены; дословный ответ модели доступен ниже.`;
}
function discardAISplit() {
  aiProposal = null;
  document.getElementById('aiViewSwitch').style.display = 'none';
  document.getElementById('aiPreview').replaceChildren();
  document.getElementById('aiRawResponse').textContent = '';
  document.getElementById('aiRawPanel').style.display = 'none';
  document.getElementById('aiWarnings').replaceChildren();
  document.getElementById('aiWarnings').style.display = 'none';
  document.getElementById('aiActions').style.display = 'none';
  document.getElementById('aiStatus').textContent = '';
}
function applyAISplit() {
  if (!aiProposal) return;
  if (aiProposal.signature !== splitInputSignature()) {
    discardAISplit();
    document.getElementById('aiStatus').textContent = 'Текст или лимит изменился. Получи новое предложение.';
    return;
  }
  if (editHistoryTimer) saveHistory();
  rows = SubtitleAI.applyVariant(rows, SubtitleAI.variant(aiProposal.data, aiView));
  saveHistory();
  discardAISplit();
  setMode('edit');
  toast('Разбивка применена. Cmd+Z / Ctrl+Z вернёт прежние титры.');
}

// ── Build SRT ──────────────────────────────────────────────
async function buildSRT() {
  const lines = rows.map(r => ({ text: r.text }));
  const res = await fetch('/api/build-srt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lines, words: wordTimings })
  });
  const data = await res.json();
  if (data.error) { alert(data.error); return; }
  srtContent = data.srt;
  document.getElementById('dlBtn').style.display = '';
  document.getElementById('doneMsg').textContent = `Создано субтитров: ${data.count}. Минимальная длительность — 0,5 с. Пересекающиеся титры сдвинуты вперёд.`;
  document.getElementById('doneModal').classList.add('show');
}

function downloadSRT() {
  const name = (selectedFile ? selectedFile.name.replace(/\.[^.]+$/, '') : 'subtitles') + '.srt';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([srtContent], { type: 'text/plain' }));
  a.download = name;
  a.click();
}

function toast(msg) {
  const t = document.createElement('div');
  t.textContent = msg;
  t.style.cssText = 'position:fixed;bottom:20px;right:20px;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:9px 14px;font-size:11px;z-index:999';
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2200);
}

// Удаление точек и запятых в конце субтитров
function stripTrailingPunct() {
  rows.forEach(r => {
    r.text = r.text.replace(/[.,]+$/, '').trim();
  });
  saveHistory();
  renderRows();
  toast('✅ Знаки препинания убраны');
}

// Режим разбивки транскрипции
function selectTrMode(mode) {
  trMode = mode;
  const autoEl = document.getElementById('trModeAuto');
  const punctEl = document.getElementById('trModePunct');
  if (mode === 'auto') {
    autoEl.style.border = '1px solid var(--accent)';
    autoEl.style.background = 'rgba(255,251,0,0.05)';
    punctEl.style.border = '1px solid var(--border)';
    punctEl.style.background = 'transparent';
  } else {
    punctEl.style.border = '1px solid var(--accent)';
    punctEl.style.background = 'rgba(255,251,0,0.05)';
    autoEl.style.border = '1px solid var(--border)';
    autoEl.style.background = 'transparent';
  }
}

// Глобальный обработчик Cmd+Z / Cmd+Shift+Z
document.addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z' && !e.shiftKey) {
    e.preventDefault();
    undo();
  } else if ((e.metaKey || e.ctrlKey) && (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey))) {
    e.preventDefault();
    redo();
  }
});

init();

// ─── Audio Player ────────────────────────────────────────
const audio = document.getElementById('audioPlayer');

function showPlayer() {
  const bar = document.getElementById('playerBar');
  bar.style.display = 'flex';
}

function togglePlay() {
  if (audio.paused) { audio.play(); document.getElementById('playBtn').innerHTML = '&#9646;&#9646;'; }
  else              { audio.pause(); document.getElementById('playBtn').innerHTML = '&#9654;'; }
}

function getRowTiming(i) {
  // Вычисляем тайминг строки через wordTimings.
  // Идём по всем строкам до i-й, считаем сколько слов они занимают,
  // затем берём соответствующий диапазон из wordTimings.
  if (!wordTimings || !wordTimings.length) return null;
  let wordIdx = 0;
  for (let r = 0; r < i; r++) {
    wordIdx += rows[r].text.split(' ').filter(w => w.trim()).length;
  }
  const rowWordCount = rows[i].text.split(' ').filter(w => w.trim()).length;
  const slice = wordTimings.slice(wordIdx, wordIdx + rowWordCount);
  if (!slice.length) return null;
  return { start: slice[0].start, end: slice[slice.length - 1].end };
}

function seekToRow(i) {
  const timing = getRowTiming(i);
  if (!timing) return;
  audio.currentTime = timing.start;
  audio.play();
  document.getElementById('playBtn').innerHTML = '&#9646;&#9646;';
}

function onAudioLoaded() {
  showPlayer();
  document.getElementById('playerTime').textContent = '0:00 / ' + fmtTime(audio.duration);
}

function onAudioTick() {
  if (!audio.duration) return;
  const pct = audio.currentTime / audio.duration * 100;
  document.getElementById('progressFill').style.width = pct + '%';
  document.getElementById('playerTime').textContent = fmtTime(audio.currentTime) + ' / ' + fmtTime(audio.duration);
  const t = audio.currentTime;
  document.querySelectorAll('.sub-row').forEach((el, i) => {
    const timing = getRowTiming(i);
    if (timing && t >= timing.start && t < timing.end) {
      if (!el.classList.contains('row-active')) {
        el.classList.add('row-active');
        const rect = el.getBoundingClientRect();
        if (rect.bottom > window.innerHeight - 160) {
          // Скроллим к элементу на 3 строки выше — получаем отступ сверху
          const rows_els = document.querySelectorAll('.sub-row');
          const targetEl = rows_els[Math.max(0, i - 3)] || el;
          targetEl.scrollIntoView({ block: 'start', behavior: 'smooth' });
        }
      }
    } else {
      el.classList.remove('row-active');
    }
  });
}

function seekFromBar(e) {
  const bar = document.getElementById('progressBar');
  const rect = bar.getBoundingClientRect();
  const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
  if (audio.duration) audio.currentTime = pct * audio.duration;
}

function fmtTime(s) {
  if (!s || isNaN(s)) return '0:00';
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60).toString().padStart(2, '0');
  return m + ':' + sec;
}

function reloadPlayer() {
  audio.src = '/api/audio?t=' + Date.now();
  audio.load();
}

// Пробел = play/pause (когда не в инпуте)
document.addEventListener('keydown', e => {
  if (e.code === 'Space' && document.activeElement.tagName !== 'INPUT') {
    e.preventDefault();
    togglePlay();
  }
});
