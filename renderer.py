""" WanXue Course Renderer — 将课程 JSON 渲染为单文件卡片化 HTML """

import html as _html
import json
try:
    from .sync_injector import generate_sync_js
except ImportError:
    from sync_injector import generate_sync_js


# ===== 内联 CSS =====
_CSS = """
:root {
  --bg: #fff8e7; --primary: #ff6b6b; --secondary: #4ecdc4;
  --accent: #ffe66d; --text: #2d3047; --text-soft: #6c6f7d;
  --card-bg: #ffffff; --shadow: 0 4px 16px rgba(45, 48, 71, 0.08);
  /* 字体大小变量（支持用户调整） */
  --fs-body: 19px; --fs-card-title: 28px; --fs-card-h3: 22px;
  --fs-bar-title: 17px; --fs-tab: 13px;
}
/* 字体大小模式 */
html[data-fs="sm"]  { --fs-body: 16px; --fs-card-title: 24px; --fs-card-h3: 19px; --fs-bar-title: 15px; --fs-tab: 12px; }
html[data-fs="md"]  { --fs-body: 19px; --fs-card-title: 28px; --fs-card-h3: 22px; --fs-bar-title: 17px; --fs-tab: 13px; }
html[data-fs="lg"]  { --fs-body: 22px; --fs-card-title: 32px; --fs-card-h3: 25px; --fs-bar-title: 19px; --fs-tab: 14px; }
html[data-fs="xl"]  { --fs-body: 25px; --fs-card-title: 36px; --fs-card-h3: 28px; --fs-bar-title: 21px; --fs-tab: 15px; }
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body {
  height: 100%;
  -webkit-text-size-adjust: 100%;
}
body {
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif;
  background: var(--bg); color: var(--text);
  line-height: 1.85; font-size: var(--fs-body);
  touch-action: pan-y;
  -webkit-tap-highlight-color: transparent;
  -webkit-touch-callout: none;
  -webkit-user-select: none;
  user-select: none;
  overscroll-behavior-x: none;
  padding-top: env(safe-area-inset-top);
  padding-bottom: env(safe-area-inset-bottom);
}
/* 顶栏 */
.top-bar {
  position: fixed; top: 0; left: 0; right: 0;
  padding: 10px 16px;
  padding-top: calc(10px + env(safe-area-inset-top));
  background: linear-gradient(135deg, #ffe66d 0%, #ff9a3c 100%);
  box-shadow: 0 2px 8px rgba(255, 154, 60, 0.2);
  z-index: 100;
}
.top-bar h1 {
  color: var(--text); font-size: var(--fs-bar-title); font-weight: bold;
  text-shadow: 0 1px 2px rgba(255,255,255,0.3);
  text-align: center; flex: 1; min-width: 0;
}
/* 字体大小切换按钮 */
.fs-toggle {
  flex-shrink: 0; width: 32px; height: 32px; border: none;
  border-radius: 50%; background: rgba(255,255,255,0.7);
  color: var(--text); font-size: 13px; font-weight: 700;
  cursor: pointer; display: flex; align-items: center;
  justify-content: center; transition: all 0.2s;
  font-family: inherit; margin-left: auto;
}
.fs-toggle:hover { background: rgba(255,255,255,0.95); }
.fs-toggle:active { transform: scale(0.9); }
.top-bar-row {
  display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
}
.chapter-tabs {
  display: flex; gap: 6px; overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}
.chapter-tabs::-webkit-scrollbar { display: none; }
.ch-tab {
  flex-shrink: 0;
  padding: 6px 12px; border: none; border-radius: 16px;
  background: rgba(255,255,255,0.6); color: var(--text);
  font-size: var(--fs-tab); font-weight: 600; white-space: nowrap;
  font-family: inherit; cursor: pointer;
  transition: all 0.2s;
}
.ch-tab.active {
  background: var(--primary); color: white;
  box-shadow: 0 2px 6px rgba(255, 107, 107, 0.4);
}
/* 进度条 */
.progress-bar {
  position: fixed; top: 0; left: 0; right: 0; height: 3px;
  background: rgba(0,0,0,0.05); z-index: 99;
  margin-top: env(safe-area-inset-top);
  padding-top: 50px; box-sizing: content-box;
}
.progress-fill {
  height: 3px; background: linear-gradient(90deg, #ff6b6b, #ffe66d);
  width: 0%; transition: width 0.4s;
}
/* 卡片区 — 长卡片滚动形式 */
.card-area {
  position: fixed;
  top: 92px; bottom: 70px; left: 0; right: 0;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  padding-top: env(safe-area-inset-top);
  padding-bottom: 20px;
}
.chapter-section {
  /* 章节之间自动垂直排列 */
}
.chapter-section:not(:last-child) {
  border-bottom: 2px solid rgba(255, 107, 107, 0.12);
  margin-bottom: 16px;
  padding-bottom: 16px;
}
/* 章节分隔标题 */
.chapter-divider {
  padding: 16px 20px 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--primary);
  background: linear-gradient(90deg, rgba(255,107,107,0.05), transparent);
  position: sticky;
  top: 0;
  z-index: 5;
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}
.chapter-divider .ch-icon { margin-right: 6px; }
.card {
  position: relative;
  max-width: 720px;
  margin: 8px auto;
  width: 100%;
  padding: 20px 20px 24px;
  background: var(--card-bg);
  border-radius: 16px;
  box-shadow: 0 1px 4px rgba(45,48,71,0.06);
  opacity: 1;
  transform: none;
  transition: none;
  pointer-events: auto;
}
/* 卡片标题 */
.card h2 {
  color: var(--primary); font-size: var(--fs-card-title); margin-bottom: 18px;
  display: flex; align-items: center; gap: 8px;
  line-height: 1.4;
}
.card h3 { color: var(--secondary); font-size: var(--fs-card-h3); margin: 18px 0 10px; line-height: 1.4; }
.card p { margin: 14px 0; color: var(--text); font-size: var(--fs-body); line-height: 1.85; }
.card ul, .card ol { margin: 14px 0; padding-left: 22px; }
.card li { margin: 8px 0; font-size: var(--fs-body); line-height: 1.8; }
.card strong { color: var(--primary); }
.card .emoji-big {
  font-size: 56px; text-align: center; display: block; margin: 16px 0;
}
.card .story-box {
  background: #fff3d6; border: 2px dashed var(--accent);
  border-radius: 16px; padding: 20px; margin: 16px 0; font-size: 16px;
}
.card .game-box {
  background: #e3f8f7; border: 2px solid var(--secondary);
  border-radius: 20px; padding: 20px; margin: 20px 0; text-align: center;
}
.card .game-step {
  background: white; border-radius: 12px; padding: 14px;
  margin: 12px 0; text-align: left; font-size: 18px;
}
.card .answer-btn {
  display: inline-block; background: var(--secondary); color: white;
  border: none; padding: 12px 22px; border-radius: 22px;
  font-size: 18px; cursor: pointer; margin: 6px;
  font-family: inherit; font-weight: 600;
  -webkit-tap-highlight-color: transparent;
  transition: transform 0.2s;
}
.card .answer-btn:active { transform: scale(0.96); }
.card .answer-btn.correct { background: #6bcf7f; }
.card .answer-btn.wrong { background: #ff8a80; }
.card .answer-btn:disabled { opacity: 0.5; cursor: default; }
/* TTS 播音按钮 */
.tts-btn {
  position: absolute; top: 12px; right: 12px;
  width: 32px; height: 32px; border: none; border-radius: 50%;
  background: rgba(255, 107, 107, 0.12); color: var(--primary);
  font-size: 14px; cursor: pointer; display: flex;
  align-items: center; justify-content: center;
  transition: all 0.2s; z-index: 10;
  font-family: inherit;
}
.tts-btn:hover { background: rgba(78, 205, 196, 0.3); transform: scale(1.1); }
.tts-btn:active { transform: scale(0.9); }
.tts-btn.speaking { background: var(--secondary); color: #fff; animation: tts-pulse 1s infinite; }
@keyframes tts-pulse { 0%,100%{opacity:1} 50%{opacity:0.6} }
.card .feedback {
  margin-top: 12px; padding: 12px; border-radius: 12px; font-size: 18px;
  display: none;
}
.card .feedback.show { display: block; }
.card .feedback.good { background: #d4f4dd; color: #2d6a3e; }
.card .feedback.bad { background: #ffe0e0; color: #c14545; }
.card .funfact {
  background: linear-gradient(135deg, #ffe66d 0%, #ff9a3c 100%);
  color: var(--text); border-radius: 16px; padding: 18px; margin: 16px 0; font-size: 18px;
}
.card .funfact strong { color: var(--primary); }
.card .scene-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 16px 0;
}
.card .scene-cell {
  background: white; border: 2px solid var(--accent);
  border-radius: 16px; padding: 14px; text-align: center; font-size: 17px;
}
.card .scene-cell .icon { font-size: 32px; display: block; margin-bottom: 6px; }
.card .scene-cell h4 { color: var(--primary); font-size: 14px; margin-bottom: 4px; }
.card .badge {
  display: inline-block;
  background: linear-gradient(135deg, #ffe66d, #ff9a3c);
  color: white; padding: 10px 20px; border-radius: 24px;
  font-size: 18px; font-weight: bold; margin: 8px;
  box-shadow: 0 4px 12px rgba(255, 154, 60, 0.4);
}
.card .summary {
  background: linear-gradient(135deg, #a8e6cf 0%, #4ecdc4 100%);
  color: white; border-radius: 20px; padding: 24px; text-align: center; margin: 24px 0;
}
.card .summary h2 { color: white; font-size: 22px; margin-bottom: 12px; }
.card .challenge-box {
  background: #fff0f0; border: 2px solid var(--primary);
  border-radius: 16px; padding: 20px; margin: 16px 0;
}
.card .challenge-box h3 { color: var(--primary); }
.card .progress-dots {
  display: flex; justify-content: center; gap: 8px; margin: 16px 0;
}
.card .progress-dots .dot {
  width: 10px; height: 10px; border-radius: 50%;
  background: #ddd; transition: all 0.3s;
}
.card .progress-dots .dot.done { background: var(--primary); }
.card .progress-dots .dot.current { background: var(--secondary); transform: scale(1.3); }
/* 底栏 — 长卡片模式下为固定进度条和回到顶部 */
.bottom-bar {
  position: fixed; bottom: 0; left: 0; right: 0; height: 70px;
  background: white; box-shadow: 0 -2px 12px rgba(0,0,0,0.08);
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 20px;
  padding-bottom: calc(12px + env(safe-area-inset-bottom));
  z-index: 100;
}
.bottom-bar .nav-btn {
  background: var(--primary); color: white; border: none;
  padding: 12px 20px; border-radius: 24px; font-size: 15px;
  font-weight: bold; cursor: pointer; font-family: inherit;
  box-shadow: 0 2px 8px rgba(255, 107, 107, 0.3);
  -webkit-tap-highlight-color: transparent;
}
.bottom-bar .nav-btn:disabled {
  background: #ccc; cursor: not-allowed; box-shadow: none;
}
.bottom-bar .nav-btn.top-btn {
  background: var(--secondary);
  box-shadow: 0 2px 8px rgba(78, 205, 196, 0.3);
}
.bottom-bar .progress-text {
  color: var(--text-soft); font-size: 14px; font-weight: 600;
}
/* 移动端适配 */
@media (max-width: 480px) {
  body { font-size: 18px; }
  .top-bar h1 { font-size: 17px; }
  .ch-tab { font-size: 13px; padding: 6px 12px; }
  .card { padding: 14px 14px 20px; margin: 4px auto; }
  .card h2 { font-size: 24px; }
  .card p { font-size: 15px; }
  .card .scene-grid { grid-template-columns: 1fr; }
  .bottom-bar { padding: 0 12px; }
  .bottom-bar .nav-btn { padding: 10px 14px; font-size: 14px; }
  .card-area { top: 80px; bottom: 65px; }
}
@media (max-width: 360px) {
  .card { padding: 10px 12px 16px; }
  .card h2 { font-size: 19px; }
  .card p { font-size: 14px; }
  .bottom-bar .nav-btn { padding: 8px 12px; font-size: 13px; }
}
@media (min-width: 768px) {
  .card { padding: 24px 28px 32px; margin: 12px auto; }
  .card h2 { font-size: 26px; }
}
/* === 3层验证 Modal === */
.verify-overlay {
  position: fixed; top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(45, 48, 71, 0.6); z-index: 200;
  display: none; align-items: center; justify-content: center;
  padding: 20px;
}
.verify-overlay.active { display: flex; }
.verify-modal {
  background: #fff; border-radius: 16px; padding: 28px 24px;
  max-width: 500px; width: 100%; max-height: 80vh; overflow-y: auto;
  box-shadow: 0 8px 32px rgba(0,0,0,0.15);
}
.verify-modal h3 { font-size: 18px; margin-bottom: 12px; color: #2d3047; }
.verify-modal p { font-size: 15px; line-height: 1.7; margin-bottom: 16px; color: #2d3047; }
.verify-modal textarea {
  width: 100%; min-height: 80px; border: 1.5px solid #ddd;
  border-radius: 8px; padding: 10px; font-size: 15px;
  font-family: inherit; resize: vertical;
}
.verify-btn {
  display: inline-block; padding: 10px 24px; border: none;
  border-radius: 20px; font-size: 15px; font-weight: 600;
  cursor: pointer; transition: all 0.2s;
  margin-right: 8px; margin-top: 12px;
}
.verify-btn.primary { background: #ff6b6b; color: #fff; }
.verify-btn.primary:hover { opacity: 0.85; }
.verify-btn.secondary { background: #4ecdc4; color: #fff; }
.verify-btn:disabled { opacity: 0.5; cursor: default; }
.verify-feedback { margin-top: 12px; padding: 10px; border-radius: 8px; font-size: 14px; }
.verify-feedback.correct { background: #e0ffe0; color: #2d8a4e; }
.verify-feedback.wrong { background: #ffe0e0; color: #d63333; }
.verify-option {
  display: block; width: 100%; text-align: left;
  padding: 10px 14px; margin-bottom: 8px;
  border: 1.5px solid #ddd; border-radius: 8px;
  background: #fff; font-size: 15px; cursor: pointer;
  transition: all 0.15s;
}
.verify-option:hover { border-color: #4ecdc4; background: #f0fdfa; }
.verify-option.selected { border-color: #ff6b6b; background: #fff0f0; }
.verify-option.correct { border-color: #2d8a4e; background: #e0ffe0; }
.verify-option.wrong { border-color: #d63333; background: #ffe0e0; }
.badge { font-size: 48px; text-align: center; margin: 16px 0; }
"""


# ===== 内联 JS（需注入课程配置变量） =====
_JS_BASE = """
// 进度存储/读取
function loadProgress() {
  try {
    var d = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    if (d.ch) currentCh = d.ch;
    if (typeof d.idx === 'number') currentIdx = d.idx;
  } catch(e) {}
}

function saveProgress() {
  try {
    var total = CHAPTER_DATA[currentCh] ? CHAPTER_DATA[currentCh].total : 0;
    if (currentIdx >= total) currentIdx = 0;
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      ch: currentCh, idx: currentIdx, time: Date.now()
    }));
    // 派发自定义事件供同步器监听
    window.dispatchEvent(new CustomEvent('wanxue_page_change'));
  } catch(e) {}
}

// 计算总完成百分比
function totalPercent() {
  var completed = 0;
  var chapterKeys = Object.keys(CHAPTER_DATA).map(Number).sort(function(a,b){return a-b;});
  for (var i = 0; i < chapterKeys.length; i++) {
    var ch = chapterKeys[i];
    if (ch < currentCh) completed += CHAPTER_DATA[ch].total;
    else if (ch === currentCh) { completed += currentIdx; break; }
  }
  var totalCards = 0;
  for (var k in CHAPTER_DATA) totalCards += CHAPTER_DATA[k].total;
  return totalCards > 0 ? Math.min(100, Math.round((completed / totalCards) * 100)) : 0;
}

// 更新界面
function updateUI() {
  // Tab 高亮
  var tabs = document.querySelectorAll('.ch-tab');
  for (var i = 0; i < tabs.length; i++) {
    tabs[i].classList.toggle('active', parseInt(tabs[i].dataset.ch) === currentCh);
  }
  // 长卡片模式：所有卡片都可见，只切换章节显示
  var sections = document.querySelectorAll('.chapter-section');
  for (var j = 0; j < sections.length; j++) {
    sections[j].style.display = parseInt(sections[j].dataset.ch) === currentCh ? 'block' : 'none';
  }
  // 所有卡片 active（长卡片不需要单卡激活）
  var cards = document.querySelectorAll('.card');
  for (var k = 0; k < cards.length; k++) {
    cards[k].classList.add('active');
  }
  // 进度文字
  var total = CHAPTER_DATA[currentCh] ? CHAPTER_DATA[currentCh].total : 0;
  document.getElementById('prog-text').textContent = '共 ' + total + ' 张卡片';
  // 顶部进��条 — 使用章节进度（长卡片模式显示为章节占比）
  var chapterIds = Object.keys(CHAPTER_DATA).filter(function(k) { return !isNaN(k); }).map(Number);
  var maxCh = Math.max.apply(null, chapterIds);
  var overall = (currentCh / maxCh) * 100;
  document.getElementById('progress').style.width = overall + '%';
  // 章节标题更新
  var activeTab = document.querySelector('.ch-tab.active');
  if (activeTab) {
    var title = activeTab.textContent || '';
    document.querySelector('.top-bar h1').textContent = title;
  }
  // 移除翻页按钮状态（长卡片不需要）
  var prevBtn = document.getElementById('btn-prev');
  var nextBtn = document.getElementById('btn-next');
  if (prevBtn) prevBtn.style.display = 'none';
  if (nextBtn) { nextBtn.textContent = '\u2191 回到顶部'; nextBtn.className = 'nav-btn top-btn'; }
}

// gotoCard：跳转到指定章节指定卡片
function gotoCard(ch, idx) {
  // 长卡片模式：跳转到章节（跳转到该章节最顶部）
  if (!CHAPTER_DATA[ch]) return;
  currentCh = ch;
  currentIdx = idx || 0;
  saveProgress();
  updateUI();
  // 滚动到该章节
  var section = document.querySelector('.chapter-section[data-ch="' + ch + '"]');
  if (section) section.scrollIntoView({behavior: 'smooth', block: 'start'});
  _checkVerification(ch, currentIdx);
}

// 翻页 — 长卡片模式下改为章节切换 / 回到顶部
function goto(direction) {
  if (direction > 0) {
    // 下一章
    var chapterIds = Object.keys(CHAPTER_DATA).filter(function(k) { return !isNaN(k); }).map(Number);
    chapterIds.sort(function(a,b){return a-b;});
    var idx = chapterIds.indexOf(currentCh);
    if (idx >= 0 && idx < chapterIds.length - 1) {
      gotoCard(chapterIds[idx + 1], 0);
    }
  } else if (direction < 0) {
    // 上一章
    var chapterIds = Object.keys(CHAPTER_DATA).filter(function(k) { return !isNaN(k); }).map(Number);
    chapterIds.sort(function(a,b){return a-b;});
    var idx = chapterIds.indexOf(currentCh);
    if (idx > 0) {
      gotoCard(chapterIds[idx - 1], 0);
    }
  } else {
    // direction === 0: 回到顶部
    var cardArea = document.querySelector('.card-area');
    if (cardArea) cardArea.scrollTop = 0;
  }
}

// 章节切换
function switchChapter(ch) {
  if (!CHAPTER_DATA[ch]) return;
  gotoCard(ch, 0);
}

// quiz 互动
// ===== TTS 朗读 =====
function speakCard(btn) {
  if (window.speechSynthesis && window.speechSynthesis.speaking) {
    window.speechSynthesis.cancel();
    btn.classList.remove('speaking');
    return;
  }
  var card = btn.closest('.card');
  if (!card) return;
  // 提取卡片文字内容（去掉按钮本身和嵌套按钮文本）
  var text = '';
  var children = card.childNodes;
  for (var i = 0; i < children.length; i++) {
    if (children[i].nodeType === 3) { // text node
      text += children[i].textContent;
    } else if (children[i].tagName !== 'BUTTON' && children[i].className !== 'diff-feedback') {
      text += children[i].textContent || '';
    }
  }
  text = text.trim().replace(/\s+/g, ' ');
  if (!text) return;

  var utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = 'zh-CN';
  utterance.rate = 0.95;
  utterance.pitch = 1.05;
  utterance.onstart = function() { btn.classList.add('speaking'); };
  utterance.onend = function() { btn.classList.remove('speaking'); };
  utterance.onerror = function() { btn.classList.remove('speaking'); };
  window.speechSynthesis.speak(utterance);
}

function checkAnswer(btn, isCorrect, fbId) {
  var fb = document.getElementById(fbId);
  var box = btn.closest('.game-box');
  if (!fb || !box) return;

  // 禁用所有按钮，防止重复点击（但保留查看）
  var btns = box.querySelectorAll('.answer-btn');
  for (var i = 0; i < btns.length; i++) btns[i].disabled = true;
  btn.classList.add(isCorrect ? 'correct' : 'wrong');

  // 显示当前选项的反馈
  if (isCorrect) {
    fb.className = 'feedback show good';
    fb.innerHTML = '🎉 <strong>答对了！</strong><br>' + (btn.getAttribute('data-good') || '回答正确！');
  } else {
    fb.className = 'feedback show bad';
    fb.innerHTML = '🤔 ' + (btn.getAttribute('data-good') || '不对哦');
  }

  // 显示所有选项的解释
  var explainDiv = box.querySelector('.explain-all');
  if (!explainDiv) {
    explainDiv = document.createElement('div');
    explainDiv.className = 'explain-all';
    explainDiv.style.cssText = 'margin-top:12px;padding:10px;background:#f8f5f0;border-radius:10px;font-size:13px;line-height:1.6;';
    box.appendChild(explainDiv);
  }
  var explainHtml = '<div style="font-weight:600;margin-bottom:6px;color:#2d3047">📖 各选项解析：</div>';
  for (var i = 0; i < btns.length; i++) {
    var label = String.fromCharCode(65 + i); // A, B, C, D
    var explain = btns[i].getAttribute('data-explain') || '';
    var mark = btns[i] === btn ? (isCorrect ? '✅' : '❌') : '';
    var color = btns[i] === btn && isCorrect ? '#4ecdc4' : (btns[i] === btn ? '#ff6b6b' : '#2d3047');
    explainHtml += '<div style="margin:4px 0;color:' + color + '"><b>' + mark + ' ' + label + '.</b> '
      + btns[i].textContent.trim();
    if (explain) explainHtml += ' <span style="color:#6c6f7d">— ' + explain + '</span>';
    explainHtml += '</div>';
  }
  explainDiv.innerHTML = explainHtml;
}

// 跳过当前测验（跳转到下一张卡片）
function skipQuiz(btn) {
  var box = btn ? btn.closest('.game-box') : null;
  if (box) {
    // 找到skip按钮所在的卡片，然后翻到下一张
    goto(1);
  }
}

// ===== 3层验证系统 =====
var _vL1Done = {};
var _vL2Done = false;
var _vL3Done = false;

// 从 localStorage 恢复验证状态
(function() {
  var v = localStorage.getItem(STORAGE_KEY + '_verify');
  if (v) {
    try {
      var d = JSON.parse(v);
      _vL1Done = d.L1 || {};
      _vL2Done = d.L2 || false;
      _vL3Done = d.L3 || false;
    } catch(e) {}
  }
})();

function _saveVerifyState() {
  localStorage.setItem(STORAGE_KEY + '_verify', JSON.stringify({
    L1: _vL1Done, L2: _vL2Done, L3: _vL3Done
  }));
}

function _chapterKeys() {
  var keys = [];
  for (var k in CHAPTER_DATA) {
    if (k !== '_verification' && CHAPTER_DATA.hasOwnProperty(k)) keys.push(Number(k));
  }
  keys.sort(function(a,b){return a-b;});
  return keys;
}

function _maxChapter() {
  var keys = _chapterKeys();
  return keys.length > 0 ? keys[keys.length - 1] : 1;
}

// 检查是否应该触发验证
function _checkVerification(ch, idx) {
  var verifyData = CHAPTER_DATA._verification;
  if (!verifyData) return;
  if (document.querySelector('.verify-overlay.active')) return; // 已有 modal 打开

  // L1: 每章第3张卡片（idx==2）
  if (verifyData.L1 && !_vL1Done[ch]) {
    var item = null;
    for (var vi = 0; vi < verifyData.L1.length; vi++) {
      if (verifyData.L1[vi].chapter === ch) { item = verifyData.L1[vi]; break; }
    }
    if (item && idx === 2) {
      _showL1Modal(ch, item);
      return;
    }
  }

  // L2: 第3章最后一张卡片
  if (verifyData.L2 && !_vL2Done && ch === 3) {
    var chCards = CHAPTER_DATA[ch] ? CHAPTER_DATA[ch].total : 0;
    if (idx === chCards - 1) {
      _showL2Modal();
      return;
    }
  }

  // L3: 最后一张卡片（全课程）
  if (verifyData.L3 && !_vL3Done) {
    var totalCh = _maxChapter();
    if (ch === totalCh) {
      var lastCards = CHAPTER_DATA[totalCh] ? CHAPTER_DATA[totalCh].total : 0;
      if (idx === lastCards - 1) {
        _showL3Modal();
        return;
      }
    }
  }
}

// L1 Modal
function _showL1Modal(ch, item) {
  var overlay = document.getElementById('verifyContainer');
  var keyword = item.keyword || '';
  var question = (item.question || '刚才提到的关键词，你能用自己的话说说它是什么意思吗？').replace('[关键词]', keyword);
  overlay.innerHTML = '<div class="verify-overlay active"><div class="verify-modal"><h3>\uD83D\uDCDD 关键概念反问</h3><p>' + question + '</p><textarea id="l1Input" placeholder="写下你的理解..."></textarea><div><button class="verify-btn primary" id="l1SubmitBtn">\u2714\uFE0F 确认</button></div><div id="l1Feedback" class="verify-feedback" style="display:none;"></div><button class="verify-btn secondary" id="l1ContinueBtn" style="display:none;">\u25B6\uFE0F 继续学习</button></div></div>';
  document.getElementById('l1SubmitBtn').onclick = function() {
    var input = document.getElementById('l1Input');
    var fb = document.getElementById('l1Feedback');
    fb.style.display = 'block';
    fb.className = 'verify-feedback correct';
    fb.innerHTML = '\uD83D\uDC4D 说得很棒！你理解了"' + keyword + '"的核心意思。带着这个理解继续学习吧！';
    document.getElementById('l1SubmitBtn').disabled = true;
    input.disabled = true;
    document.getElementById('l1ContinueBtn').style.display = 'inline-block';
  };
  document.getElementById('l1ContinueBtn').onclick = function() {
    var ov = document.querySelector('.verify-overlay');
    if (ov) { ov.classList.remove('active'); ov.parentNode.removeChild(ov); }
    _vL1Done[ch] = true;
    _saveVerifyState();
  };
}

// L2 Modal
function _showL2Modal() {
  var verifyData = CHAPTER_DATA._verification;
  if (!verifyData || !verifyData.L2) return;
  var questions = verifyData.L2.questions || [];
  var html = '<div class="verify-overlay active"><div class="verify-modal"><h3>\uD83D\uDCDD 章节小测</h3><p>做完这两道题，才能继续第4章哦！</p>';
  for (var qi = 0; qi < questions.length; qi++) {
    var q = questions[qi];
    html += '<div class="l2-question" data-qidx="' + qi + '"><p><strong>' + (qi + 1) + '. ' + q.q + '</strong></p>';
    for (var oi = 0; oi < q.options.length; oi++) {
      html += '<button class="verify-option" data-q="' + qi + '" data-oi="' + oi + '">' + (String.fromCharCode(65 + oi)) + '. ' + q.options[oi] + '</button>';
    }
    html += '<div id="l2fb' + qi + '" class="verify-feedback" style="display:none;"></div></div>';
  }
  html += '<div id="l2Result" style="display:none;"></div></div></div>';
  var overlay = document.getElementById('verifyContainer');
  overlay.innerHTML = html;

  var correctCount = 0;
  var answered = {};
  var optionBtns = overlay.querySelectorAll('.verify-option');
  for (var bi = 0; bi < optionBtns.length; bi++) {
    (function(btn) {
      btn.onclick = function() {
        var qi = parseInt(btn.getAttribute('data-q'));
        var oi = parseInt(btn.getAttribute('data-oi'));
        if (answered[qi]) return;
        answered[qi] = true;
        var isCorrect = oi === questions[qi].answer;
        var fb = document.getElementById('l2fb' + qi);
        fb.style.display = 'block';
        if (isCorrect) {
          fb.className = 'verify-feedback correct';
          fb.innerHTML = '\u2705 答对了！';
          btn.classList.add('correct');
          correctCount++;
        } else {
          fb.className = 'verify-feedback wrong';
          fb.innerHTML = '\u274C 不对哦，正确答案是 ' + (String.fromCharCode(65 + questions[qi].answer)) + '。' + (questions[qi].explanation || '再想想～');
          btn.classList.add('wrong');
        }
        // 标记该题所有选项
        var qBtns = overlay.querySelectorAll('.verify-option[data-q="' + qi + '"]');
        for (var xb = 0; xb < qBtns.length; xb++) {
          qBtns[xb].disabled = true;
          var xoi = parseInt(qBtns[xb].getAttribute('data-oi'));
          if (xoi === questions[qi].answer) qBtns[xb].classList.add('correct');
        }
        // 检查是否全部答完
        var allDone = true;
        for (var cqi = 0; cqi < questions.length; cqi++) { if (!answered[cqi]) { allDone = false; break; } }
        if (allDone) {
          var resultDiv = document.getElementById('l2Result');
          resultDiv.style.display = 'block';
          if (correctCount === questions.length) {
            resultDiv.innerHTML = '<div class="verify-feedback correct">\uD83C\uDF89 全部答对！太棒了！</div><button class="verify-btn primary" id="l2UnlockBtn">\u25B6\uFE0F 继续第4章</button>';
            document.getElementById('l2UnlockBtn').onclick = function() {
              var ov = document.querySelector('.verify-overlay');
              if (ov) { ov.classList.remove('active'); ov.parentNode.removeChild(ov); }
              _vL2Done = true;
              _saveVerifyState();
            };
          } else {
            resultDiv.innerHTML = '<div class="verify-feedback wrong">\uD83D\uDC4A 答对了 ' + correctCount + '/' + questions.length + '，再想想吧！</div><button class="verify-btn secondary" id="l2RetryBtn">\uD83D\uDD04 重试</button>';
            document.getElementById('l2RetryBtn').onclick = function() { _showL2Modal(); };
          }
        }
      };
    })(optionBtns[bi]);
  }
}

// L3 Modal
function _showL3Modal() {
  var verifyData = CHAPTER_DATA._verification;
  if (!verifyData || !verifyData.L3) return;
  var l3 = verifyData.L3;
  var html = '<div class="verify-overlay active"><div class="verify-modal"><h3>\uD83C\uDF1F 场景迁移</h3>';
  html += '<p><strong>' + l3.scenario + '</strong></p>';
  html += '<p>' + l3.question + '</p>';
  for (var oi = 0; oi < l3.options.length; oi++) {
    html += '<button class="verify-option" data-oi="' + oi + '">' + (String.fromCharCode(65 + oi)) + '. ' + l3.options[oi] + '</button>';
  }
  html += '<div id="l3Feedback" class="verify-feedback" style="display:none;"></div>';
  html += '<div id="l3Badge" style="display:none;" class="badge">\uD83C\uDFC6</div>';
  html += '<button class="verify-btn secondary" id="l3RetryBtn" style="display:none;">\uD83D\uDD04 再想想</button></div></div>';
  var overlay = document.getElementById('verifyContainer');
  overlay.innerHTML = html;

  var answered = false;
  var optionBtns = overlay.querySelectorAll('.verify-option');
  for (var bi = 0; bi < optionBtns.length; bi++) {
    (function(btn) {
      btn.onclick = function() {
        if (answered) return;
        answered = true;
        var oi = parseInt(btn.getAttribute('data-oi'));
        var isCorrect = oi === l3.answer;
        var fb = document.getElementById('l3Feedback');
        fb.style.display = 'block';
        // 禁用所有
        var allBtns = overlay.querySelectorAll('.verify-option');
        for (var ab = 0; ab < allBtns.length; ab++) {
          allBtns[ab].disabled = true;
          var aoi = parseInt(allBtns[ab].getAttribute('data-oi'));
          if (aoi === l3.answer) allBtns[ab].classList.add('correct');
        }
        if (isCorrect) {
          btn.classList.add('correct');
          fb.className = 'verify-feedback correct';
          fb.innerHTML = '\u2705 完全正确！' + (l3.explanation || '');
          document.getElementById('l3Badge').style.display = 'block';
          var badgeHtml = '<div style="text-align:center;margin-top:8px;"><div class="badge">\uD83C\uDFC6</div><p style="font-size:14px;color:#2d3047;"><strong>\uD83C\uDF89 恭喜完成课程！</strong><br>你已获得课程完成徽章！</p></div>';
          fb.innerHTML += badgeHtml;
          // 关闭按钮
          fb.innerHTML += '<br><button class="verify-btn primary" id="l3FinishBtn">\u2714\uFE0F 完成</button>';
          document.getElementById('l3FinishBtn').onclick = function() {
            var ov = document.querySelector('.verify-overlay');
            if (ov) { ov.classList.remove('active'); ov.parentNode.removeChild(ov); }
            _vL3Done = true;
            _saveVerifyState();
          };
        } else {
          btn.classList.add('wrong');
          fb.className = 'verify-feedback wrong';
          fb.innerHTML = '\u274C 不对哦。' + (l3.explanation || '再想想～');
          // 显示重试按钮
          document.getElementById('l3RetryBtn').style.display = 'inline-block';
          document.getElementById('l3RetryBtn').onclick = function() {
            for (var cb = 0; cb < allBtns.length; cb++) {
              allBtns[cb].disabled = false;
              allBtns[cb].classList.remove('correct', 'wrong');
            }
            fb.style.display = 'none';
            document.getElementById('l3RetryBtn').style.display = 'none';
            answered = false;
          };
        }
      };
    })(optionBtns[bi]);
  }
}

// 事件绑定
document.addEventListener('DOMContentLoaded', function() {
  document.getElementById('btn-next').onclick = function() {
    var btn = document.getElementById('btn-next');
    if (btn.textContent.indexOf('回到顶部') >= 0) {
      goto(0);  // 滚动到顶部
      return;
    }
    goto(1);  // 下一章
  };
  // 在章节切换后更新按钮文字
  var _origUpdate = updateUI;
  updateUI = function() {
    _origUpdate();
    // 如果是最后一章，按钮改为"回到顶部"
    var chapterIds = Object.keys(CHAPTER_DATA).filter(function(k) { return !isNaN(k); }).map(Number);
    var maxCh = Math.max.apply(null, chapterIds);
    var btn = document.getElementById('btn-next');
    if (currentCh >= maxCh) {
      btn.textContent = '\u2191 回到顶部';
      btn.className = 'nav-btn top-btn';
    } else {
      btn.textContent = '下一章 \u2192';
      btn.className = 'nav-btn';
    }
  };
  var tabs = document.querySelectorAll('.ch-tab');
  for (var i = 0; i < tabs.length; i++) {
    tabs[i].onclick = function() { switchChapter(parseInt(this.dataset.ch)); };
  }
});

// 键盘翻页
document.addEventListener('keydown', function(e) {
  if (e.key === 'ArrowLeft') { e.preventDefault(); goto(-1); }
  else if (e.key === 'ArrowRight') { e.preventDefault(); goto(1); }
});

// 触摸滑动
// ===== 字体大小控制 =====
(function() {
  var FS_SIZES = ['sm', 'md', 'lg', 'xl'];
  var saved = localStorage.getItem(storageKey + '_fs');
  var idx = FS_SIZES.indexOf(saved);
  if (idx < 0) idx = 1;
  document.documentElement.setAttribute('data-fs', FS_SIZES[idx]);
  var btn = document.getElementById('fsToggle');
  if (btn) {
    btn.addEventListener('click', function() {
      idx = (idx + 1) % FS_SIZES.length;
      var size = FS_SIZES[idx];
      document.documentElement.setAttribute('data-fs', size);
      localStorage.setItem(storageKey + '_fs', size);
    });
  }
})();

// 触摸滑动
(function() {
  var touchStartX = 0, touchStartY = 0;
  var cardArea = document.querySelector('.card-area');
  if (cardArea) {
    cardArea.addEventListener('touchstart', function(e) {
      touchStartX = e.touches[0].clientX;
      touchStartY = e.touches[0].clientY;
    }, {passive: true});
    cardArea.addEventListener('touchend', function(e) {
      var dx = e.changedTouches[0].clientX - touchStartX;
      var dy = e.changedTouches[0].clientY - touchStartY;
      if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) {
        goto(dx < 0 ? 1 : -1);
      }
    }, {passive: true});
  }
})();

// ===== 难度反馈按钮处理 =====
(function() {
  var container = document.getElementById('diffFeedback');
  if (!container) return;
  container.addEventListener('click', function(e) {
    var btn = e.target.closest('.diff-fb-btn');
    if (!btn) return;
    // 禁用所有按钮
    var allBtns = container.querySelectorAll('.diff-fb-btn');
    for (var i = 0; i < allBtns.length; i++) allBtns[i].disabled = true;
    // 显示感谢信息
    var result = container.querySelector('.diff-fb-result');
    if (result) result.style.display = 'block';
    // 通过 postMessage 通知父页面（app.html）
    var fbValue = btn.getAttribute('data-fb');
    try {
      window.parent.postMessage({
        type: 'wanxue_difficulty_feedback',
        value: fbValue === 'too_easy' ? '太简单了' : (fbValue === 'too_hard' ? '太难了' : '难度正好')
      }, '*');
    } catch(e) {
      // 如果不在 iframe 中（直接查看课程），忽略
    }
  });
})();

// 启动
loadProgress();
updateUI();

// 为所有 quiz 添加跳过按钮
(function() {
  var boxes = document.querySelectorAll('.game-box');
  for (var i = 0; i < boxes.length; i++) {
    // 检查是否已有跳过按钮
    if (boxes[i].querySelector('.skip-quiz-btn')) continue;
    var skip = document.createElement('div');
    skip.style.cssText = 'text-align:right;margin-top:6px';
    skip.innerHTML = '<button class="skip-quiz-btn" style="padding:6px 14px;border:1px solid #ddd;border-radius:8px;background:#fff;color:#999;cursor:pointer;font-size:12px;font-family:inherit">跳过此题 ↓</button>';
    boxes[i].appendChild(skip);
    skip.querySelector('.skip-quiz-btn').onclick = function() {
      // 在长卡片模式下，滚动到当前卡片下���
      var card = this.closest('.card');
      if (card) {
        var next = card.nextElementSibling;
        while (next && !next.classList.contains('card')) next = next.nextElementSibling;
        if (next) next.scrollIntoView({behavior:'smooth', block:'start'});
      }
    };
  }
})();
"""


def render_html(course_data: dict) -> str:
    """将课程 JSON 渲染为单文件卡片化 HTML

    Args:
        course_data: 来自 engine.py 的课程数据字典

    Returns:
        完整 HTML 字符串（单文件，内联 CSS/JS）
    """
    course_title = course_data.get("course_title", "课程")
    course_emoji = course_data.get("course_emoji", "\U0001f4da")
    course_id = course_data.get("_course_id", "course")
    storage_key = f"wanxue_{course_id}"
    chapter_totals = course_data.get("_chapter_totals", [0])
    total_cards = course_data.get("_total_cards", 0)
    chapters = course_data.get("chapters", [])

    # 提取验证数据
    verification_json = json.dumps(course_data.get("_verification", {}), ensure_ascii=False)

    # 构建各部分 HTML
    chapter_tabs_html = _build_chapter_tabs(chapters)
    cards_html = _build_cards_html(chapters)
    chapter_data_js = _build_chapter_data_js(chapters, verification_json)

    # 获取同步器 JS
    sync_js = generate_sync_js(course_id, storage_key, chapter_totals, total_cards)

    title_safe = _html.escape(f"{course_emoji} {course_title}")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="format-detection" content="telephone=no">
<meta name="theme-color" content="#fff8e7">
<title>{title_safe}</title>
<style>
{_CSS}
</style>
</head>
<body>
<div class="top-bar">
  <div class="top-bar-row">
    <h1>{title_safe}</h1>
    <button class="fs-toggle" id="fsToggle" title="调整字体大小">Aa</button>
  </div>
  <nav class="chapter-tabs" id="chapter-tabs">
{chapter_tabs_html}
  </nav>
</div>

<div class="progress-bar"><div class="progress-fill" id="progress"></div></div>

<div class="card-area" id="card-area">
{cards_html}
</div>

<!-- 3层验证 Modal 容器 -->
<div id="verifyContainer"></div>

<div class="bottom-bar">
  <button class="nav-btn" id="btn-prev" style="display:none">&larr; 上一章</button>
  <span class="progress-text" id="prog-text">共 0 张卡片</span>
  <button class="nav-btn" id="btn-next">下一章 &rarr;</button>
</div>

<script>
var CHAPTER_DATA = {chapter_data_js};
var currentCh = 1;
var currentIdx = 0;
var STORAGE_KEY = '{storage_key}';
{_JS_BASE}
</script>

{sync_js}

</body>
</html>"""
    return html


def _build_chapter_tabs(chapters: list) -> str:
    """构建章节 Tab 按钮 HTML"""
    lines = []
    for ch in chapters:
        ch_id = ch.get("id", 1)
        emoji = ch.get("emoji", "\U0001f4d6")
        title_short = ch.get("title", f"Ch{ch_id}")[:8]
        active_cls = "active" if ch_id == 1 else ""
        label = f"{emoji} {title_short}"
        lines.append(
            f'<button class="ch-tab {active_cls}" data-ch="{ch_id}">'
            f'{_html.escape(label)}</button>'
        )
    return "\n".join(lines)


def _build_cards_html(chapters: list) -> str:
    """构建所有章节和卡片的 HTML"""
    sections = []
    global_card_id = 0

    for ch_idx, ch in enumerate(chapters):
        ch_id = ch.get("id", 1)
        is_first_chapter = ch_id == 1
        is_last_chapter = ch_idx == len(chapters) - 1
        display_style = "" if is_first_chapter else ' style="display:none;"'

        cards_html = []
        cards = ch.get("cards", [])
        for card_idx, card in enumerate(cards):
            is_active = card_idx == 0
            active_cls = "active" if is_active else ""
            card_body = card.get("body", "<p>内容待补充</p>")
            card_type = card.get("type", "concept")

            # 最后一章的 reward 卡片 → 添加难度反馈
            is_last_reward = is_last_chapter and card_type == "reward" and card_idx == len(cards) - 1
            diff_feedback_html = ""
            if is_last_reward:
                diff_feedback_html = """
  <div class="diff-feedback" id="diffFeedback" style="margin-top:20px;padding:16px;background:linear-gradient(135deg,#fff8e7 0%,#ffe9b3 100%);border-radius:14px;border:1px solid #ffe66d;text-align:center;">
    <div style="font-size:14px;font-weight:700;color:#2d3047;margin-bottom:10px">📊 这个课程的难度怎么样？</div>
    <div style="font-size:12px;color:#6c6f7d;margin-bottom:12px">你的反馈会帮我以后自动匹配合适的难度</div>
    <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">
      <button class="diff-fb-btn" data-fb="too_easy" style="padding:10px 20px;border:1.5px solid #ff6b6b;border-radius:10px;background:#fff;color:#ff6b6b;cursor:pointer;font-size:13px;font-weight:600;font-family:inherit">😅 太简单</button>
      <button class="diff-fb-btn" data-fb="just_right" style="padding:10px 20px;border:1.5px solid #4ecdc4;border-radius:10px;background:#fff;color:#4ecdc4;cursor:pointer;font-size:13px;font-weight:600;font-family:inherit">👍 正好</button>
      <button class="diff-fb-btn" data-fb="too_hard" style="padding:10px 20px;border:1.5px solid #9b59b6;border-radius:10px;background:#fff;color:#9b59b6;cursor:pointer;font-size:13px;font-weight:600;font-family:inherit">😰 太难了</button>
    </div>
    <div class="diff-fb-result" style="margin-top:10px;font-size:13px;color:#2d3047;display:none">已记录你的难度偏好，谢谢反馈！🎉</div>
  </div>
"""

            cards_html.append(
                f'  <div class="card {active_cls}" id="c{global_card_id}" '
                f'data-ch="{ch_id}" data-idx="{card_idx}" data-type="{card_type}">\n'
                f'<button class="tts-btn" onclick="speakCard(this)" title="朗读本卡">🔊</button>\n'
                f'{card_body}\n'
                f'{diff_feedback_html}\n'
                f'  </div>'
            )
            global_card_id += 1

        ch_title = ch.get("title", f"第{ch_id}章")
        ch_emoji = ch.get("emoji", "📖")
        chapter_divider = (
            f'<div class="chapter-divider" id="divider-{ch_id}">'
            f'<span class="ch-icon">{ch_emoji}</span>{_html.escape(ch_title)}'
            f'</div>\n'
        )
        section = (
            f'<section class="chapter-section" data-ch="{ch_id}"{display_style}>\n'
            + chapter_divider
            + "\n".join(cards_html)
            + "\n</section>"
        )
        sections.append(section)

    return "\n".join(sections)


def _build_chapter_data_js(chapters: list, verification_json: str = "{}") -> str:
    """构建 JavaScript 的 CHAPTER_DATA 对象"""
    entries = []
    for ch in chapters:
        ch_id = ch.get("id", 1)
        total = len(ch.get("cards", []))
        entries.append(f"  {ch_id}: {{total: {total}}}")
    entries.append(f'  "_verification": {verification_json}')
    return "{\n" + ",\n".join(entries) + "\n}"
