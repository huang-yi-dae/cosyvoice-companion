/* CosyVoice Studio — 共享 UI 层
 *
 * 目的：统一 toast / 活跃用户 chip / 骨架屏 / 活跃 QQ 记忆，
 * 消除 5 个页面各自手写导致的细节不一致（UX + 架构评审 P0）。
 *
 * 纯原生、无依赖，通过 <script src="/static/ui.js"></script> 引入（在 api.js 之后）。
 * 全局 window.UI。约定的 DOM id：#toast、#activeUserChip（可选存在）。
 */
(function (global) {
  'use strict';

  var toastTimer = null;

  /** 轻量 toast。err=true 用错误样式。依赖 #toast 元素（若无则降级为 alert）。 */
  function toast(msg, err) {
    var t = document.getElementById('toast');
    if (!t) { if (err) console.warn(msg); return; }
    t.textContent = msg;
    t.className = 'toast show' + (err ? ' err' : '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      t.className = 'toast' + (err ? ' err' : '');
    }, 2600);
  }

  /** 更新页头「当前：QQ xxx」chip，带一次高亮 flash。qq 为空则隐藏。 */
  function updateActiveUserChip(qq) {
    var chip = document.getElementById('activeUserChip');
    if (!chip) return;
    if (qq) {
      chip.textContent = '当前：QQ ' + qq;
      chip.hidden = false;
      chip.classList.remove('flash');
      void chip.offsetWidth; // 触发重排以重放动画
      chip.classList.add('flash');
    } else {
      chip.hidden = true;
    }
  }

  /** 活跃 QQ 的 localStorage 记忆（跨页面一致）。 */
  var ACTIVE_QQ_KEY = 'cosyvoice_active_qq';
  function rememberActiveQQ(qq) {
    try { if (qq) localStorage.setItem(ACTIVE_QQ_KEY, String(qq)); } catch (e) {}
  }
  function readRememberedQQ() {
    try { return localStorage.getItem(ACTIVE_QQ_KEY); } catch (e) { return null; }
  }
  /** 选定活跃 QQ：记忆值（若仍在列表中）> 配置 active_qq > 列表首个。 */
  function resolveActiveQQ(cfgActiveQQ, list) {
    var remembered = readRememberedQQ();
    if (remembered && (list || []).some(function (u) { return String(u.qq) === String(remembered); }))
      return remembered;
    return cfgActiveQQ || ((list && list[0] && list[0].qq) || null);
  }

  /** 持久化活跃 QQ 并同步更新 chip（页面切换用户时调用）。 */
  function persistActiveQQ(qq) {
    rememberActiveQQ(qq);
    updateActiveUserChip(qq);
  }

  /** 生成 n 行骨架屏占位 HTML（配合 studio.css 的 .skeleton 系列）。 */
  function skeletonRows(n, className) {
    var cls = className || 'skeleton-row';
    var out = [];
    for (var i = 0; i < (n || 3); i++) out.push('<div class="skeleton ' + cls + '"></div>');
    return out.join('');
  }

  global.UI = {
    toast: toast,
    updateActiveUserChip: updateActiveUserChip,
    persistActiveQQ: persistActiveQQ,
    rememberActiveQQ: rememberActiveQQ,
    readRememberedQQ: readRememberedQQ,
    resolveActiveQQ: resolveActiveQQ,
    skeletonRows: skeletonRows,
    ACTIVE_QQ_KEY: ACTIVE_QQ_KEY,
  };
})(window);
