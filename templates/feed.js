// myPodcast 客户端动态层 (M3-A: dynamic framework)
// - 取代 build_index() 对 latest / series 的静态渲染
// - fetch('manifest.json') → 解析 episodes / groups → 注入 DOM
// - 依赖 player.js 已有的 click handler（closest('[data-action="play-now"]')，
//   会向上找 [data-audio]，所以 button 不必自带）
// - 失败 fallback：fetch 失败 → 显示一行提示，不破坏静态壳

(function () {
  'use strict';

  var PLAY_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true"><polygon points="7 5 19 12 7 19 7 5"/></svg>';

  function fmtDur(sec) {
    if (!sec || sec < 0) sec = 0;
    var m = Math.floor(sec / 60);
    var s = Math.floor(sec % 60);
    return m + ':' + (s < 10 ? '0' + s : s);
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // ---- latest 排序：复用 src/feed.py _group_by_series 规则 ----
  // groups 按 latest_date 倒序；items 按 ep_index 升序；featured = groups[0].items[0]
  function groupBySeries(eps) {
    var map = {};
    var singletons = [];
    eps.forEach(function (e) {
      var slug = e.slug || '';
      if (slug) {
        if (!map[slug]) map[slug] = [];
        map[slug].push(e);
      } else {
        singletons.push(e);
      }
    });
    var groups = [];
    Object.keys(map).forEach(function (slug) {
      var items = map[slug].sort(function (a, b) {
        return (a.ep_index || a.episode || 1) - (b.ep_index || b.episode || 1);
      });
      var totalDur = items.reduce(function (s, x) { return s + (x.duration || 0); }, 0);
      var latestDate = items.reduce(function (m, x) { return x.date > m ? x.date : m; }, '');
      var firstDesc = (items[0].description || '').split('（第')[0].trim();
      groups.push({
        slug: slug,
        series: items[0].series || slug,
        items: items,
        count: items.length,
        total_duration: totalDur,
        latest_date: latestDate,
        description: firstDesc,
      });
    });
    groups.sort(function (a, b) { return b.latest_date.localeCompare(a.latest_date); });
    return groups;
  }

  function renderLatest(groups) {
    var LATEST_PER_SERIES = 3;
    var cards = [];
    var overflows = [];
    groups.forEach(function (g) {
      g.items.slice(0, LATEST_PER_SERIES).forEach(function (e) { cards.push(e); });
      var rest = g.items.slice(LATEST_PER_SERIES);
      if (rest.length) {
        overflows.push({ series: g.series, slug: g.slug, remaining: rest.length });
      }
    });
    // featured = cards[0]（hero 已经在静态模板里展示，这里跳过）
    var html = '';
    cards.slice(1).forEach(function (e) {
      html += epCardHtml(e);
    });
    overflows.forEach(function (o) {
      html += overflowCardHtml(o);
    });
    return html;
  }

  function epCardHtml(e) {
    var label = (e.episode && e.total) ? ('第 ' + e.episode + '/' + e.total + ' 集') : '';
    return ''
      + '<article class="ep-card" data-slug="' + escapeHtml(e.slug) + '" data-audio="'
      + escapeHtml(e.url) + '" data-title="' + escapeHtml(e.title) + '" data-series="'
      + escapeHtml(e.series) + '" data-duration="' + (e.duration || 0) + '">'
      + '<div class="ep-meta">'
      + '<time datetime="' + escapeHtml(e.date) + '">' + escapeHtml(e.date) + '</time>'
      + (label ? '<span class="badge">' + escapeHtml(label) + '</span>' : '')
      + '<span class="duration">' + fmtDur(e.duration) + '</span>'
      + '</div>'
      + '<h3 class="ep-title">' + escapeHtml(e.title) + '</h3>'
      + '<p class="ep-desc">' + escapeHtml(e.description || '') + '</p>'
      + '<div class="ep-actions">'
      + '<button type="button" class="ep-play" data-action="play-now" aria-label="立即播放 '
      + escapeHtml(e.title) + '">' + PLAY_SVG + '<span>听</span></button>'
      + '<a href="' + escapeHtml('series/' + e.slug + '/ep-' + pad(e.episode || e.ep_index) + '/shownotes.md') + '">Shownotes</a>'
      + '<a href="' + escapeHtml(e.url) + '" download>下载</a>'
      + '</div>'
      + '</article>';
  }

  function overflowCardHtml(o) {
    return ''
      + '<a class="ep-card ep-card-overflow" href="#series" data-slug="' + escapeHtml(o.slug)
      + '" aria-label="' + escapeHtml(o.series) + ' 还有 ' + o.remaining + ' 集，去节目区看全部">'
      + '<div class="ep-overflow-num">+' + o.remaining + '</div>'
      + '<div class="ep-overflow-label">集</div>'
      + '<div class="ep-overflow-hint">去节目区看全部</div>'
      + '<div class="ep-overflow-series">' + escapeHtml(o.series) + '</div>'
      + '</a>';
  }

  function pad(n) {
    var s = String(n || 1);
    return s.length < 2 ? '0' + s : s;
  }

  function renderSeries(groups) {
    var EP_PAGE_SIZE = 3;          // 单 series 内 ep 分页大小
    var LIST_PAGE_SIZE = 3;        // series 列表本身分页大小
    var totalListPages = Math.max(1, Math.ceil(groups.length / LIST_PAGE_SIZE));
    var html = '';
    for (var lp = 1; lp <= totalListPages; lp++) {
      var listSlice = groups.slice((lp - 1) * LIST_PAGE_SIZE, lp * LIST_PAGE_SIZE);
      html += '<div class="series-grid" data-list-page="' + lp + '"'
        + (lp === 1 ? '' : ' hidden') + '>';
      listSlice.forEach(function (g) {
        var totalDur = fmtDur(g.total_duration);
        var totalPages = Math.max(1, Math.ceil(g.items.length / EP_PAGE_SIZE));
        html += ''
          + '<article class="series-card" data-slug="' + escapeHtml(g.slug)
          + '" data-page-size="' + EP_PAGE_SIZE + '" data-total-pages="' + totalPages + '">'
          + '<div class="series-body">'
          + '<h3>' + escapeHtml(g.series) + '</h3>'
          + '<p class="series-meta"><span class="series-count">' + g.count + ' 集</span>'
          + '<span class="series-dot" aria-hidden="true">·</span>'
          + '<span>总时长 ' + totalDur + '</span></p>'
          + (g.description ? '<p class="series-desc">' + escapeHtml(g.description) + '</p>' : '')
          + '<ol class="series-ep-list" data-page="1">'
          + renderPage(g, 1)
          + '</ol>'
          + '</div>'
          + (totalPages > 1 ? paginationHtml(g.slug, totalPages, 1) : '')
          + '</article>';
      });
      html += '</div>';
    }
    if (totalListPages > 1) {
      html += listPagerHtml(totalListPages, 1);
    }
    // render 完成后，把每张卡片的 items 挂到 DOM 节点上，供分页 click handler 用
    // （绕过 dataset JSON escape 麻烦 + 字符串拼接里塞大数组的丑）
    setTimeout(function () {
      var cards = document.querySelectorAll('.series-card');
      if (!cards.length) return;
      var bySlug = {};
      groups.forEach(function (g) { bySlug[g.slug] = g.items; });
      cards.forEach(function (card) {
        card._items = bySlug[card.getAttribute('data-slug')] || [];
      });
    }, 0);
    return html;
  }

  // 列表级分页条（同款分页 UI）：< 1 2 >，箭头 + 页码
  function listPagerHtml(totalPages, page) {
    var ARROW_LEFT = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true"><polygon points="15 5 7 12 15 19 15 5"/></svg>';
    var ARROW_RIGHT = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true"><polygon points="9 5 17 12 9 19 9 5"/></svg>';
    var html = ''
      + '<nav class="series-pagination series-list-pager" data-page="' + page + '" data-total-pages="' + totalPages + '" aria-label="系列列表分页">'
      + '<button type="button" class="pg-arrow pg-list-prev" data-action="list-prev"'
      + (page <= 1 ? ' disabled aria-disabled="true"' : ' aria-label="上一页"') + '>'
      + ARROW_LEFT + '</button>';
    for (var p = 1; p <= totalPages; p++) {
      var active = (p === page);
      html += ''
        + '<button type="button" class="pg-num pg-list-num' + (active ? ' is-active' : '') + '"'
        + ' data-action="list-num" data-page="' + p + '"'
        + (active ? ' aria-current="page"' : ' aria-label="第 ' + p + ' 页"') + '>'
        + p + '</button>';
    }
    html += ''
      + '<button type="button" class="pg-arrow pg-list-next" data-action="list-next"'
      + (page >= totalPages ? ' disabled aria-disabled="true"' : ' aria-label="下一页"') + '>'
      + ARROW_RIGHT + '</button>'
      + '</nav>';
    return html;
  }

  // 单页 3 集 li 的 HTML
  function renderPage(g, page) {
    var PAGE_SIZE = 3;
    var start = (page - 1) * PAGE_SIZE;
    var slice = g.items.slice(start, start + PAGE_SIZE);
    var html = '';
    slice.forEach(function (it) { html += seriesEpItemHtml(g, it); });
    return html;
  }

  // 分页条 HTML：< 1 2 3 >，箭头 + 页码；当前页加粗橙，禁用端点
  function paginationHtml(slug, totalPages, page) {
    var ARROW_LEFT = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true"><polygon points="15 5 7 12 15 19 15 5"/></svg>';
    var ARROW_RIGHT = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true"><polygon points="9 5 17 12 9 19 9 5"/></svg>';
    var html = ''
      + '<nav class="series-pagination" aria-label="系列分页" data-slug="' + escapeHtml(slug) + '">'
      + '<button type="button" class="pg-arrow" data-action="pg-prev" data-slug="' + escapeHtml(slug) + '"'
      + (page <= 1 ? ' disabled aria-disabled="true"' : ' aria-label="上一页"') + '>'
      + ARROW_LEFT + '</button>';
    for (var p = 1; p <= totalPages; p++) {
      var active = (p === page);
      html += ''
        + '<button type="button" class="pg-num' + (active ? ' is-active' : '') + '"'
        + ' data-action="pg-num" data-slug="' + escapeHtml(slug) + '" data-page="' + p + '"'
        + (active ? ' aria-current="page"' : ' aria-label="第 ' + p + ' 页"') + '>'
        + p + '</button>';
    }
    html += ''
      + '<button type="button" class="pg-arrow" data-action="pg-next" data-slug="' + escapeHtml(slug) + '"'
      + (page >= totalPages ? ' disabled aria-disabled="true"' : ' aria-label="下一页"') + '>'
      + ARROW_RIGHT + '</button>'
      + '</nav>';
    return html;
  }

  // 抽出来复用：单集 <li> HTML
  function seriesEpItemHtml(g, it) {
    var epIdx = it.ep_index || it.episode || 1;
    return ''
      + '<li class="series-ep-item">'
      + '<span class="series-ep-num">EP ' + pad(epIdx) + '</span>'
      + '<a class="series-ep-title" href="' + escapeHtml('series/' + g.slug + '/ep-' + pad(epIdx) + '/shownotes.md')
      + '" title="' + escapeHtml(it.title) + '">' + escapeHtml(it.title) + '</a>'
      + '<span class="series-ep-dur">' + fmtDur(it.duration) + '</span>'
      + '<button type="button" class="series-ep-play" data-action="play-now" data-audio="'
      + escapeHtml(it.url) + '" data-title="' + escapeHtml(it.title) + '" data-series="'
      + escapeHtml(it.series) + '" data-duration="' + (it.duration || 0)
      + '" aria-label="听 ' + escapeHtml(it.title) + '">' + PLAY_SVG + '</button>'
      + '</li>';
  }

  // 分页 click handler（一次性事件委托）— 替代上一版的 +N 折叠行
  // 缓存：每张 series-card 的 _items（g.items 引用）
  function bindSeriesPagination() {
    var slot = document.getElementById('series-list');
    if (!slot || slot._pgBound) return;
    slot._pgBound = true;
    slot.addEventListener('click', function (ev) {
      var arrow = ev.target.closest('.pg-arrow');
      var num = ev.target.closest('.pg-num');
      var btn = arrow || num;
      if (!btn) return;
      if (btn.disabled || btn.getAttribute('aria-disabled') === 'true') return;
      ev.preventDefault();
      var action = btn.dataset.action || '';

      // ---- 列表级分页：< 1 2 > 在 series-card 之外 ----
      if (action === 'list-prev' || action === 'list-next' || action === 'list-num') {
        var pager = btn.closest('.series-list-pager');
        if (!pager) return;
        var cur = parseInt(pager.getAttribute('data-page') || '1', 10);
        var totalPages = parseInt(pager.getAttribute('data-total-pages') || '1', 10);
        var next = cur;
        if (action === 'list-prev') next = Math.max(1, cur - 1);
        else if (action === 'list-next') next = Math.min(totalPages, cur + 1);
        else next = parseInt(btn.dataset.page, 10);
        if (next === cur) return;
        // 隐藏所有 list-page，显示目标
        var grids = slot.querySelectorAll('.series-grid');
        grids.forEach(function (g) {
          if (parseInt(g.getAttribute('data-list-page'), 10) === next) g.removeAttribute('hidden');
          else g.setAttribute('hidden', '');
        });
        // 重渲 pager 整条
        pager.outerHTML = listPagerHtml(totalPages, next);
        return;
      }

      // ---- 单 series 内部 ep 分页：< 1 2 3 > 在 series-card 里 ----
      var slug = btn.dataset.slug;
      var card = btn.closest('.series-card');
      if (!card) return;
      var ol = card.querySelector('.series-ep-list');
      var innerPager = card.querySelector('.series-pagination:not(.series-list-pager)');
      var cur2 = parseInt(ol.getAttribute('data-page') || '1', 10);
      var totalPages2 = parseInt(card.getAttribute('data-total-pages') || '1', 10);
      var next2 = cur2;
      if (action === 'pg-prev') next2 = Math.max(1, cur2 - 1);
      else if (action === 'pg-next') next2 = Math.min(totalPages2, cur2 + 1);
      else next2 = parseInt(btn.dataset.page, 10);
      if (next2 === cur2) return;
      var items = card._items || [];
      ol.setAttribute('data-page', next2);
      ol.innerHTML = renderPage({ slug: slug, items: items }, next2);
      if (innerPager) innerPager.outerHTML = paginationHtml(slug, totalPages2, next2);
    });
  }

  function renderFeaturedCta(groups) {
    // 渲染 #hero-featured 占位 div 的内容
    var slot = document.getElementById('hero-featured');
    if (!slot) return;
    if (!groups.length || !groups[0].items.length) return;
    var featured = groups[0].items[0];
    slot.innerHTML = ''
      + '<a class="btn btn-primary" href="' + escapeHtml(featured.url) + '" data-action="play-now" data-audio="'
      + escapeHtml(featured.url) + '" data-title="' + escapeHtml(featured.title) + '" data-series="'
      + escapeHtml(featured.series) + '" data-duration="' + (featured.duration || 0) + '">'
      + PLAY_SVG + '<span>听最新一期</span></a>';
    // 同步更新 hero 区的 alt text（cover 图 alt 用 featured.title）
    var heroImg = document.querySelector('.hero-img');
    if (heroImg) heroImg.alt = (featured.title || '') + ' 封面';
  }

  function renderError(msg) {
    var html = '<p class="lead">' + escapeHtml(msg) + '</p>';
    var latestSlot = document.getElementById('latest-list');
    var seriesSlot = document.getElementById('series-list');
    if (latestSlot) latestSlot.innerHTML = html;
    if (seriesSlot) seriesSlot.innerHTML = html;
  }

  function init() {
    fetch('manifest.json', { cache: 'no-cache' })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (data) {
        var eps = (data && data.episodes) || [];
        var groups = groupBySeries(eps);
        var latestSlot = document.getElementById('latest-list');
        if (latestSlot) latestSlot.innerHTML = renderLatest(groups);
        var seriesSlot = document.getElementById('series-list');
        if (seriesSlot) seriesSlot.innerHTML = renderSeries(groups);
        renderFeaturedCta(groups);
        bindSeriesPagination();
      })
      .catch(function (err) {
        console.warn('[feed] manifest fetch failed:', err);
        renderError('最新集暂不可用，请刷新重试。');
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();