/* CosyVoice Studio — 共享 API 层
 *
 * 目的：消除 5 个页面各自手写 fetch/错误处理的重复（架构评审 P0）。
 * 所有 /api/* 调用统一走这里，错误统一归类为「原因 + 可操作建议」。
 *
 * 用法（全局 window.API）：
 *   const users = await API.get('/api/users');
 *   await API.post('/api/save/' + name);
 *   showStatus(API.friendlyError(e.message, isCloud), 'error');
 *
 * 纯原生、无依赖、无构建步骤，通过 <script src="/static/api.js"></script> 引入。
 */
(function (global) {
  'use strict';

  /** 统一 JSON 请求：非 2xx 抛出 Error(detail)。 */
  async function request(path, options) {
    const opts = Object.assign({ headers: {} }, options || {});
    if (opts.body && typeof opts.body !== 'string') {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(opts.body);
    }
    const res = await fetch(path, opts);
    let data = null;
    try { data = await res.json(); } catch (e) { /* 可能是空响应 */ }
    if (!res.ok) {
      const detail = (data && (data.detail || data.error)) || ('HTTP ' + res.status);
      const err = new Error(detail);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  const API = {
    request: request,
    get: function (path) { return request(path, { method: 'GET' }); },
    post: function (path, body) { return request(path, { method: 'POST', body: body }); },
    del: function (path) { return request(path, { method: 'DELETE' }); },

    /** 附加 ?qq= 查询参数（活跃用户）。 */
    withQQ: function (path, qq) {
      if (!qq) return path;
      const sep = path.indexOf('?') === -1 ? '?' : '&';
      return path + sep + 'qq=' + encodeURIComponent(qq);
    },

    /**
     * 把常见后端错误归类为「原因 + 可操作建议」。
     * 与合成/克隆场景相关；isCloud 影响兜底文案。
     * （权威实现，原先散落在 index.html / manage.html。）
     */
    friendlyError: function (msg, isCloud) {
      const m = String(msg || '');
      if (/模型|model|未下载|not found|checkpoint/i.test(m))
        return '合成失败：模型可能未下载或加载失败。请到「模型」页确认已下载所选模型。';
      if (/样本|voice|参考音频|reference|prompt.*wav/i.test(m))
        return '合成失败：语音样本无效或缺失。请换其它样本，或到「自动化」重新生成克隆样本。';
      if (/api.?key|dashscope|云端|unauthorized|401/i.test(m))
        return '合成失败：云端音色需要在 .env 配置 DASHSCOPE_API_KEY 后重试。';
      if (/timeout|超时|time.?out/i.test(m))
        return '合成失败：首次加载模型较慢导致超时，请稍候重试（本地模型加载约 1 分钟）。';
      if (/显存|cuda|out of memory|oom/i.test(m))
        return '合成失败：显存不足。可尝试更小的模型或缩短文本。';
      return '合成失败：' + (m || '未知错误') + (isCloud ? '' : '（可到「模型」页确认模型状态）');
    },
  };

  global.API = API;
})(window);
