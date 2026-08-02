// myPodcast 吸底 mini player (M3)
// - 取代 7 个原生 <audio controls>（暗色主题上视觉断裂）
// - 单一 <audio id="player-audio"> 元素 + UI 控件
// - 单播互斥：天然（同一 audio 实例）
// - Media Session API 锁屏控制
// - 键盘可达：Space 播放/暂停，←/→ 跳 5s
// - 进度条点击 + 拖动 + 键盘 ←/→

(function () {
  'use strict';

  var audio = document.getElementById('player-audio');
  var player = document.getElementById('player');
  if (!audio || !player) return;

  var btn = player.querySelector('[data-action="toggle"]');
  var muteBtn = player.querySelector('[data-action="mute"]');
  var closeBtn = player.querySelector('[data-action="close"]');
  var progress = player.querySelector('.player-progress');
  var fill = player.querySelector('.player-fill');
  var curEl = player.querySelector('.player-cur');
  var durEl = player.querySelector('.player-dur');
  var seriesEl = player.querySelector('.player-series');
  var titleEl = player.querySelector('.player-title');

  // play icon (polygon) → pause icon (two rects)
  var playIcon = btn.querySelector('svg');
  var playIconHTML = playIcon.outerHTML;
  var pauseIconHTML =
    '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<rect x="6" y="4" width="4" height="16"></rect>' +
    '<rect x="14" y="4" width="4" height="16"></rect>' +
    '</svg>';

  function fmt(t) {
    if (!isFinite(t) || t < 0) t = 0;
    var m = Math.floor(t / 60);
    var s = Math.floor(t % 60);
    return m + ':' + (s < 10 ? '0' + s : s);
  }

  function updateBtn() {
    if (audio.paused) {
      btn.setAttribute('data-state', 'paused');
      btn.setAttribute('aria-label', '播放');
      playIcon.outerHTML = playIconHTML;
      // re-bind local ref since outerHTML replaced
      playIcon = btn.querySelector('svg');
    } else {
      btn.setAttribute('data-state', 'playing');
      btn.setAttribute('aria-label', '暂停');
      playIcon.outerHTML = pauseIconHTML;
      playIcon = btn.querySelector('svg');
    }
  }

  function updateProgress() {
    if (!audio.duration) {
      fill.style.width = '0%';
      return;
    }
    var pct = (audio.currentTime / audio.duration) * 100;
    fill.style.width = pct + '%';
    curEl.textContent = fmt(audio.currentTime);
  }

  function updateDuration() {
    durEl.textContent = fmt(audio.duration);
  }

  function setMediaSession(title, series) {
    if (!('mediaSession' in navigator)) return;
    navigator.mediaSession.metadata = new MediaMetadata({
      title: title,
      artist: series,
      album: document.title
    });
    navigator.mediaSession.setActionHandler('play', function () { audio.play(); });
    navigator.mediaSession.setActionHandler('pause', function () { audio.pause(); });
    navigator.mediaSession.setActionHandler('seekbackward', function () { audio.currentTime = Math.max(0, audio.currentTime - 5); });
    navigator.mediaSession.setActionHandler('seekforward', function () { audio.currentTime = Math.min(audio.duration || 0, audio.currentTime + 5); });
  }

  // 单播 mutex + UI 互斥高亮
  function clearActiveCards() {
    document.querySelectorAll('.ep-card.is-playing, .series-ep-play[data-state="playing"]').forEach(function (el) {
      el.classList.remove('is-playing');
      el.removeAttribute('data-state');
    });
  }

  function markActive(btnEl) {
    clearActiveCards();
    if (btnEl) {
      btnEl.setAttribute('data-state', 'playing');
      btnEl.classList.add('is-playing');
    }
  }

  // 启动播放器
  function playEpisode(src, title, series, duration, sourceEl) {
    if (audio.src.indexOf(src) === -1) {
      audio.src = src;
    }
    seriesEl.textContent = series;
    titleEl.textContent = title;
    durEl.textContent = fmt(duration);
    player.classList.add('is-active');
    player.hidden = false;
    setMediaSession(title, series);
    audio.play().catch(function () {});
    markActive(sourceEl);
    updateBtn();
  }

  // 关闭播放器
  function close() {
    audio.pause();
    audio.removeAttribute('src');
    audio.load();
    player.classList.remove('is-active');
    player.hidden = true;
    clearActiveCards();
  }

  // 按钮 + 链接 click 拦截（play-now + ep-play + series-ep-play）
  // 兼容：ep-play button 自己不带 data-audio 时，向外层 article 找。
  // series-ep-play / Hero 链接 自带 data-audio，行为不变。
  document.addEventListener('click', function (e) {
    var play = e.target.closest('[data-action="play-now"]');
    if (!play) return;
    e.preventDefault();
    var src = play.getAttribute('data-audio')
      || (play.closest('[data-audio]') && play.closest('[data-audio]').getAttribute('data-audio'))
      || play.getAttribute('href');
    if (!src) return;
    var title = play.getAttribute('data-title') || play.getAttribute('aria-label') || '未命名';
    var series = play.getAttribute('data-series') || '';
    var duration = parseInt(play.getAttribute('data-duration') || '0', 10);
    playEpisode(src, title, series, duration, play);
  });

  // 暂停/播放
  btn.addEventListener('click', function () {
    if (audio.paused) {
      audio.play().catch(function () {});
    } else {
      audio.pause();
    }
  });

  // 静音
  muteBtn.addEventListener('click', function () {
    audio.muted = !audio.muted;
    muteBtn.setAttribute('data-state', audio.muted ? 'muted' : 'unmuted');
    muteBtn.setAttribute('aria-label', audio.muted ? '取消静音' : '静音');
  });

  // 关闭
  closeBtn.addEventListener('click', close);

  // 进度条点击
  progress.addEventListener('click', function (e) {
    if (!audio.duration) return;
    var rect = progress.getBoundingClientRect();
    var pct = (e.clientX - rect.left) / rect.width;
    audio.currentTime = pct * audio.duration;
    updateProgress();
  });

  // 进度条键盘
  progress.addEventListener('keydown', function (e) {
    if (!audio.duration) return;
    var step = audio.duration * 0.05;
    if (e.key === 'ArrowLeft') {
      e.preventDefault();
      audio.currentTime = Math.max(0, audio.currentTime - step);
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      audio.currentTime = Math.min(audio.duration, audio.currentTime + step);
    } else if (e.key === ' ' || e.key === 'Enter') {
      e.preventDefault();
      if (audio.paused) audio.play(); else audio.pause();
    }
  });

  // 全局键盘：Space 切换（焦点不在 input/textarea）
  document.addEventListener('keydown', function (e) {
    if (e.key !== ' ' && e.key !== 'Spacebar') return;
    var tag = (document.activeElement && document.activeElement.tagName) || '';
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'BUTTON') return;
    if (!audio.src) return;
    e.preventDefault();
    if (audio.paused) audio.play(); else audio.pause();
  });

  // audio 事件
  audio.addEventListener('timeupdate', updateProgress);
  audio.addEventListener('loadedmetadata', updateDuration);
  audio.addEventListener('play', updateBtn);
  audio.addEventListener('pause', function () { updateBtn(); clearActiveCards(); });
  audio.addEventListener('ended', function () { clearActiveCards(); updateBtn(); });
  audio.addEventListener('error', function () {
    if (audio.error) close();
  });
})();
