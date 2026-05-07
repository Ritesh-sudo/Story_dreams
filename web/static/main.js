/* ══════════════════════════════════════════════════════════════════
   Bedtime Story Generator — vanilla JS frontend
   ══════════════════════════════════════════════════════════════════ */

// ── Application state ─────────────────────────────────────────────
const state = {
  age: 7,
  story: '',
  narratorStory: '',
  judgment: null,
  category: '',
  originalRequest: '',
  showingNarrator: false,
  storyId: '',
  audioPlaying: false,
};

// ── DOM refs ──────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

const progressBar   = $('progress-bar');
const storyForm     = $('story-form');
const generateBtn   = $('generate-btn');
const formError     = $('form-error');
const viewLanding   = $('view-landing');
const viewGenerating= $('view-generating');
const viewStory     = $('view-story');
const storyText     = $('story-text');
const narratorText  = $('narrator-text');
const scorePill     = $('score-pill');
const categoryTag   = $('story-category-tag');
const narratorToggle= $('narrator-toggle');
const newStoryBtn   = $('new-story-btn');
const feedbackInput = $('feedback-input');
const reviseBtn     = $('revise-btn');
const reviseLoading = $('revise-loading');

// ── Progress bar helpers ──────────────────────────────────────────
function setProgress(pct) {
  progressBar.classList.add('active');
  progressBar.style.width = `${pct}%`;
}
function completeProgress() {
  progressBar.style.width = '100%';
  setTimeout(() => {
    progressBar.classList.remove('active');
    progressBar.style.width = '0%';
  }, 600);
}

// ── View switching ────────────────────────────────────────────────
function showView(name) {
  viewLanding.classList.toggle('view-hidden', name !== 'landing');
  viewGenerating.classList.toggle('view-hidden', name !== 'generating');
  viewStory.classList.toggle('view-hidden', name !== 'story');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ── Age pill selection ────────────────────────────────────────────
document.querySelectorAll('.age-pill').forEach(pill => {
  pill.addEventListener('click', () => {
    document.querySelectorAll('.age-pill').forEach(p =>
      p.classList.remove('age-pill-selected')
    );
    pill.classList.add('age-pill-selected');
    state.age = parseInt(pill.dataset.age, 10);
  });
});

// ── Quick feedback pills ──────────────────────────────────────────
document.querySelectorAll('.quick-pill').forEach(pill => {
  pill.addEventListener('click', () => {
    document.querySelectorAll('.quick-pill').forEach(p => p.classList.remove('active'));
    pill.classList.add('active');
    feedbackInput.value = pill.dataset.feedback;
    feedbackInput.focus();
  });
});

// Clear the active pill when the user edits the text themselves
feedbackInput.addEventListener('input', () => {
  document.querySelectorAll('.quick-pill').forEach(p => p.classList.remove('active'));
});

// ── Step helpers ──────────────────────────────────────────────────
const STEP_PROGRESS = { guard: 10, classify: 25, plan: 45, write: 65, judge: 82, revise: 90 };

function activateStep(stepName) {
  const el = document.querySelector(`[data-step="${stepName}"]`);
  if (!el) return;
  el.classList.remove('step-pending');
  // Hide dot, show spinner
  const dot = el.querySelector('.step-dot');
  const spinner = el.querySelector('.step-spinner');
  if (dot) dot.hidden = true;
  if (spinner) spinner.hidden = false;
  setProgress(STEP_PROGRESS[stepName] || 50);
}

function completeStep(stepName, detailHTML = '') {
  const el = document.querySelector(`[data-step="${stepName}"]`);
  if (!el) return;
  const spinner = el.querySelector('.step-spinner');
  const check   = el.querySelector('.step-check');
  if (spinner) spinner.hidden = true;
  if (check) check.hidden = false;
  const detail = $(`step-detail-${stepName}`);
  if (detail && detailHTML) detail.innerHTML = detailHTML;
}

// ── Generate form submit ──────────────────────────────────────────
storyForm.addEventListener('submit', async e => {
  e.preventDefault();

  const prompt     = $('story-prompt').value.trim();
  const category   = $('story-category').value;
  const childName  = $('child-name').value.trim();

  if (!prompt) {
    formError.textContent = "Please describe the story you'd like.";
    formError.hidden = false;
    return;
  }
  formError.hidden = true;

  state.originalRequest = prompt;
  state.showingNarrator = false;
  state.storyId = '';

  generateBtn.disabled = true;
  generateBtn.textContent = 'Generating…';

  // Reset all steps to pending state
  document.querySelectorAll('.pipeline-step').forEach(step => {
    step.classList.add('step-pending');
    const spinner = step.querySelector('.step-spinner');
    const check   = step.querySelector('.step-check');
    const dot     = step.querySelector('.step-dot');
    if (spinner) spinner.hidden = true;
    if (check)   check.hidden = true;
    if (dot)     dot.hidden = false;
    const name = step.dataset.step;
    const detail = $(`step-detail-${name}`);
    if (detail) detail.innerHTML = '';
  });
  $('step-revise').hidden = true;
  $('scores-preview').hidden = true;
  $('guard-blocked-msg').hidden = true;
  $('pipeline-steps').hidden = false;

  showView('generating');
  setProgress(5);
  activateStep('guard');

  try {
    await streamGenerate(prompt, state.age, category, childName);
  } catch (err) {
    showView('landing');
    formError.textContent = `Error: ${err.message}`;
    formError.hidden = false;
  }

  generateBtn.disabled = false;
  generateBtn.textContent = 'Generate';
});

// ── SSE stream reader ─────────────────────────────────────────────
async function streamGenerate(prompt, age, category, childName = '') {
  const response = await fetch('/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, age, category, child_name: childName }),
  });

  if (!response.ok) {
    throw new Error(`Server error: ${response.status}`);
  }

  const reader  = response.body.getReader();
  const decoder = new TextDecoder();
  let   buffer  = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop(); // keep incomplete line in buffer

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const event = JSON.parse(line.slice(6));
          handleSSEEvent(event);
        } catch (_) { /* skip malformed lines */ }
      }
    }
  }
}

function handleSSEEvent(event) {
  const { step, type, data } = event;

  if (type === 'error') {
    throw new Error(data.message || 'Unknown error');
  }

  if (type === 'start') {
    if (step === 'revise') $('step-revise').hidden = false;
    activateStep(step);
    return;
  }

  // Guard blocked — show friendly message, go back to form
  if (step === 'guard' && type === 'blocked') {
    completeProgress();
    $('pipeline-steps').hidden = true;
    const msg = data.child_message ||
      "That topic isn't quite right for a bedtime story. Try something like a brave animal, a magical adventure, or a peaceful night under the stars.";
    $('guard-blocked-text').textContent = msg;
    $('guard-blocked-msg').hidden = false;
    return;
  }

  if (type === 'complete') {
    if (step === 'guard') {
      if (data.verdict === 'reframe') {
        completeStep('guard', 'Adjusted for bedtime');
      } else {
        completeStep('guard', 'All good');
      }
      activateStep('classify');
    }

    if (step === 'classify') {
      const label = (data.category || '').replace(/_/g, ' ');
      completeStep('classify', `<span class="category-badge">${label}</span>`);
      activateStep('plan');
    }

    if (step === 'plan') {
      const title = data.outline?.title || '';
      completeStep('plan', title ? `"${escapeHTML(title)}"` : '');
      activateStep('write');
    }

    if (step === 'write') {
      completeStep('write', 'Story written');
      activateStep('judge');
    }

    if (step === 'revise') {
      completeStep('revise');
    }

    if (step === 'judge') {
      const j = data.judgment || {};
      const score = typeof j.overall_score === 'number'
        ? j.overall_score.toFixed(1) : '—';
      completeStep('judge', `Score: ${score} / 10`);
      revealScores(j);
      setProgress(95);
    }

    if (step === 'complete') {
      state.story          = data.story || '';
      state.narratorStory  = data.narrator_story || data.story || '';
      state.judgment       = data.judgment || {};
      state.category       = data.category || '';
      state.storyId        = data.story_id || '';

      completeProgress();
      renderStoryView();
      showView('story');
      // Story view was display:none when the page loaded, so the observer
      // never saw its .reveal elements. Run a fresh pass now that it's visible.
      requestAnimationFrame(() => observeRevealElements($('view-story')));
    }
  }
}

// ── Score card animation ──────────────────────────────────────────
function revealScores(judgment) {
  const preview = $('scores-preview');
  preview.hidden = false;

  const scores = judgment.scores || {};
  document.querySelectorAll('.score-card').forEach(card => {
    const dim    = card.dataset.dim;
    const target = scores[dim]?.score ?? 0;
    const el     = card.querySelector('.score-card-value');

    let current = 0;
    const duration = 900;
    const start   = performance.now();

    function tick(now) {
      const progress = Math.min((now - start) / duration, 1);
      // ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      current = eased * target;
      el.textContent = current.toFixed(1);
      if (progress < 1) requestAnimationFrame(tick);
      else el.textContent = target.toFixed(1);
    }
    requestAnimationFrame(tick);
  });
}

// ── Story rendering ───────────────────────────────────────────────
// wordIndex is shared across paragraphs so span data-idx matches word_timings array
let _storyWordCount = 0;

// Caller must reset _storyWordCount before calling so title + body share one index sequence
function formatStoryHTML(text) {
  const paras = text.split(/\n{2,}/);
  return paras
    .map(p => {
      const trimmed = p.trim();
      if (!trimmed) return '';
      const wrapped = escapeHTML(trimmed).replace(/\S+/g, token =>
        `<span class="story-word" data-idx="${_storyWordCount++}">${token}</span>`
      );
      return `<p>${wrapped}</p>`;
    })
    .filter(Boolean)
    .join('\n');
}

function formatNarratorHTML(text) {
  const cueRe = /\[(pause long|pause|whisper)\]/gi;
  const paras = text.split(/\n{2,}/);
  return paras
    .map(p => {
      const trimmed = p.trim();
      if (!trimmed) return '';
      const withCues = escapeHTML(trimmed).replace(
        /\[(pause long|pause|whisper)\]/gi,
        (_m, cue) => `<span class="narrator-cue">[${cue}]</span>`
      );
      return `<p>${withCues}</p>`;
    })
    .filter(Boolean)
    .join('\n');
}

// Splits raw story text into {title, body}, skipping any leading blank lines.
function splitTitleBody(text) {
  const lines = text.split('\n');
  let titleIdx = -1;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim()) { titleIdx = i; break; }
  }
  if (titleIdx === -1) return { title: '', body: text.trim() };
  const title = lines[titleIdx].trim();
  const body  = lines.slice(titleIdx + 1).join('\n').trim();
  return { title, body };
}

function renderStoryView() {
  const j = state.judgment || {};

  // Category tag
  categoryTag.textContent = (state.category || '').replace(/_/g, ' ').toUpperCase();

  // Score pill
  const score = typeof j.overall_score === 'number' ? j.overall_score.toFixed(1) : '—';
  scorePill.textContent = `${score} / 10`;

  // Story body — title + body share the same word-span index sequence
  // so TTS word_timings indices align with data-idx on every span.
  _storyWordCount = 0;
  const { title, body } = splitTitleBody(state.story);
  const titleHTML = title
    ? `<p class="story-title">${
        escapeHTML(title).replace(/\S+/g, token =>
          `<span class="story-word" data-idx="${_storyWordCount++}">${token}</span>`
        )
      }</p>`
    : '';
  storyText.innerHTML = titleHTML + formatStoryHTML(body);

  // Narrator version
  const { title: nTitle, body: nBody } = splitTitleBody(state.narratorStory);
  const nTitleHTML = nTitle
    ? `<p class="story-title">${escapeHTML(nTitle)}</p>`
    : '';
  narratorText.innerHTML = nTitleHTML + formatNarratorHTML(nBody);

  // Reset narrator toggle
  state.showingNarrator = false;
  narratorText.hidden = true;
  storyText.hidden = false;
  narratorToggle.textContent = 'Read aloud →';

  // Reset vocabulary chat for the new story
  resetVocab();

  // Trigger scroll-reveal for feedback section
  revealObserver.observe(document.querySelector('.feedback-section'));
}

// ── Narrator toggle ───────────────────────────────────────────────
narratorToggle.addEventListener('click', () => {
  state.showingNarrator = !state.showingNarrator;
  storyText.hidden = state.showingNarrator;
  narratorText.hidden = !state.showingNarrator;
  narratorToggle.textContent = state.showingNarrator
    ? 'Hide cues ↑'
    : 'Read aloud →';
});

// ── Guard "try again" button ──────────────────────────────────────
$('guard-try-again-btn').addEventListener('click', () => {
  generateBtn.disabled = false;
  generateBtn.textContent = 'Generate';
  showView('landing');
  setTimeout(() => $('create').scrollIntoView({ behavior: 'smooth' }), 100);
});

// ── New story button ──────────────────────────────────────────────
newStoryBtn.addEventListener('click', () => {
  $('story-prompt').value = '';
  feedbackInput.value = '';
  showView('landing');
  setTimeout(() => $('create').scrollIntoView({ behavior: 'smooth' }), 100);
});

// ── Nav anchor links — work from any view ─────────────────────────
// #how-it-works and #create are inside view-landing (display:none when
// not on the landing page), so native anchor scrolling fails. Intercept
// them, restore the landing view first, then scroll.
document.querySelectorAll('a[href^="#"]').forEach(link => {
  link.addEventListener('click', e => {
    const targetId = link.getAttribute('href').slice(1);
    const target = document.getElementById(targetId);
    if (!target) return;
    e.preventDefault();
    if (historyPanel.classList.contains('open')) closeHistory();
    showView('landing');
    setTimeout(() => target.scrollIntoView({ behavior: 'smooth' }), 80);
  });
});

// ── Revise (feedback loop) ────────────────────────────────────────
const feedbackForm = document.querySelector('.feedback-form');

function showReviseLoading() {
  reviseLoading.hidden = false;
  // Double rAF: first frame removes display:none, second triggers the CSS transition
  requestAnimationFrame(() => requestAnimationFrame(() => {
    reviseLoading.classList.add('visible');
  }));
}

function hideReviseLoading() {
  reviseLoading.classList.remove('visible');
  // Wait for transition to finish before collapsing out of layout
  setTimeout(() => { reviseLoading.hidden = true; }, 360);
}

reviseBtn.addEventListener('click', async () => {
  const feedback = feedbackInput.value.trim();
  if (!feedback) return;

  // ── Enter loading state ────────────────────────────────────────
  reviseBtn.disabled = true;
  reviseBtn.classList.add('is-loading');
  feedbackInput.disabled = true;
  feedbackForm.classList.add('is-loading');
  document.querySelectorAll('.quick-pill').forEach(p => p.classList.remove('active'));
  showReviseLoading();

  try {
    const res = await fetch('/revise', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        story: state.story,
        feedback,
        original_request: state.originalRequest,
        age: state.age,
      }),
    });

    if (!res.ok) throw new Error(`Server error: ${res.status}`);
    const data = await res.json();

    // ── Fade out story + score pill ────────────────────────────────
    storyText.classList.add('is-fading');
    narratorText.classList.add('is-fading');
    scorePill.classList.add('is-updating');
    await new Promise(r => setTimeout(r, 290));

    // ── Swap in the new content ────────────────────────────────────
    state.story         = data.story || state.story;
    state.narratorStory = data.narrator_story || data.story || state.story;
    state.judgment      = data.judgment || state.judgment;
    renderStoryView();
    feedbackInput.value = '';

    // ── Fade new content back in ───────────────────────────────────
    requestAnimationFrame(() => {
      storyText.classList.remove('is-fading');
      narratorText.classList.remove('is-fading');
      scorePill.classList.remove('is-updating');
    });

    window.scrollTo({ top: 0, behavior: 'smooth' });

  } catch (err) {
    // Restore visibility if something failed mid-fade
    storyText.classList.remove('is-fading');
    narratorText.classList.remove('is-fading');
    scorePill.classList.remove('is-updating');
    alert(`Could not revise story: ${err.message}`);
  } finally {
    // ── Exit loading state ─────────────────────────────────────────
    reviseBtn.disabled = false;
    reviseBtn.classList.remove('is-loading');
    feedbackInput.disabled = false;
    feedbackForm.classList.remove('is-loading');
    hideReviseLoading();
  }
});

// ── Scroll-reveal (IntersectionObserver) ─────────────────────────
// Observe each .reveal element directly (not parent sections).
// threshold:0 fires as soon as any pixel enters the viewport.
// rootMargin bottom offset triggers the animation slightly before
// the element reaches the bottom edge, so it feels responsive.
const revealObserver = new IntersectionObserver(
  entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        revealObserver.unobserve(entry.target); // only animate once
      }
    });
  },
  { threshold: 0, rootMargin: '0px 0px -48px 0px' }
);

function observeRevealElements(root = document) {
  root.querySelectorAll('.reveal').forEach(el => {
    // If already in the viewport (e.g. page just loaded), show immediately
    const rect = el.getBoundingClientRect();
    if (rect.top < window.innerHeight - 48) {
      el.classList.add('visible');
    } else {
      revealObserver.observe(el);
    }
  });
}

// Initial pass over the landing page
observeRevealElements();

// ── Utility ───────────────────────────────────────────────────────
function escapeHTML(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── TTS — Edge Neural TTS with word highlighting + playback controls ──
const ttsListenBtn   = $('tts-listen-btn');
const ttsPlayer      = $('tts-player');
const ttsRestartBtn  = $('tts-restart-btn');
const ttsPlayPauseBtn= $('tts-playpause-btn');
const ttsPauseIcon   = $('tts-pause-icon');
const ttsPlayIcon    = $('tts-play-icon');
const ttsStopBtn     = $('tts-stop-btn');

let _ttsAudio    = null;
let _wordTimings = [];
let _activeIdx   = -1;

// ── word highlight sync ───────────────────────────────────────────
function _syncHighlight() {
  if (!_ttsAudio || !_wordTimings.length) return;
  const ms = _ttsAudio.currentTime * 1000;
  let idx = _activeIdx;
  while (idx + 1 < _wordTimings.length && _wordTimings[idx + 1].start_ms <= ms) idx++;
  if (idx === _activeIdx) return;
  _activeIdx = idx;
  storyText.querySelectorAll('.story-word.word-active')
    .forEach(el => el.classList.remove('word-active'));
  if (idx >= 0) {
    const span = storyText.querySelector(`.story-word[data-idx="${idx}"]`);
    if (span) {
      span.classList.add('word-active');
      span.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }
}

function _clearHighlight() {
  _activeIdx = -1;
  storyText.querySelectorAll('.story-word.word-active')
    .forEach(el => el.classList.remove('word-active'));
}

// ── player UI helpers ─────────────────────────────────────────────
function _showPlayer() {
  ttsListenBtn.hidden = true;
  ttsPlayer.hidden    = false;
}

function _hidePlayer() {
  ttsPlayer.hidden    = true;
  ttsListenBtn.hidden = false;
  ttsListenBtn.disabled = false;
  ttsListenBtn.classList.remove('tts-loading');
}

function _setPlayingUI(playing) {
  ttsPauseIcon.hidden = !playing;
  ttsPlayIcon.hidden  =  playing;
  ttsPlayPauseBtn.title = playing ? 'Pause' : 'Play';
  ttsPlayPauseBtn.classList.toggle('tts-playpause-active', playing);
}

// ── listen button — fetches audio and starts playback ─────────────
ttsListenBtn.addEventListener('click', async () => {
  ttsListenBtn.disabled = true;
  ttsListenBtn.classList.add('tts-loading');

  try {
    const body = state.storyId ? { story_id: state.storyId } : { text: state.story };
    const res  = await fetch('/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
      throw new Error(err.detail || `Server error ${res.status}`);
    }

    const data   = await res.json();
    _wordTimings = data.word_timings || [];
    _activeIdx   = -1;

    const raw   = atob(data.audio_b64);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    _ttsAudio   = new Audio(URL.createObjectURL(new Blob([bytes], { type: 'audio/mpeg' })));

    _ttsAudio.addEventListener('timeupdate', _syncHighlight);
    _ttsAudio.addEventListener('ended', () => {
      state.audioPlaying = false;
      _clearHighlight();
      _setPlayingUI(false);
    });

    _ttsAudio.play();
    state.audioPlaying = true;
    _showPlayer();
    _setPlayingUI(true);

  } catch (err) {
    ttsListenBtn.disabled = false;
    ttsListenBtn.classList.remove('tts-loading');
    alert(`Could not generate audio: ${err.message}`);
  }
});

// ── play / pause ──────────────────────────────────────────────────
ttsPlayPauseBtn.addEventListener('click', () => {
  if (!_ttsAudio) return;
  if (state.audioPlaying) {
    _ttsAudio.pause();
    state.audioPlaying = false;
    _setPlayingUI(false);
  } else {
    _ttsAudio.play();
    state.audioPlaying = true;
    _setPlayingUI(true);
  }
});

// ── restart ───────────────────────────────────────────────────────
ttsRestartBtn.addEventListener('click', () => {
  if (!_ttsAudio) return;
  _ttsAudio.currentTime = 0;
  _activeIdx = -1;
  _clearHighlight();
  _ttsAudio.play();
  state.audioPlaying = true;
  _setPlayingUI(true);
});

// ── stop — clears audio and returns to listen button ─────────────
ttsStopBtn.addEventListener('click', () => {
  if (_ttsAudio) { _ttsAudio.pause(); _ttsAudio.currentTime = 0; }
  state.audioPlaying = false;
  _clearHighlight();
  _hidePlayer();
});

// ── reset when a new story loads ──────────────────────────────────
function resetTTS() {
  if (_ttsAudio) { _ttsAudio.pause(); _ttsAudio = null; }
  _wordTimings   = [];
  _activeIdx     = -1;
  state.audioPlaying = false;
  _clearHighlight();
  _hidePlayer();
}

// ── History panel ────────────────────────────────────────────────
const historyBtn     = $('history-btn');
const historyPanel   = $('history-panel');
const historyOverlay = $('history-overlay');
const historyClose   = $('history-close-btn');
const historyList    = $('history-list');

function openHistory() {
  historyOverlay.hidden = false;
  historyPanel.classList.add('open');
  document.body.style.overflow = 'hidden';
  loadHistory();
}

function closeHistory() {
  historyPanel.classList.remove('open');
  document.body.style.overflow = '';
  setTimeout(() => { historyOverlay.hidden = true; }, 320);
}

historyBtn.addEventListener('click', openHistory);
historyClose.addEventListener('click', closeHistory);
historyOverlay.addEventListener('click', closeHistory);
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && historyPanel.classList.contains('open')) closeHistory();
});

async function loadHistory() {
  historyList.innerHTML = '<p class="history-empty">Loading…</p>';
  try {
    const res = await fetch('/history');
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    const stories = await res.json();

    if (!stories.length) {
      historyList.innerHTML = '<p class="history-empty">No stories yet. Create your first one!</p>';
      return;
    }

    historyList.innerHTML = stories.map(s => {
      const date  = new Date(s.timestamp).toLocaleDateString(undefined, {
        month: 'short', day: 'numeric', year: 'numeric',
      });
      const score = typeof s.overall_score === 'number'
        ? s.overall_score.toFixed(1) : '—';
      const cat   = (s.category || '').replace(/_/g, ' ');
      const title = s.title || s.prompt.slice(0, 60);
      return `
        <div class="history-item" data-id="${escapeHTML(s.id)}">
          <div class="history-item-top">
            <span class="history-item-title">${escapeHTML(title)}</span>
            <span class="history-score-pill">${score}</span>
          </div>
          <div class="history-item-meta">
            <span class="history-cat">${escapeHTML(cat)}</span>
            <span class="history-age">Age ${s.age}</span>
            <span class="history-date">${date}</span>
          </div>
        </div>
      `;
    }).join('');

    historyList.querySelectorAll('.history-item').forEach(el => {
      el.addEventListener('click', () => loadHistoryStory(el.dataset.id));
    });

  } catch (err) {
    historyList.innerHTML = `<p class="history-empty">Could not load history: ${escapeHTML(err.message)}</p>`;
  }
}

async function loadHistoryStory(id) {
  try {
    const res = await fetch(`/history/${id}`);
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    const record = await res.json();

    state.story         = record.story || '';
    state.narratorStory = record.narrator_story || record.story || '';
    state.judgment      = record.judgment || {};
    state.category      = record.category || '';
    state.storyId       = record.id || '';
    state.originalRequest = record.prompt || '';
    resetTTS();

    closeHistory();
    renderStoryView();
    showView('story');
    requestAnimationFrame(() => observeRevealElements($('view-story')));

  } catch (err) {
    alert(`Could not load story: ${err.message}`);
  }
}

// ── Vocabulary chatbot ────────────────────────────────────────────
const vocabPanel    = $('vocab-panel');
const vocabMessages = $('vocab-messages');
const vocabHint     = $('vocab-hint');
const vocabForm     = $('vocab-form');
const vocabInput    = $('vocab-input');
const vocabSendBtn  = $('vocab-send-btn');
const vocabToggleBtn = $('vocab-toggle');

let _vocabBusy = false;

function openVocab() {
  vocabPanel.hidden = false;
  vocabToggleBtn.setAttribute('aria-expanded', 'true');
  document.body.classList.add('vocab-open');
  vocabInput.focus();
}

function closeVocab() {
  vocabPanel.hidden = true;
  vocabToggleBtn.setAttribute('aria-expanded', 'false');
  document.body.classList.remove('vocab-open');
}

function resetVocab() {
  vocabMessages.innerHTML = '';
  vocabHint.classList.remove('hidden');
  closeVocab();
}

vocabToggleBtn.addEventListener('click', () => {
  if (vocabPanel.hidden) openVocab();
  else closeVocab();
});

// Clicking a story word pre-fills the input and opens the panel.
// Listen on document so it works regardless of which view is rendered.
document.addEventListener('click', e => {
  if (!e.target.classList.contains('story-word')) return;
  // Strip punctuation to get the bare word
  const raw = e.target.textContent.replace(/[^a-zA-Z']/g, '').trim();
  if (!raw) return;
  vocabInput.value = raw;
  openVocab();
  vocabInput.focus();
  vocabInput.select();
});

vocabForm.addEventListener('submit', async e => {
  e.preventDefault();
  const word = vocabInput.value.trim();
  if (!word || _vocabBusy) return;

  _vocabBusy = true;
  vocabSendBtn.disabled = true;
  vocabInput.value = '';
  vocabHint.classList.add('hidden');

  // User question chip
  const qDiv = document.createElement('div');
  qDiv.className = 'vocab-msg-question';
  qDiv.innerHTML = `<span class="vocab-word-chip">${escapeHTML(word)}</span>`;
  vocabMessages.appendChild(qDiv);

  // Loading bubble
  const loadDiv = document.createElement('div');
  loadDiv.className = 'vocab-msg-loading';
  loadDiv.innerHTML = '<div class="vocab-bubble">···</div>';
  vocabMessages.appendChild(loadDiv);
  loadDiv.scrollIntoView({ block: 'end', behavior: 'smooth' });

  try {
    const res = await fetch('/vocabulary', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ word, story: state.story, age: state.age }),
    });
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    const data = await res.json();

    loadDiv.remove();
    const aDiv = document.createElement('div');
    aDiv.className = 'vocab-msg-answer';
    aDiv.innerHTML = `<div class="vocab-bubble">${escapeHTML(data.explanation)}</div>`;
    vocabMessages.appendChild(aDiv);
    aDiv.scrollIntoView({ block: 'end', behavior: 'smooth' });

  } catch {
    loadDiv.remove();
    const errDiv = document.createElement('div');
    errDiv.className = 'vocab-msg-answer';
    errDiv.innerHTML = `<div class="vocab-bubble">Oops! Something went wrong. Try again!</div>`;
    vocabMessages.appendChild(errDiv);
  } finally {
    _vocabBusy = false;
    vocabSendBtn.disabled = false;
    vocabInput.focus();
  }
});
