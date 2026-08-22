/*
 * SomaPerf SDK v0.2.0
 * 轻量真实用户监测脚本：性能、卡顿、点击、停留、Bot 信号。
 * 无依赖，兼容旧浏览器与微信内置浏览器。
 *
 * 用法：
 *   <script src="soma-perf.js"></script>
 *   <script>
 *     window.SomaPerf.init({ endpoint: "https://your-site/collect", siteId: "somaagent" });
 *   </script>
 */
(function (global) {
  'use strict';

  var VERSION = '0.2.0';
  var cfg = {
    endpoint: '',
    siteId: 'default',
    token: '',            // 与采集服务 SOMA_SITE_TOKEN 一致；空则不校验
    sampleRate: 1,        // 0~1，大流量时可抽样
    debug: false,
    heartbeatMs: 60000
  };

  var queue = [];
  var MAX_QUEUE = 40;
  var FLUSH_INTERVAL = 15000;
  var startedAt = Date.now();
  var visitorId = null;
  var sessionId = null;
  var clicks = 0;
  var longTasks = 0;
  var longTaskMs = 0;
  var jsErrors = 0;
  var resourceErrors = 0;
  var maxScrollDepth = 0;
  var hiddenMs = 0;
  var hiddenSince = null;
  var fcp = null;
  var lcp = null;
  var cls = 0;
  var inp = null;
  var ttfb = null;
  var domReady = null;
  var loadEvent = null;
  var exitSent = false;
  var lastClickAt = 0;
  var lastScrollAt = 0;

  function log() {
    if (cfg.debug && global.console && global.console.log) {
      global.console.log.apply(global.console, ['[SomaPerf]'].concat([].slice.call(arguments)));
    }
  }

  function genId(prefix) {
    var r = '';
    try {
      r = (global.crypto && global.crypto.getRandomValues) ?
        Array.prototype.map.call(global.crypto.getRandomValues(new Uint32Array(4)), function (n) {
          return n.toString(36);
        }).join('') :
        Math.random().toString(36).slice(2) + Date.now().toString(36);
    } catch (e) {
      r = Math.random().toString(36).slice(2) + Date.now().toString(36);
    }
    return (prefix || 'id') + '_' + r;
  }

  function getVisitorId() {
    try {
      var k = 'soma_perf_visitor';
      var v = global.localStorage.getItem(k);
      if (!v) {
        v = genId('v');
        global.localStorage.setItem(k, v);
      }
      return v;
    } catch (e) {
      return genId('v');
    }
  }

  function getSessionId() {
    try {
      var k = 'soma_perf_session';
      var v = global.sessionStorage.getItem(k);
      if (!v) {
        v = genId('s');
        global.sessionStorage.setItem(k, v);
      }
      return v;
    } catch (e) {
      return genId('s');
    }
  }

  function uaInfo(ua) {
    ua = ua || '';
    var info = { device: 'pc', os: 'other', browser: 'other', isWechat: false, isBot: false };
    if (/bot|crawl|spider|slurp|headless|phantom|curl|wget|python|java-|node|scrapy/i.test(ua)) {
      info.isBot = true;
    }
    if (/MicroMessenger/i.test(ua)) {
      info.browser = 'wechat';
      info.isWechat = true;
    } else if (/Edg\//i.test(ua)) {
      info.browser = 'edge';
    } else if (/OPR\//i.test(ua) || /Opera/i.test(ua)) {
      info.browser = 'opera';
    } else if (/Chrome\//i.test(ua)) {
      info.browser = 'chrome';
    } else if (/Firefox\//i.test(ua)) {
      info.browser = 'firefox';
    } else if (/Safari\//i.test(ua)) {
      info.browser = 'safari';
    } else if (/MSIE|Trident/i.test(ua)) {
      info.browser = 'ie';
    }
    if (/Android/i.test(ua)) {
      info.os = 'android';
      info.device = /Mobile/i.test(ua) ? 'mobile' : 'tablet';
    } else if (/iPhone|iPad|iPod/i.test(ua)) {
      info.os = 'ios';
      info.device = /iPad/i.test(ua) ? 'tablet' : 'mobile';
    } else if (/Windows Phone/i.test(ua)) {
      info.os = 'wp';
      info.device = 'mobile';
    } else if (/Windows/i.test(ua)) {
      info.os = 'windows';
    } else if (/Mac OS X/i.test(ua)) {
      info.os = 'macos';
    } else if (/Linux/i.test(ua)) {
      info.os = 'linux';
    }
    return info;
  }

  function botHints() {
    var hints = {};
    var nav = global.navigator || {};
    try { hints.webdriver = !!nav.webdriver; } catch (e) {}
    try { hints.languages = (nav.languages && nav.languages.length) || 0; } catch (e) {}
    try { hints.plugins = (nav.plugins && nav.plugins.length) || 0; } catch (e) {}
    try { hints.cores = nav.hardwareConcurrency || 0; } catch (e) {}
    try { hints.memory = nav.deviceMemory || 0; } catch (e) {}
    try { hints.touch = ('ontouchstart' in global); } catch (e) {}
    try { hints.screen = global.screen ? global.screen.width + 'x' + global.screen.height : ''; } catch (e) {}
    return hints;
  }

  function baseData(type, extra) {
    var info = uaInfo(global.navigator ? global.navigator.userAgent : '');
    var data = {
      type: type,
      ts: Date.now(),
      siteId: cfg.siteId,
      token: cfg.token || '',
      visitorId: visitorId,
      sessionId: sessionId,
      page: global.location ? global.location.pathname + global.location.search : '',
      referrer: global.document ? global.document.referrer : '',
      ua: global.navigator ? global.navigator.userAgent : '',
      device: info.device,
      os: info.os,
      browser: info.browser,
      isWechat: info.isWechat ? 1 : 0,
      uaBot: info.isBot ? 1 : 0,
      viewport: (global.innerWidth || 0) + 'x' + (global.innerHeight || 0),
      lang: ((global.navigator && global.navigator.language) || '') + '|' + ((global.navigator && global.navigator.languages) || []).join(','),
      botHints: botHints()
    };
    if (extra) {
      for (var k in extra) {
        if (Object.prototype.hasOwnProperty.call(extra, k)) data[k] = extra[k];
      }
    }
    return data;
  }

  function send(type, extra) {
    queue.push(baseData(type, extra));
    if (queue.length >= MAX_QUEUE) flush();
  }

  function flush() {
    if (!cfg.endpoint || !queue.length) return;
    var payload = queue.splice(0, queue.length);
    var body = JSON.stringify(payload);
    var nav = global.navigator || {};
    try {
      if (nav.sendBeacon) {
        nav.sendBeacon(cfg.endpoint, new Blob([body], { type: 'application/json' }));
        return;
      }
    } catch (e) {}
    try {
      if (global.fetch) {
        global.fetch(cfg.endpoint, {
          method: 'POST',
          keepalive: true,
          headers: { 'Content-Type': 'application/json' },
          body: body
        });
        return;
      }
    } catch (e) {}
    try {
      var img = new Image();
      img.src = cfg.endpoint + (cfg.endpoint.indexOf('?') >= 0 ? '&' : '?') + 'data=' + encodeURIComponent(body);
    } catch (e) {}
  }

  function trackTimings() {
    var perf = global.performance;
    if (!perf) return;
    try {
      var navEntries = perf.getEntriesByType('navigation');
      if (navEntries && navEntries.length) {
        var nav = navEntries[0];
        if (nav.responseStart > 0) ttfb = Math.round(nav.responseStart - nav.startTime);
        if (nav.domContentLoadedEventEnd > 0) domReady = Math.round(nav.domContentLoadedEventEnd - nav.startTime);
        if (nav.loadEventEnd > 0) loadEvent = Math.round(nav.loadEventEnd - nav.startTime);
      }
    } catch (e) {}
    try {
      var paints = perf.getEntriesByType('paint') || [];
      for (var i = 0; i < paints.length; i++) {
        if (paints[i].name === 'first-contentful-paint') fcp = Math.round(paints[i].startTime);
      }
    } catch (e) {}
    send('perf', { ttfb: ttfb, fcp: fcp, domReady: domReady, loadEvent: loadEvent });
  }

  function observePerf() {
    if (!global.PerformanceObserver) return;

    // 逐个类型监听：兼容 Safari/微信内置浏览器（它们不支持
    // entryTypes 数组 + buffered 的组合），并自动降级。
    function watch(type, handler) {
      var obs = null;
      try {
        obs = new PerformanceObserver(handler);
        obs.observe({ type: type, buffered: true });
        return;
      } catch (e) {}
      try {
        if (!obs) obs = new PerformanceObserver(handler);
        obs.observe({ type: type });
      } catch (e) {}
    }

    watch('paint', function (list) {
      var entries = list.getEntries();
      for (var i = 0; i < entries.length; i++) {
        if (entries[i].name === 'first-contentful-paint') {
          fcp = Math.round(entries[i].startTime);
        }
      }
    });
    watch('largest-contentful-paint', function (list) {
      var entries = list.getEntries();
      for (var i = 0; i < entries.length; i++) {
        lcp = Math.round(entries[i].startTime);
      }
    });
    watch('layout-shift', function (list) {
      var entries = list.getEntries();
      for (var i = 0; i < entries.length; i++) {
        if (!entries[i].hadRecentInput) {
          cls = Math.round((cls + entries[i].value) * 1000) / 1000;
        }
      }
    });
    watch('longtask', function (list) {
      var entries = list.getEntries();
      for (var i = 0; i < entries.length; i++) {
        longTasks++;
        longTaskMs += entries[i].duration;
      }
    });
    watch('event', function (list) {
      var entries = list.getEntries();
      for (var i = 0; i < entries.length; i++) {
        var e = entries[i];
        if (e.duration > 0 && (!('interactionId' in e) || e.interactionId > 0)) {
          if (inp === null || e.duration > inp) inp = Math.round(e.duration);
        }
      }
    });
  }

  function trackErrors() {
    global.addEventListener('error', function (ev) {
      var t = ev.target || {};
      var tag = (t.tagName || '').toLowerCase();
      if (tag === 'script' || tag === 'img' || tag === 'link' || tag === 'iframe' || t.src) {
        resourceErrors++;
        send('resource_error', { url: (t.src || t.href || '').slice(0, 300) });
      } else {
        jsErrors++;
        send('js_error', {
          message: (ev.message || '').slice(0, 300),
          source: (ev.filename || '').slice(0, 200),
          line: ev.lineno || 0,
          col: ev.colno || 0
        });
      }
    }, true);
    global.addEventListener('unhandledrejection', function (ev) {
      jsErrors++;
      var reason = 'UnhandledPromiseRejection';
      try {
        if (ev.reason) reason = (ev.reason.message || ev.reason.toString() || reason).slice(0, 300);
      } catch (e) {}
      send('js_error', { message: reason, source: 'unhandledrejection' });
    });
  }

  function trackClicks() {
    if (!global.document) return;
    global.document.addEventListener('click', function (ev) {
      var now = Date.now();
      if (now - lastClickAt < 250) return;
      lastClickAt = now;
      clicks++;
      var t = ev.target || {};
      var text = '';
      try {
        text = (t.innerText || t.value || '').toString().slice(0, 50).replace(/\s+/g, ' ').trim();
      } catch (e) {}
      var selector = '';
      try {
        var parts = [];
        var node = t;
        while (node && node !== global.document.body && parts.length < 3) {
          var part = node.tagName ? node.tagName.toLowerCase() : '';
          if (node.id) part += '#' + node.id;
          else if (node.className && typeof node.className === 'string') part += '.' + node.className.split(/\s+/)[0];
          else if (node.getAttribute && node.getAttribute('data-event')) part += '[data-event=' + node.getAttribute('data-event') + ']';
          if (!part) break;
          parts.unshift(part);
          node = node.parentNode;
        }
        selector = parts.join(' > ');
      } catch (e) {}
      send('click', {
        x: Math.round(ev.clientX || 0),
        y: Math.round(ev.clientY || 0),
        tag: (t.tagName || '').toLowerCase(),
        text: text,
        href: (t.href || '').slice(0, 200),
        selector: selector
      });
    }, true);
  }

  function trackScroll() {
    if (!global.document) return;
    global.document.addEventListener('scroll', function () {
      var now = Date.now();
      if (now - lastScrollAt < 300) return;
      lastScrollAt = now;
      var doc = global.document.documentElement || global.document.body;
      var max = (doc.scrollHeight || 0) - (global.innerHeight || 0);
      var cur = Math.max(global.pageYOffset || 0, global.document.body ? global.document.body.scrollTop || 0 : 0);
      if (max > 0) {
        var depth = Math.round((cur / max) * 100);
        if (depth > maxScrollDepth) maxScrollDepth = depth;
      }
    }, { passive: true });
  }

  function getActiveMs() {
    var duration = Date.now() - startedAt;
    var hidden = hiddenMs + (hiddenSince ? Date.now() - hiddenSince : 0);
    return Math.max(duration - hidden, 0);
  }

  function exitData() {
    return {
      durationMs: Date.now() - startedAt,
      activeMs: getActiveMs(),
      clicks: clicks,
      scrollDepth: maxScrollDepth,
      longTasks: longTasks,
      longTaskMs: Math.round(longTaskMs),
      jsErrors: jsErrors,
      resourceErrors: resourceErrors,
      fcp: fcp,
      lcp: lcp,
      cls: cls,
      inp: inp,
      ttfb: ttfb
    };
  }

  function trackVisibility() {
    if (!global.document) return;
    global.document.addEventListener('visibilitychange', function () {
      if (global.document.hidden || global.document.visibilityState === 'hidden') {
        hiddenSince = hiddenSince === null ? Date.now() : hiddenSince;
        if (!exitSent) {
          exitSent = true;
          send('page_exit', exitData());
        }
        flush();
      } else if (hiddenSince !== null) {
        hiddenMs += Date.now() - hiddenSince;
        hiddenSince = null;
      }
    });
    global.addEventListener('pagehide', function () {
      if (!exitSent) {
        exitSent = true;
        send('page_exit', exitData());
      }
      flush();
    });
  }

  function init(opts) {
    opts = opts || {};
    for (var k in opts) {
      if (Object.prototype.hasOwnProperty.call(opts, k)) cfg[k] = opts[k];
    }
    if (!cfg.endpoint) {
      log('未配置 endpoint，数据不会上报');
      return;
    }
    if (Math.random() >= (cfg.sampleRate || 1)) {
      log('未命中采样，本页面不上报');
      return;
    }
    visitorId = getVisitorId();
    sessionId = getSessionId();
    send('page_view', { ttfb: ttfb, fcp: fcp });
    observePerf();
    trackErrors();
    trackClicks();
    trackScroll();
    trackVisibility();
    if (global.addEventListener) {
      global.addEventListener('load', function () { trackTimings(); });
    }
    setInterval(function () { flush(); }, FLUSH_INTERVAL);
    setInterval(function () {
      if (!global.document || !global.document.hidden) send('heartbeat', { activeMs: getActiveMs() });
    }, cfg.heartbeatMs);
    log('SDK 已启动，站点', cfg.siteId);
  }

  global.SomaPerf = {
    version: VERSION,
    init: init,
    flush: flush,
    _queue: function () { return queue.slice(); }
  };
})(window);
