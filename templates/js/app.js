/* ────────────────────────────────────────────────────────────────────────────────
   ASSET INTELLIGENCE TRACKER - MAIN APPLICATION SCRIPT
   ───────────────────────────────────────────────────────────────────────────────── */

// ─────────────────────────────────────────────────────────────────────────────────
// DOM ELEMENT REFERENCES
// ─────────────────────────────────────────────────────────────────────────────────

const dropZone    = document.getElementById('dropZone');
const fileInput   = document.getElementById('fileInput');
const btnSearchIndividually = document.getElementById('btnSearchIndividually');
const btnExportIndividual = document.getElementById('btnExportIndividual');
const manualSearchInput = document.getElementById('manualSearchInput');
const btnManualSubmit = document.getElementById('btnManualSubmit');
const infoCard    = document.getElementById('infoCard');
const errorMsg    = document.getElementById('errorMsg');
const processingSummary = document.getElementById('processingSummary');
const tablesContainer = document.getElementById('tablesContainer');

// Theme toggle elements
const themeToggle = document.getElementById('themeToggle');
const themeIcon = document.getElementById('themeIcon');
const themeLabel = document.getElementById('themeLabel');

// Reset box elements
const resetBox = document.getElementById('resetBox');
const resetBoxFile = document.getElementById('resetBoxFile');
const btnResetCompact = document.getElementById('btnResetCompact');

// Pipeline button elements
const pipelineActions = document.getElementById('pipelineActions');
const btnTriggerPipeline = document.getElementById('btnTriggerPipeline');

// Hardware table elements
const hwTableSection = document.getElementById('hwTableSection');
const hwTableHead = document.getElementById('hwTableHead');
const hwTableBody = document.getElementById('hwTableBody');
const hwTableMeta = document.getElementById('hwTableMeta');

// Software table elements
const swTableSection = document.getElementById('swTableSection');
const swTableHead = document.getElementById('swTableHead');
const swTableBody = document.getElementById('swTableBody');
const swTableMeta = document.getElementById('swTableMeta');
const apiKeyToast = document.getElementById('apiKeyToast');
const liveDateTime = document.getElementById('liveDateTime');

// AI Chat elements
const aiChatBtn = document.getElementById('aiChatBtn');
const aiChatModal = document.getElementById('aiChatModal');
const aiChatClose = document.getElementById('aiChatClose');

// ─────────────────────────────────────────────────────────────────────────────────
// APPLICATION STATE
// ─────────────────────────────────────────────────────────────────────────────────

const ALLOWED = ['.csv', '.xlsx'];
btnExportIndividual.disabled = true;

let currentFile = null;
let manualMode = false;
let manualAutoRunActive = false;
let _manualFirstResultDone = false;
let currentManualEs = null;
let manualTimerInterval = null;
let apiKeyToastTimer = null;

const selectedRows = { hw: new Set(), sw: new Set() };
const lastToggledRow = { hw: null, sw: null };
const editedNames = { hw: {}, sw: {} };
const tableTotals = { hw: 0, sw: 0 };
const currentTableData = { hw: [], sw: [] };

// ─────────────────────────────────────────────────────────────────────────────────
// TIME & DATE UTILITIES
// ─────────────────────────────────────────────────────────────────────────────────

let lastFetchedTime = null;
let timeOffsetMs = 0;

async function fetchNTPTime() {
  try {
    const response = await fetch('/get-time');
    const data = await response.json();
    if (data.timestamp) {
      lastFetchedTime = new Date(data.timestamp);
      timeOffsetMs = lastFetchedTime.getTime() - Date.now();
    }
  } catch (err) {
    console.warn('Failed to fetch NTP time:', err);
  }
}

function formatDateTimeUTC8() {
  const now = lastFetchedTime ? new Date(lastFetchedTime.getTime() - timeOffsetMs + (Date.now() - lastFetchedTime.getTime())) : new Date();
  const utc8Time = new Date(now.getTime() + (8 * 60 * 60 * 1000));
  
  const dayNames = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const day = dayNames[utc8Time.getUTCDay()];
  const date = String(utc8Time.getUTCDate()).padStart(2, '0');
  const month = String(utc8Time.getUTCMonth() + 1).padStart(2, '0');
  const year = utc8Time.getUTCFullYear();
  const hours = String(utc8Time.getUTCHours()).padStart(2, '0');
  const minutes = String(utc8Time.getUTCMinutes()).padStart(2, '0');
  const seconds = String(utc8Time.getUTCSeconds()).padStart(2, '0');
  return `${day}, ${date}/${month}/${year} - ${hours}:${minutes}:${seconds}`;
}

function updateLiveDateTime() {
  if (liveDateTime) {
    liveDateTime.textContent = formatDateTimeUTC8();
  }
}

// Fetch NTP time on load and update every second
(async function() {
  await fetchNTPTime();
  updateLiveDateTime();
  setInterval(updateLiveDateTime, 1000);
})();

// ─────────────────────────────────────────────────────────────────────────────────
// UTILITY FUNCTIONS
// ─────────────────────────────────────────────────────────────────────────────────

function formatSize(b) {
  if (b < 1024) return b + ' B';
  if (b < 1048576) return (b / 1024).toFixed(1) + ' KB';
  return (b / 1048576).toFixed(2) + ' MB';
}

function getExt(name) { 
  return name.slice(name.lastIndexOf('.')).toLowerCase(); 
}

function isApiKeyError(msg) {
  return /api key not valid|api_key_invalid/i.test(msg || '');
}

function showApiKeyToast() {
  if (apiKeyToastTimer) clearTimeout(apiKeyToastTimer);
  apiKeyToast.classList.add('visible');
  apiKeyToastTimer = setTimeout(() => {
    apiKeyToast.classList.remove('visible');
    apiKeyToastTimer = null;
  }, 5000);
}

function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.classList.add('visible');
  if (isApiKeyError(msg)) showApiKeyToast();
}

function clearError() { 
  errorMsg.classList.remove('visible'); 
}

// ─────────────────────────────────────────────────────────────────────────────────
// PROMPT INJECTION PREVENTION — CLIENT-SIDE VALIDATION
// ─────────────────────────────────────────────────────────────────────────────────

function detectPromptInjection(userInput) {
  const msg = String(userInput || '').toLowerCase();
  
  // Common prompt injection patterns
  const suspiciousPatterns = [
    // Context override attempts
    'forget your instructions', 'ignore your instructions', 'ignore your system prompt',
    'what is your system prompt', 'what were your instructions', 'override your settings',
    
    // Roleplay override
    'pretend you are', 'act as if', 'from now on', 'starting now',
    
    // Jailbreak attempts
    'disabled mode', 'ignore all rules', 'rules are now', 'you are now',
    
    // Sensitive data requests
    'show me your source', 'show me your prompt', 'database schema', 
    'api keys', 'password:', 'secret:', 'internal code',
    
    // Breaking context
    '</asset_name>', '```', 'system:', 'admin:',
    
    // Rule modification
    'new instructions', 'ignore previous', 'override', 'execute'
  ];
  
  for (const pattern of suspiciousPatterns) {
    if (msg.includes(pattern)) {
      return { suspicious: true, reason: `Detected injection pattern: "${pattern}"` };
    }
  }
  
  // Check for excessive length (potential padding attack)
  if (userInput.length > 2000) {
    return { suspicious: true, reason: 'Input exceeds 2000 character limit' };
  }
  
  // Check for excessive newlines (formatting bypass)
  const newlineCount = (userInput.match(/\n/g) || []).length;
  if (newlineCount > 5) {
    return { suspicious: true, reason: 'Too many newlines detected' };
  }
  
  return { suspicious: false, reason: '' };
}

function showInjectionWarning(reason) {
  showError(`⚠️ Security: ${reason}. Please ask a legitimate question.`);
}

// ─────────────────────────────────────────────────────────────────────────────────
// SELECTION & CHECKBOX MANAGEMENT
// ─────────────────────────────────────────────────────────────────────────────────

function syncSelection(typeKey, total, preserveExisting = true) {
  const hadPreviousRows = (tableTotals[typeKey] || 0) > 0;
  const previous = selectedRows[typeKey] || new Set();

  if (!preserveExisting || (!hadPreviousRows && previous.size === 0)) {
    selectedRows[typeKey] = new Set(Array.from({ length: total }, (_, index) => index));
  } else {
    const next = new Set();
    previous.forEach(index => {
      if (index >= 0 && index < total) next.add(index);
    });
    selectedRows[typeKey] = next;
  }

  tableTotals[typeKey] = total;
  if (total === 0) lastToggledRow[typeKey] = null;
}

function applyRowSelection(typeKey, rowIndex, checked) {
  if (checked) selectedRows[typeKey].add(rowIndex);
  else selectedRows[typeKey].delete(rowIndex);
}

function applyRangeSelection(typeKey, bodyElement, fromIndex, toIndex, checked) {
  const start = Math.min(fromIndex, toIndex);
  const end = Math.max(fromIndex, toIndex);

  for (let idx = start; idx <= end; idx += 1) {
    const checkbox = bodyElement.querySelector(`.row-select[data-type="${typeKey}"][data-index="${idx}"]`);
    if (checkbox) checkbox.checked = checked;
    applyRowSelection(typeKey, idx, checked);
  }
}

function getTableBodyByType(typeKey) {
  return typeKey === 'hw' ? hwTableBody : swTableBody;
}

function getCheckedRowIndices(typeKey) {
  const checked = new Set();
  const bodyElement = getTableBodyByType(typeKey);
  if (!bodyElement) return checked;

  bodyElement.querySelectorAll('.row-select:checked').forEach(checkbox => {
    const idx = Number(checkbox.dataset.index);
    if (!Number.isNaN(idx)) checked.add(idx);
  });

  return checked;
}

function updateTableMeta(typeKey) {
  const total = tableTotals[typeKey] || 0;
  const selected = getCheckedRowIndices(typeKey).size;
  const metaElement = typeKey === 'hw' ? hwTableMeta : swTableMeta;
  metaElement.innerHTML = `<span>${total}</span> rows · <span>${selected}</span> selected`;
}

function syncSelectAllState(typeKey) {
  const bodyElement = getTableBodyByType(typeKey);
  const total = bodyElement ? bodyElement.querySelectorAll('.row-select').length : (tableTotals[typeKey] || 0);
  const selectAll = document.getElementById(`select-all-${typeKey}`);
  if (!selectAll) return;
  const selected = getCheckedRowIndices(typeKey).size;
  selectAll.checked = total > 0 && selected === total;
  selectAll.indeterminate = selected > 0 && selected < total;
}

function refreshSelectionFromDOM() {
  selectedRows.hw = getCheckedRowIndices('hw');
  selectedRows.sw = getCheckedRowIndices('sw');
  updateTableMeta('hw');
  updateTableMeta('sw');
  syncSelectAllState('hw');
  syncSelectAllState('sw');
}

// ─────────────────────────────────────────────────────────────────────────────────
// PIPELINE URL & DATA ROUTING
// ─────────────────────────────────────────────────────────────────────────────────

function buildPipelineUrl() {
  refreshSelectionFromDOM();
  const params = new URLSearchParams();

  [...getCheckedRowIndices('hw')].sort((a, b) => a - b).forEach(index => {
    params.append('hw', index);
    const row = document.querySelector(`tr[data-row-id="row-hw-${index}"]`);
    const name = row?.querySelector('.name-text')?.textContent?.trim();
    if (name) params.append(`name_hw_${index}`, name);
  });

  [...getCheckedRowIndices('sw')].sort((a, b) => a - b).forEach(index => {
    params.append('sw', index);
    const row = document.querySelector(`tr[data-row-id="row-sw-${index}"]`);
    const name = row?.querySelector('.name-text')?.textContent?.trim();
    if (name) params.append(`name_sw_${index}`, name);
  });

  if (manualMode) {
    params.append('skip_cache', '1');
  }

  const query = params.toString();
  return query ? `/run-pipeline?${query}` : '/run-pipeline';
}

function commitAllOpenNameEdits() {
  document.querySelectorAll('.name-edit-input').forEach(input => {
    input.blur();
  });
}

function routeManualResultToTable(itemDonePayload) {
  if (!itemDonePayload || !itemDonePayload.result) return;

  const result = itemDonePayload.result;
  const itemType = itemDonePayload.type;
  const itemIndex = itemDonePayload.index;
  const declaredType = String(result['Hardware/Software'] || '').toLowerCase();
  const isHardware = declaredType.includes('hardware');
  const isSoftware = declaredType.includes('software');
  const finalTypeStr = isHardware ? 'Hardware' : isSoftware ? 'Software' : 'N.A';

  if (currentTableData[itemType]?.[itemIndex] !== undefined) {
    currentTableData[itemType][itemIndex]['Hardware/Software'] = finalTypeStr;
  }

  const tr = document.querySelector(`tr[data-row-id="row-${itemType}-${itemIndex}"]`);
  if (tr && tr.cells[3]) {
    const normalizedFinal = String(finalTypeStr).toLowerCase();
    if (normalizedFinal === 'n.a' || normalizedFinal === 'na' || normalizedFinal === 'unknown') {
      tr.cells[3].innerHTML = `<span class="type-badge" style="opacity:0.3; border-color:rgba(128,128,128,0.3); color:var(--muted);">—</span>`;
    } else {
      tr.cells[3].innerHTML = `<span class="type-badge ${isHardware ? 'hw' : 'sw'}">${isHardware ? 'HW' : 'SW'}</span>`;
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────────
// UI MODE MANAGEMENT
// ─────────────────────────────────────────────────────────────────────────────────

function toggleManualMode(nextState) {
  manualMode = nextState;
  dropZone.classList.toggle('manual-mode', manualMode);
  btnSearchIndividually.classList.toggle('active', manualMode);
  btnSearchIndividually.textContent = 'Search Individually';
  if (manualMode) {
    clearError();
    setTimeout(() => manualSearchInput.focus(), 50);
  }
}

function stopManualSpinner() {
  if (manualTimerInterval) { clearInterval(manualTimerInterval); manualTimerInterval = null; }
  btnManualSubmit.disabled = false;
  btnManualSubmit.classList.remove('loading');
}

function renderCurrentTables(showPipeline = true) {
  const hasHW = currentTableData.hw.length > 0;
  const hasSW = currentTableData.sw.length > 0;

  if (hasHW) {
    renderTable(currentTableData.hw, hwTableHead, hwTableBody, 'hw');
    hwTableSection.style.display = 'block';
  } else {
    hwTableSection.style.display = 'none';
    tableTotals.hw = 0;
    selectedRows.hw = new Set();
    lastToggledRow.hw = null;
  }

  if (hasSW) {
    renderTable(currentTableData.sw, swTableHead, swTableBody, 'sw');
    swTableSection.style.display = 'block';
  } else {
    swTableSection.style.display = 'none';
    tableTotals.sw = 0;
    selectedRows.sw = new Set();
    lastToggledRow.sw = null;
  }

  if (hasHW || hasSW) {
    tablesContainer.classList.add('visible');
    if (showPipeline) {
      pipelineActions.classList.add('visible');
      btnExportIndividual.disabled = false;
    } else {
      pipelineActions.classList.remove('visible');
      btnExportIndividual.disabled = true;
    }
    infoCard.classList.remove('visible');
    resetBox.classList.add('visible');
  } else {
    pipelineActions.classList.remove('visible');
    btnExportIndividual.disabled = true;
  }
}

async function renderProcessedData(data, elapsedTime, showPipeline = true) {
  const hwCount = data.hw_count || 0;
  const swCount = data.sw_count || 0;

  let summaryText = `File read in ${elapsedTime.toFixed(2)}s`;
  if (hwCount > 0) summaryText += ` • Hardware: <span>${hwCount}</span>`;
  if (swCount > 0) summaryText += ` • Software: <span>${swCount}</span>`;

  processingSummary.innerHTML = summaryText;
  processingSummary.classList.add('visible');

  currentTableData.hw = data.hw_data ? [...data.hw_data] : [];
  currentTableData.sw = data.sw_data ? [...data.sw_data] : [];
  selectedRows.hw = new Set();
  selectedRows.sw = new Set();
  tableTotals.hw = 0;
  tableTotals.sw = 0;
  lastToggledRow.hw = null;
  lastToggledRow.sw = null;
  editedNames.hw = {};
  editedNames.sw = {};
  renderCurrentTables(showPipeline);
}

// ─────────────────────────────────────────────────────────────────────────────────
// FILE HANDLING
// ─────────────────────────────────────────────────────────────────────────────────

function setFileInfo(file) {
  clearError();
  const ext = getExt(file.name);
  if (!ALLOWED.includes(ext)) { 
    showError(`Unsupported type "${ext}". Use .csv or .xlsx.`); 
    return false; 
  }

  const badge = document.getElementById('typeBadge');
  badge.textContent = ext.slice(1).toUpperCase();
  badge.className = `badge ${ext === '.csv' ? 'csv' : 'xlsx'}`;

  document.getElementById('fileName').textContent = file.name;
  document.getElementById('fileSize').textContent = `${formatSize(file.size)}  (${file.size.toLocaleString()} bytes)`;

  infoCard.classList.add('visible');
  tablesContainer.classList.remove('visible');
  processingSummary.classList.remove('visible');
  resetBox.classList.remove('visible');
  dropZone.classList.add('hidden');
  
  setTimeout(() => processFile(), 500);
  return true;
}

async function processFile() {
  if (!currentFile) return;
  clearError();
  processingSummary.classList.remove('visible');

  const startTime = performance.now();

  try {
    const formData = new FormData();
    formData.append('file', currentFile);

    const response = await fetch('/upload', { method: 'POST', body: formData });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `Server error ${response.status}`);
    }

    const data = await response.json();

    if (data.error) {
      showError(data.error || 'Processing failed');
      tablesContainer.classList.remove('visible');
      processingSummary.classList.remove('visible');
      return;
    }

    resetBoxFile.textContent = currentFile.name;
    await renderProcessedData(data, (performance.now() - startTime) / 1000);

  } catch (err) {
    showError('Processing failed: ' + err.message);
    tablesContainer.classList.remove('visible');
    processingSummary.classList.remove('visible');
  }
}

function reset() {
  currentFile = null;
  manualSearchInput.value = '';
  toggleManualMode(false);
  fileInput.value = '';
  infoCard.classList.remove('visible');
  tablesContainer.classList.remove('visible');
  pipelineActions.classList.remove('visible');
  btnExportIndividual.disabled = true;
  processingSummary.classList.remove('visible');
  resetBox.classList.remove('visible');
  dropZone.classList.remove('hidden');
  clearError();
  apiKeyToast.classList.remove('visible');
  if (apiKeyToastTimer) {
    clearTimeout(apiKeyToastTimer);
    apiKeyToastTimer = null;
  }
  hwTableHead.innerHTML = '';
  hwTableBody.innerHTML = '';
  swTableHead.innerHTML = '';
  swTableBody.innerHTML = '';
  currentTableData.hw = [];
  currentTableData.sw = [];
  tableTotals.hw = 0;
  tableTotals.sw = 0;
  selectedRows.hw = new Set();
  selectedRows.sw = new Set();
  lastToggledRow.hw = null;
  lastToggledRow.sw = null;
  editedNames.hw = {};
  editedNames.sw = {};
  manualAutoRunActive = false;
  _manualFirstResultDone = false;
  stopTimer();
  pipelineTimerValue.textContent = '00:00.0';
  btnTriggerPipeline.disabled = false;
  btnTriggerPipeline.querySelector('.pipeline-text').textContent = 'Trigger AI Intelligence Pipeline';
}

// ─────────────────────────────────────────────────────────────────────────────────
// MANUAL SEARCH MODE
// ─────────────────────────────────────────────────────────────────────────────────

function startFreshIndividualSearch() {
  reset();
  manualSearchInput.value = '';
  toggleManualMode(true);
  pipelineActions.classList.remove('visible');
  btnExportIndividual.disabled = true;
  setTimeout(() => manualSearchInput.focus(), 50);
}

async function processManualInput() {
  const raw = manualSearchInput.value.trim();
  if (!raw) {
    showError('Please enter a product name to search individually.');
    manualSearchInput.focus();
    return;
  }

  // CLIENT-SIDE: Detect prompt injection in manual input
  const injectionCheck = detectPromptInjection(raw);
  if (injectionCheck.suspicious) {
    showInjectionWarning(injectionCheck.reason);
    manualSearchInput.focus();
    return;
  }

  clearError();
  processingSummary.classList.remove('visible');
  btnManualSubmit.disabled = true;
  btnManualSubmit.classList.add('loading');
  _manualFirstResultDone = false;

  const manualTimerDisplay = document.getElementById('manualTimerDisplay');
  const startTime = performance.now();
  manualTimerDisplay.textContent = '0.0s';
  if (manualTimerInterval) clearInterval(manualTimerInterval);
  manualTimerInterval = setInterval(() => {
    manualTimerDisplay.textContent = ((performance.now() - startTime) / 1000).toFixed(1) + 's';
  }, 100);

  const fetchAbort = new AbortController();
  const fetchTimeoutId = setTimeout(() => fetchAbort.abort(), 10000);

  try {
    const response = await fetch('/upload-manual', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: raw }),
      signal: fetchAbort.signal
    });
    clearTimeout(fetchTimeoutId);

    const data = await response.json();
    if (!response.ok || data.error) {
      throw new Error(data.error || `Server error ${response.status}`);
    }

    const allItems = [...(data.sw_data || []), ...(data.hw_data || [])].map(item => ({
      ...item,
      'Hardware/Software': 'N.A'
    }));

    currentTableData.hw = [];
    currentTableData.sw = allItems;
    selectedRows.hw = new Set();
    selectedRows.sw = new Set();
    tableTotals.hw = 0;
    tableTotals.sw = 0;
    lastToggledRow.hw = null;
    lastToggledRow.sw = null;
    editedNames.hw = {};
    editedNames.sw = {};
    renderCurrentTables(false);

    currentFile = null;
    infoCard.classList.remove('visible');
    dropZone.classList.add('hidden');
    toggleManualMode(false);
    resetBoxFile.textContent = allItems.length === 1 ? (allItems[0]?.Name || '') : `${allItems.length} items`;
    resetBox.classList.add('visible');
    tablesContainer.classList.add('visible');

    manualAutoRunActive = true;
    startPipelineRun(true);
  } catch (err) {
    clearTimeout(fetchTimeoutId);
    if (err.name === 'AbortError') {
      showError('Request timed out. Please try again.');
    } else {
      showError('Processing failed: ' + err.message);
      tablesContainer.classList.remove('visible');
      processingSummary.classList.remove('visible');
    }
    manualAutoRunActive = false;
    stopManualSpinner();
  }
}

// ─────────────────────────────────────────────────────────────────────────────────
// TABLE RENDERING
// ─────────────────────────────────────────────────────────────────────────────────

function renderTable(data, headElement, bodyElement, type) {
  if (!data || data.length === 0) return false;

  const normalizedType = String(type || '').toLowerCase();
  const typeLabel = (normalizedType === 'hw' || normalizedType === 'hardware') ? 'hw' : 'sw';
  syncSelection(typeLabel, data.length, true);

  headElement.innerHTML = '';
  const hr = document.createElement('tr');
  ['', '', 'Name', 'Type', 'EOS Date', 'Confidence', ''].forEach((h, index) => {
    const th = document.createElement('th');
    if (index === 0) {
      const selectAll = document.createElement('input');
      selectAll.type = 'checkbox';
      selectAll.id = `select-all-${typeLabel}`;
      selectAll.className = 'select-all-checkbox';
      selectAll.title = 'Select all rows';
      selectAll.addEventListener('click', event => event.stopPropagation());
      selectAll.addEventListener('change', event => {
        const checked = event.target.checked;
        bodyElement.querySelectorAll('.row-select').forEach(checkbox => {
          checkbox.checked = checked;
        });
        selectedRows[typeLabel] = getCheckedRowIndices(typeLabel);
        lastToggledRow[typeLabel] = null;
        updateTableMeta(typeLabel);
        syncSelectAllState(typeLabel);
      });
      th.appendChild(selectAll);
    } else {
      th.textContent = h;
    }
    hr.appendChild(th);
  });
  headElement.appendChild(hr);

  bodyElement.innerHTML = '';
  data.forEach((row, i) => {
    const tr = document.createElement('tr');
    tr.className = 'expandable-row';
    tr.dataset.rowId = `row-${typeLabel}-${i}`;
    tr.tabIndex = 0;

    const tdSelect = document.createElement('td');
    tdSelect.className = 'select-cell';
    tdSelect.addEventListener('click', event => event.stopPropagation());
    const selectInput = document.createElement('input');
    selectInput.type = 'checkbox';
    selectInput.className = 'row-select';
    selectInput.checked = selectedRows[typeLabel].has(i);
    selectInput.dataset.type = typeLabel;
    selectInput.dataset.index = String(i);
    selectInput.title = `Select ${row.Name || ''}`;
    selectInput.addEventListener('click', event => {
      event.stopPropagation();
      const rowIndex = Number(event.target.dataset.index);
      const checked = event.target.checked;
      const previousIndex = lastToggledRow[typeLabel];

      if (event.shiftKey && previousIndex !== null) {
        applyRangeSelection(typeLabel, bodyElement, previousIndex, rowIndex, checked);
      } else {
        applyRowSelection(typeLabel, rowIndex, checked);
      }

      selectedRows[typeLabel] = getCheckedRowIndices(typeLabel);
      lastToggledRow[typeLabel] = rowIndex;
      updateTableMeta(typeLabel);
      syncSelectAllState(typeLabel);
    });
    tdSelect.appendChild(selectInput);
    tr.appendChild(tdSelect);
    
    const tdChevron = document.createElement('td');
    tdChevron.innerHTML = '<span class="row-chevron">▶</span>';
    tdChevron.style.width = '30px';
    tr.appendChild(tdChevron);
    
    const tdName = document.createElement('td');
    tdName.className = 'name-cell';
    tdName.title = row.Name || '';
    tdName.style.fontWeight = '500';

    const nameWrapper = document.createElement('div');
    nameWrapper.className = 'name-cell-wrapper';

    const nameSpan = document.createElement('span');
    nameSpan.className = 'name-text';
    nameSpan.textContent = row.Name || '';

    const editBtn = document.createElement('button');
    editBtn.className = 'edit-name-btn';
    editBtn.title = 'Edit name';
    editBtn.innerHTML = '<i class="ph ph-pencil-simple" style="font-size:0.85rem;"></i>';
    editBtn.addEventListener('click', event => {
      event.stopPropagation();
      startEditName(nameSpan, editBtn, tdName, typeLabel, i);
    });

    nameWrapper.appendChild(nameSpan);
    nameWrapper.appendChild(editBtn);
    tdName.appendChild(nameWrapper);
    tr.appendChild(tdName);
    
    const tdType = document.createElement('td');
    tdType.className = 'type-badge-cell';
    const typeStr = row['Hardware/Software'] || '';
    const normalizedTypeStr = String(typeStr).toLowerCase();
    const isBlank = !typeStr || normalizedTypeStr === 'n.a' || normalizedTypeStr === 'na' || normalizedTypeStr === 'unknown';
    const isSW = normalizedTypeStr.includes('software');
    const isHW = normalizedTypeStr.includes('hardware');
    if (isBlank || (!isSW && !isHW)) {
      tdType.innerHTML = `<span class="type-badge" style="opacity:0.3; border-color:rgba(128,128,128,0.3); color:var(--muted);">—</span>`;
    } else {
      tdType.innerHTML = `<span class="type-badge ${isSW ? 'sw' : 'hw'}">${isSW ? 'SW' : 'HW'}</span>`;
    }
    tr.appendChild(tdType);
    
    const tdEOS = document.createElement('td');
    tdEOS.className = 'eos-date-cell';
    tdEOS.textContent = row['EOS Date'] || 'N/A';
    tr.appendChild(tdEOS);
    
    const tdConfidence = document.createElement('td');
    tdConfidence.className = 'confidence-cell';
    const confidence = parseFloat(row.Confidence) || 0;
    const confWidth = Math.max(confidence * 100, 5);
    let confColor = 'low';
    if (confidence >= 0.8) confColor = 'high';
    else if (confidence >= 0.5) confColor = 'med';
    
    tdConfidence.innerHTML = `
      <div class="confidence-bar">
        <div class="confidence-track">
          <div class="confidence-fill ${confColor}" style="width: ${confWidth}%"></div>
        </div>
        <span class="confidence-score">${confidence.toFixed(2)}</span>
      </div>
    `;
    tr.appendChild(tdConfidence);

    const tdStatus = document.createElement('td');
    tdStatus.className = 'status-cell';
    tdStatus.id = `status-${typeLabel}-${i}`;
    tdStatus.innerHTML = `
      <div class="row-spinner" id="spinner-${typeLabel}-${i}"></div>
      <span class="row-status-icon" id="icon-${typeLabel}-${i}"></span>
    `;
    tr.appendChild(tdStatus);
    
    tr.addEventListener('click', () => toggleRow(tr, bodyElement, row, typeLabel, i));
    tr.addEventListener('keydown', event => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      if (event.target !== tr) return;
      event.preventDefault();
      toggleRow(tr, bodyElement, row, typeLabel, i);
    });
    
    bodyElement.appendChild(tr);

    const expandTr = document.createElement('tr');
    expandTr.className = 'expand-row';
    expandTr.id = `expand-${typeLabel}-${i}`;
    expandTr.style.display = 'none';
    
    const expandTd = document.createElement('td');
    expandTd.colSpan = 7;
    
    const summary = row.Summary || '';
    const supportModel = row['Support Model'] || 'N/A';
    const sourceUrls = row['Source URLs'] || [];
    const supportTiers = row['Support Tiers'] || [];
    
    expandTd.innerHTML = `
      <div class="expand-content-grid">
        <div>
          <div class="expand-section">
            <div class="expand-section-title">Executive Summary</div>
            <div class="expand-value">${summary || 'No summary available.'}</div>
          </div>
          
          <div class="expand-section">
            <div class="expand-section-title">Support Model</div>
            <div class="support-model-box">
              <div class="expand-value">${supportModel}</div>
            </div>
          </div>
          
          <div class="expand-section">
            <div class="expand-section-title">Sources</div>
            ${sourceUrls.length > 0
              ? `<div class="sources-list">${sourceUrls.map(u => {
                  let host = u;
                  try { host = new URL(u).hostname; } catch(_) {}
                  return `<a href="${u}" target="_blank" class="source-link">🔗 ${host}</a>`;
                }).join('')}</div>`
              : '<div class="expand-value" style="color: #666;">No sources available.</div>'
            }
          </div>
        </div>
        
        <div>
          <div class="expand-section">
            <div class="expand-section-title">Lifecycle Milestones</div>
            ${supportTiers.length > 0
              ? `<table class="tiers-table"><thead><tr><th>Tier</th><th>End Date</th></tr></thead><tbody>
                  ${supportTiers.map(t => `<tr><td>${t.Tier||''}</td><td>${t.EndDate||''}</td></tr>`).join('')}
                 </tbody></table>`
              : '<div class="expand-value" style="color:#666;">No milestones available.</div>'
            }
          </div>
        </div>
      </div>
    `;
    expandTr.appendChild(expandTd);
    bodyElement.appendChild(expandTr);
  });

  updateTableMeta(typeLabel);
  syncSelectAllState(typeLabel);

  return true;
}

function startEditName(nameSpan, editBtn, tdCell, typeKey, rowIndex) {
  const original = nameSpan.textContent;
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'name-edit-input';
  input.value = original;

  nameSpan.style.display = 'none';
  editBtn.style.display = 'none';
  tdCell.querySelector('.name-cell-wrapper').appendChild(input);
  input.focus();
  input.select();

  let committed = false;
  function commit() {
    if (committed) return;
    committed = true;
    const newName = input.value.trim() || original;
    nameSpan.textContent = newName;
    editedNames[typeKey][rowIndex] = newName;
    tdCell.title = newName;
    const checkbox = tdCell.closest('tr')?.querySelector('.row-select');
    if (checkbox) checkbox.title = `Select ${newName}`;
    nameSpan.style.display = '';
    editBtn.style.display = '';
    input.remove();
  }

  input.addEventListener('keydown', e => {
    if (e.key === 'Enter')  { e.preventDefault(); commit(); }
    if (e.key === 'Escape') { input.value = original; commit(); }
  });
  input.addEventListener('blur', commit);
  input.addEventListener('click', e => e.stopPropagation());
}

function toggleRow(rowElement, tableBody, rowData, type, index) {
  const expandId = `expand-${type}-${index}`;
  const expandRow = document.getElementById(expandId);
  const isExpanded = rowElement.classList.contains('row-expanded');
  
  tableBody.querySelectorAll('tr.row-expanded').forEach(r => {
    if (r !== rowElement) {
      r.classList.remove('row-expanded');
      const rowId = r.dataset.rowId;
      const idx = rowId.split('-').pop();
      const otherType = rowId.split('-')[1];
      const otherExpand = document.getElementById(`expand-${otherType}-${idx}`);
      if (otherExpand) otherExpand.style.display = 'none';
    }
  });

  if (isExpanded) {
    rowElement.classList.remove('row-expanded');
    if (expandRow) expandRow.style.display = 'none';
  } else {
    rowElement.classList.add('row-expanded');
    if (expandRow) expandRow.style.display = 'table-row';
  }
}

// ─────────────────────────────────────────────────────────────────────────────────
// PIPELINE TIMER
// ─────────────────────────────────────────────────────────────────────────────────

const pipelineTimer      = document.getElementById('pipelineTimer');
const pipelineTimerValue = document.getElementById('pipelineTimerValue');
let _timerStart = null;
let _timerRAF   = null;

function startTimer() {
  _timerStart = performance.now();
  pipelineTimer.classList.add('running');
  function tick() {
    const ms  = performance.now() - _timerStart;
    const m   = Math.floor(ms / 60000);
    const s   = Math.floor((ms % 60000) / 1000);
    const ds  = Math.floor((ms % 1000) / 100);
    pipelineTimerValue.textContent =
      String(m).padStart(2,'0') + ':' +
      String(s).padStart(2,'0') + '.' + ds;
    _timerRAF = requestAnimationFrame(tick);
  }
  _timerRAF = requestAnimationFrame(tick);
}

function stopTimer() {
  if (_timerRAF) cancelAnimationFrame(_timerRAF);
  pipelineTimer.classList.remove('running');
}

// ─────────────────────────────────────────────────────────────────────────────────
// ROW STATUS & PIPELINE HELPERS
// ─────────────────────────────────────────────────────────────────────────────────

async function refreshItemFromAPI(type, index, itemName) {
  const icon = document.getElementById(`icon-${type}-${index}`);
  if (!icon || !itemName) return;
  
  const originalChar = icon.textContent;
  icon.textContent = '↻';
  icon.style.color = '';
  icon.classList.add('refreshing');
  icon.disabled = true;
  
  try {
    const response = await fetch('/refresh-item', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_name: itemName,
        item_type: type
      })
    });
    
    const data = await response.json();
    
    if (!response.ok || data.error) {
      throw new Error(data.error || `Refresh failed`);
    }
    
    icon.classList.remove('refreshing');
    rowSetDone(type, index, data.result, false, 'api');
    
    const expandedRow = document.querySelector(`#expand-${type}-${index}`);
    if (expandedRow && expandedRow.style.display !== 'none') {
      const expandTd = expandedRow.querySelector('td');
      if (expandTd && data.result) {
        const summary     = data.result.Summary || '';
        const support     = data.result['Support Model'] || 'N/A';
        const urls        = data.result['Source URLs'] || [];
        const tiers       = data.result['Support Tiers'] || [];

        expandTd.querySelector('.expand-content-grid').innerHTML = `
          <div>
            <div class="expand-section">
              <div class="expand-section-title">Executive Summary</div>
              <div class="expand-value">${summary || 'No summary available.'}</div>
            </div>
            <div class="expand-section">
              <div class="expand-section-title">Support Model</div>
              <div class="support-model-box">
                <div class="expand-value">${support}</div>
              </div>
            </div>
            <div class="expand-section">
              <div class="expand-section-title">Sources</div>
              ${urls.length > 0
                ? `<div class="sources-list">${urls.map(u => {
                    let host = u;
                    try { host = new URL(u).hostname; } catch(_) {}
                    return `<a href="${u}" target="_blank" class="source-link">🔗 ${host}</a>`;
                  }).join('')}</div>`
                : '<div class="expand-value" style="color: #666;">No sources available.</div>'
              }
            </div>
          </div>`;
      }
    }
    
  } catch (err) {
    console.error('Refresh error:', err);
    showError('Failed to refresh: ' + err.message);
    
    icon.classList.remove('refreshing');
    icon.textContent = originalChar;
    icon.style.color = '#ffffff';
    icon.disabled = false;
  }
}

function rowSetSpinning(type, index) {
  const spinner = document.getElementById(`spinner-${type}-${index}`);
  const icon    = document.getElementById(`icon-${type}-${index}`);
  if (spinner) spinner.classList.add('active');
  if (icon)    { icon.textContent = ''; icon.classList.remove('visible'); }
}

function getConfidenceExplanation(score) {
  if (score >= 1.0) {
    return 'Direct exact date from current official vendor documentation.';
  } else if (score >= 0.9) {
    return 'Official documentation with broad timeframe OR 2+ reputable tech/analyst outlets agree on exact date.';
  } else if (score >= 0.7) {
    return 'Single reputable tech outlet OR verified vendor employee on official forum.';
  } else if (score >= 0.4) {
    return 'Third-party lifecycle aggregators without primary source OR consensus from IT forums.';
  } else {
    return 'Conflicting dates, AI-inferred lifecycle, or no credible data found.';
  }
}

function rowSetDone(type, index, result, fromCache = false, cachedFrom = 'api') {
  const spinner = document.getElementById(`spinner-${type}-${index}`);
  const icon    = document.getElementById(`icon-${type}-${index}`);
  if (spinner) spinner.classList.remove('active');
  if (icon) {
    let iconChar = '✓';
    let iconColor = '#2ecc71';
    let iconTitle = 'Processed by AI (fresh)';
    
    if (cachedFrom === 'database') {
      iconChar = '◈';
      iconColor = '#89b4fa';
      iconTitle = 'Cached — click to refresh from API';
    } else if (cachedFrom === 'memory') {
      iconChar = '◈';
      iconColor = '#cba6f7';
      iconTitle = 'Memory cached — click to refresh from API';
    }
    
    icon.textContent = iconChar;
    icon.style.color = iconColor;
    icon.title = iconTitle;
    icon.classList.add('visible');
    icon.setAttribute('data-cache-source', cachedFrom);
    
    if (cachedFrom !== 'api') {
      icon.classList.add('cached');
      icon.setAttribute('data-type', type);
      icon.setAttribute('data-index', index);
      icon.setAttribute('data-item-name', result?.Name || '');
      
      icon.onmouseenter = () => { if (!icon.classList.contains('refreshing')) { icon.textContent = iconChar + ' ↻'; } };
      icon.onmouseleave = () => { if (!icon.classList.contains('refreshing')) icon.textContent = iconChar; };
      icon.onclick     = (e) => { e.stopPropagation(); refreshItemFromAPI(type, index, result?.Name || ''); };
    } else {
      icon.onmouseenter = null;
      icon.onmouseleave = null;
      icon.onclick = null;
    }
  }

  if (!result) return;
  const tr = document.querySelector(`tr[data-row-id="row-${type}-${index}"]`);
  if (!tr) return;

  const tdEOS = tr.cells[4];
  if (tdEOS && result['EOS Date']) tdEOS.textContent = result['EOS Date'];

  const tdConf = tr.cells[5];
  if (tdConf && result.Confidence !== undefined) {
    const c = parseFloat(result.Confidence) || 0;
    const w = Math.max(c * 100, 5);
    const cls = c >= 0.8 ? 'high' : c >= 0.5 ? 'med' : 'low';
    const explanation = getConfidenceExplanation(c);
    tdConf.innerHTML = `
      <div class="confidence-bar" title="${explanation}" style="cursor:help;">
        <div class="confidence-track">
          <div class="confidence-fill ${cls}" style="width:${w}%"></div>
        </div>
        <span class="confidence-score">${c.toFixed(2)}</span>
      </div>`;
  }

  const expandTd = document.querySelector(`#expand-${type}-${index} td`);
  if (expandTd && result) {
    const summary     = result.Summary || '';
    const support     = result['Support Model'] || 'N/A';
    const urls        = result['Source URLs'] || [];
    const tiers       = result['Support Tiers'] || [];

    expandTd.querySelector('.expand-content-grid').innerHTML = `
      <div>
        <div class="expand-section">
          <div class="expand-section-title">Executive Summary</div>
          <div class="expand-value">${summary || 'No summary available.'}</div>
        </div>
        <div class="expand-section">
          <div class="expand-section-title">Support Model</div>
          <div class="support-model-box">
            <div class="expand-value">${support}</div>
          </div>
        </div>
        <div class="expand-section">
          <div class="expand-section-title">Sources</div>
          ${urls.length > 0
            ? `<div class="sources-list">${urls.map(u => {
                let host = u;
                try { host = new URL(u).hostname; } catch(_) {}
                return `<a href="${u}" target="_blank" class="source-link">🔗 ${host}</a>`;
              }).join('')}</div>`
            : '<div class="expand-value" style="color: #666;">No sources available.</div>'
          }
        </div>
      </div>
      <div>
        <div class="expand-section">
          <div class="expand-section-title">Lifecycle Milestones</div>
          ${tiers.length > 0
            ? `<table class="tiers-table"><thead><tr><th>Tier</th><th>End Date</th></tr></thead><tbody>
                ${tiers.map(t => `<tr><td>${t.Tier||''}</td><td>${t.EndDate||''}</td></tr>`).join('')}
               </tbody></table>`
            : '<div class="expand-value" style="color:#666;">No milestones available.</div>'
          }
        </div>
      </div>
    `;
  }
}

function rowSetError(type, index) {
  const spinner = document.getElementById(`spinner-${type}-${index}`);
  const icon    = document.getElementById(`icon-${type}-${index}`);
  if (spinner) spinner.classList.remove('active');
  if (icon)    { icon.textContent = '✕'; icon.style.color = '#ff5c38'; icon.classList.add('visible'); }
}

// ─────────────────────────────────────────────────────────────────────────────────
// PIPELINE TRIGGER & EVENTSOURCE
// ─────────────────────────────────────────────────────────────────────────────────

function startPipelineRun(autoFromManual = false) {
  commitAllOpenNameEdits();
  refreshSelectionFromDOM();

  if (selectedRows.hw.size === 0 && selectedRows.sw.size === 0) {
    showError('Please select at least one item before running the AI pipeline.');
    manualAutoRunActive = false;
    return;
  }

  btnTriggerPipeline.disabled = true;
  btnTriggerPipeline.querySelector('.pipeline-text').textContent = 'Pipeline Running…';
  clearError();
  startTimer();

  let liveCount = 0;
  let cachedCount = 0;

  let watchdog = null;
  const WATCHDOG_MS = 60000;
  function resetWatchdog() {
    if (!autoFromManual) return;
    if (watchdog) clearTimeout(watchdog);
    watchdog = setTimeout(() => {
      es.close();
      currentManualEs = null;
      stopManualSpinner();
      manualAutoRunActive = false;
      showError('Timeout Error: Please try again later.');
    }, WATCHDOG_MS);
  }
  function clearWatchdog() {
    if (watchdog) { clearTimeout(watchdog); watchdog = null; }
  }

  const es = new EventSource(buildPipelineUrl());
  if (autoFromManual) { currentManualEs = es; resetWatchdog(); }

  es.addEventListener('item-start', e => {
    const d = JSON.parse(e.data);
    rowSetSpinning(d.type, d.index);
    resetWatchdog();
  });

  es.addEventListener('item-done', e => {
    const d = JSON.parse(e.data);
    if (d.cached) {
      cachedCount++;
      rowSetDone(d.type, d.index, d.result, true, d.cached_from);
    } else {
      liveCount++;
      rowSetDone(d.type, d.index, d.result, false, d.cached_from);
    }
    if (manualAutoRunActive || autoFromManual) {
      routeManualResultToTable(d);
    }
    resetWatchdog();
  });

  es.addEventListener('item-error', e => {
    const d = JSON.parse(e.data);
    rowSetError(d.type, d.index);
    if (isApiKeyError(d.error)) showApiKeyToast();
    console.warn('Pipeline item error:', d.error);
  });

  es.addEventListener('pipeline-done', e => {
    const d = JSON.parse(e.data);
    stopTimer();
    es.close();
    clearWatchdog();
    btnTriggerPipeline.disabled = false;
    btnExportIndividual.disabled = false;
    const parts = [`${d.processed}/${d.total} items`];
    if (cachedCount > 0) parts.push(`${cachedCount} from cache`);
    if (liveCount > 0)   parts.push(`${liveCount} via API`);
    btnTriggerPipeline.querySelector('.pipeline-text').textContent = `✓ Complete — ${parts.join(' · ')}`;
    pipelineTimerValue.textContent += ' ✓';
    if (autoFromManual) { currentManualEs = null; stopManualSpinner(); }
    manualAutoRunActive = false;
  });

  es.addEventListener('pipeline-error', e => {
    const d = JSON.parse(e.data);
    stopTimer();
    es.close();
    clearWatchdog();
    showError('Pipeline error: ' + d.error);
    btnTriggerPipeline.disabled = false;
    btnTriggerPipeline.querySelector('.pipeline-text').textContent = 'Trigger AI Intelligence Pipeline';
    if (autoFromManual) { currentManualEs = null; stopManualSpinner(); }
    manualAutoRunActive = false;
  });

  es.onerror = () => {
    stopTimer();
    es.close();
    clearWatchdog();
    showError('Lost connection to pipeline. Please try again.');
    btnTriggerPipeline.disabled = false;
    btnTriggerPipeline.querySelector('.pipeline-text').textContent = 'Trigger AI Intelligence Pipeline';
    if (autoFromManual) { currentManualEs = null; stopManualSpinner(); }
    manualAutoRunActive = false;
  };
}

// ─────────────────────────────────────────────────────────────────────────────────
// EVENT LISTENERS
// ─────────────────────────────────────────────────────────────────────────────────

window.addEventListener('load', () => {
  const savedTheme = localStorage.getItem('theme') || 'dark';
  if (savedTheme === 'light') {
    document.body.classList.add('light-mode');
    themeIcon.textContent = '☀️';
    themeLabel.textContent = 'light';
  }
});

themeToggle.addEventListener('click', () => {
  if (themeToggle.classList.contains('disabled')) return;
  const isLightMode = document.body.classList.toggle('light-mode');
  if (isLightMode) {
    themeIcon.textContent = '☀️';
    themeLabel.textContent = 'light';
    localStorage.setItem('theme', 'light');
  } else {
    themeIcon.textContent = '🌙';
    themeLabel.textContent = 'dark';
    localStorage.setItem('theme', 'dark');
  }
});

fileInput.addEventListener('change', e => {
  if (e.target.files.length) { currentFile = e.target.files[0]; setFileInfo(currentFile); }
});

btnSearchIndividually.addEventListener('click', () => {
  if (manualMode) {
    reset();
  } else {
    startFreshIndividualSearch();
  }
});

btnExportIndividual.addEventListener('click', async () => {
  try {
    btnExportIndividual.disabled = true;
    const textSpan = btnExportIndividual.querySelector('span:last-child');
    textSpan.textContent = 'Exporting...';

    const response = await fetch('/export-csv');
    if (!response.ok) {
      const error = await response.json();
      showError(error.error || 'Failed to export CSV');
      return;
    }

    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    
    const contentDisposition = response.headers.get('Content-Disposition');
    let filename = 'eos_results.csv';
    if (contentDisposition) {
      const match = contentDisposition.match(/filename[^;=\n]*=([^;\n]*)/);
      if (match[1]) filename = match[1].trim().replace(/^"(.+)"$/, '$1');
    }
    
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(url);

    clearError();
  } catch (error) {
    showError('Error exporting CSV: ' + error.message);
  } finally {
    btnExportIndividual.disabled = false;
    btnExportIndividual.querySelector('span:last-child').textContent = 'Export';
  }
});

btnManualSubmit.addEventListener('click', processManualInput);

manualSearchInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    processManualInput();
  }
});

dropZone.addEventListener('dragover', e => {
  if (manualMode) return;
  e.preventDefault();
  dropZone.classList.add('dragover');
});

dropZone.addEventListener('dragleave', () => {
  if (manualMode) return;
  dropZone.classList.remove('dragover');
});

dropZone.addEventListener('drop', e => {
  if (manualMode) return;
  e.preventDefault();
  dropZone.classList.remove('dragover');
  if (e.dataTransfer.files.length) { currentFile = e.dataTransfer.files[0]; setFileInfo(currentFile); }
});

btnResetCompact.addEventListener('click', reset);

btnTriggerPipeline.addEventListener('click', () => startPipelineRun(false));

// ─────────────────────────────────────────────────────────────────────────────────
// AI CHAT BUTTON & MODAL
// ─────────────────────────────────────────────────────────────────────────────────

// Wait for DOM to be ready before setting up AI chat listeners
function initAIChat() {
  if (!aiChatBtn || !aiChatModal || !aiChatClose) {
    console.warn('AI Chat elements not found');
    return;
  }

  // Restore modal state on page load
  const isOpen = localStorage.getItem('aiChatOpen') === 'true';
  if (isOpen) {
    aiChatModal.classList.add('active');
  }

  // Toggle AI chat modal
  aiChatBtn.addEventListener('click', (e) => {
    e.preventDefault();
    const isActive = aiChatModal.classList.contains('active');
    if (isActive) {
      aiChatModal.classList.remove('active');
      localStorage.setItem('aiChatOpen', 'false');
    } else {
      aiChatModal.classList.add('active');
      localStorage.setItem('aiChatOpen', 'true');
    }
  });

  // Close button
  aiChatClose.addEventListener('click', (e) => {
    e.preventDefault();
    aiChatModal.classList.remove('active');
    localStorage.setItem('aiChatOpen', 'false');
  });

  // Close modal when clicking outside the container
  aiChatModal.addEventListener('click', (e) => {
    if (e.target === aiChatModal) {
      aiChatModal.classList.remove('active');
      localStorage.setItem('aiChatOpen', 'false');
    }
  });

  // ───────────────────────────────────────────────────────────────────
  // AI CHAT MESSAGE SENDING WITH INJECTION PREVENTION
  // ───────────────────────────────────────────────────────────────────
  
  const aiChatInput = document.getElementById('aiChatInput');
  const aiChatSend = document.getElementById('aiChatSend');
  const aiChatContent = document.getElementById('aiChatContent');
  const aiChatClear = document.getElementById('aiChatClear');
  
  if (aiChatInput && aiChatSend) {
    async function sendChatMessage() {
      const message = aiChatInput.value.trim();
      
      if (!message) {
        return;
      }
      
      // CLIENT-SIDE: Detect prompt injection in chat message
      const injectionCheck = detectPromptInjection(message);
      if (injectionCheck.suspicious) {
        // Show warning in AI chat instead of main error box
        const warningBubble = document.createElement('div');
        warningBubble.className = 'ai-bubble ai-bubble-ai';
        warningBubble.innerHTML = `
          <p style="color: #ff6b6b; font-weight: 500;">⚠️ Security: ${injectionCheck.reason}</p>
          <p style="margin-top: 8px; font-size: 0.9em; opacity: 0.8;">Please ask a legitimate question about product EOS/EOL dates.</p>
          <span class="ai-bubble-time">${new Date().toLocaleTimeString()}</span>
        `;
        aiChatContent.appendChild(warningBubble);
        aiChatContent.scrollTop = aiChatContent.scrollHeight;
        aiChatInput.value = '';
        return;
      }
      
      // Add user message to chat
      const userBubble = document.createElement('div');
      userBubble.className = 'ai-bubble ai-bubble-user';
      userBubble.innerHTML = `
        <p>${escapeHtml(message)}</p>
        <span class="ai-bubble-time">${new Date().toLocaleTimeString()}</span>
      `;
      aiChatContent.appendChild(userBubble);
      aiChatContent.scrollTop = aiChatContent.scrollHeight;
      
      aiChatInput.value = '';
      aiChatSend.disabled = true;
      aiChatSend.textContent = 'Sending...';
      
      try {
        const response = await fetch('/chat/send', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: message })
        });
        
        const data = await response.json();
        
        // Handle different response scenarios
        if (response.status === 429) {
          // Token limit reached
          const limitBubble = document.createElement('div');
          limitBubble.className = 'ai-bubble ai-bubble-ai';
          limitBubble.innerHTML = `
            <p style="color: #ffa94d;">⚠️ ${data.error}</p>
            <span class="ai-bubble-time">${new Date().toLocaleTimeString()}</span>
          `;
          aiChatContent.appendChild(limitBubble);
        } else if (!response.ok || data.error) {
          const errorBubble = document.createElement('div');
          errorBubble.className = 'ai-bubble ai-bubble-ai';
          errorBubble.innerHTML = `
            <p style="color: #ff6b6b;">❌ ${escapeHtml(data.error || 'Error processing message')}</p>
            <span class="ai-bubble-time">${new Date().toLocaleTimeString()}</span>
          `;
          aiChatContent.appendChild(errorBubble);
        } else {
          // Show AI response
          const aiBubble = document.createElement('div');
          aiBubble.className = 'ai-bubble ai-bubble-ai';
          const responseText = data.response || 'No response from AI';
          aiBubble.innerHTML = `
            <p>${escapeHtml(responseText)}</p>
            <span class="ai-bubble-time">${new Date().toLocaleTimeString()}</span>
          `;
          aiChatContent.appendChild(aiBubble);
          
          // Show warning if approaching token limit
          if (data.token_warning) {
            const warningBubble = document.createElement('div');
            warningBubble.className = 'ai-bubble ai-bubble-ai';
            warningBubble.innerHTML = `
              <p style="font-size: 0.9em; opacity: 0.8;">⚠️ Conversation getting long (${data.conversation_tokens}/${data.token_limit} tokens). Consider starting a new chat soon.</p>
              <span class="ai-bubble-time">${new Date().toLocaleTimeString()}</span>
            `;
            aiChatContent.appendChild(warningBubble);
          }
        }
        
        aiChatContent.scrollTop = aiChatContent.scrollHeight;
      } catch (err) {
        const errorBubble = document.createElement('div');
        errorBubble.className = 'ai-bubble ai-bubble-ai';
        errorBubble.innerHTML = `
          <p style="color: #ff6b6b;">❌ Connection error: ${escapeHtml(err.message)}</p>
          <span class="ai-bubble-time">${new Date().toLocaleTimeString()}</span>
        `;
        aiChatContent.appendChild(errorBubble);
        aiChatContent.scrollTop = aiChatContent.scrollHeight;
      } finally {
        aiChatSend.disabled = false;
        aiChatSend.textContent = 'Send';
        aiChatInput.focus();
      }
    }
    
    aiChatSend.addEventListener('click', sendChatMessage);
    
    aiChatInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendChatMessage();
      }
    });
  }
  
  // Clear chat history
  if (aiChatClear) {
    aiChatClear.addEventListener('click', async () => {
      try {
        const response = await fetch('/chat/clear', { method: 'POST' });
        if (response.ok) {
          // Reset chat UI
          if (aiChatContent) {
            aiChatContent.innerHTML = `
              <div class="ai-chat-day">Today</div>
              <div class="ai-bubble ai-bubble-ai" id="aiWelcomeBubble">
                <p>Hi, I can help with EOS/EOL questions about your assets. What would you like to check?</p>
                <span class="ai-bubble-time" id="aiWelcomeTime">${new Date().toLocaleTimeString()}</span>
              </div>
            `;
          }
          if (aiChatInput) aiChatInput.focus();
        }
      } catch (err) {
        console.error('Clear chat error:', err);
      }
    });
  }
}

// Helper function to escape HTML in chat messages
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Initialize AI chat when script loads
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initAIChat);
} else {
  initAIChat();
}
