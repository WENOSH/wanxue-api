""" WanXue Synchronizer Injector — 跨端进度同步器自动注入 """


def generate_sync_js(course_id: str, storage_key: str,
                     chapter_totals: list, total_cards: int) -> str:
    """生成参数化的同步器 JavaScript 代码

    Args:
        course_id: 课程唯一标识
        storage_key: localStorage key
        chapter_totals: 每章卡片数数组 [0, ch1_count, ch2_count, ...]
        total_cards: 总卡片数
    """
    return f'''<!-- ===== WanXue 跨端进度同步器 (自动注入) ===== -->
<script>
(function() {{
  'use strict';

  // 环境检测
  var ENV = {{
    isWeixin: /MicroMessenger/i.test(navigator.userAgent),
    isMiniProgram: false,
    isUniApp: typeof uni !== 'undefined' && !!uni.postMessage,
    isIframe: window.self !== window.top
  }};
  if (ENV.isWeixin) {{
    ENV.isMiniProgram = window.__wxjs_environment === 'miniprogram';
  }}

  // 课程配置
  var CHAPTER_TOTALS = {chapter_totals};
  var TOTAL_CARDS = {total_cards};
  var STORAGE_KEY = '{storage_key}';
  var COURSE_ID = '{course_id}';

  // 进度读取
  function readProgress() {{
    try {{
      var data = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{}}');
      var ch = data.ch || 1;
      var idx = data.idx || 0;
      var completed = 0;
      for (var i = 1; i < ch; i++) completed += CHAPTER_TOTALS[i];
      completed += idx;
      return {{
        courseId: COURSE_ID,
        chapter: ch,
        cardIndex: idx,
        chapterTotal: CHAPTER_TOTALS[ch] || 0,
        completedCards: completed,
        totalCards: TOTAL_CARDS,
        percent: Math.min(100, Math.round((completed / TOTAL_CARDS) * 100)),
        lastStudyAt: data.time || Date.now(),
        timestamp: Date.now()
      }};
    }} catch(e) {{
      return {{ courseId: COURSE_ID, chapter: 1, cardIndex: 0, chapterTotal: CHAPTER_TOTALS[1]||0, completedCards: 0, totalCards: TOTAL_CARDS, percent: 0, lastStudyAt: Date.now(), timestamp: Date.now() }};
    }}
  }}

  // 上报（有去重）
  var lastHash = '';
  function report(force) {{
    var p = readProgress();
    var hash = p.chapter + '|' + p.cardIndex + '|' + p.percent;
    if (!force && hash === lastHash) return;
    lastHash = hash;
    var payload = {{ type: 'wanxue_progress' }};
    for (var k in p) payload[k] = p[k];

    if (ENV.isIframe) window.parent.postMessage(payload, '*');
    if (window.WANXUE_SYNC_API) {{
      fetch(window.WANXUE_SYNC_API, {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify(p), keepalive: true }}).catch(function(){{}});
    }}
  }}

  document.addEventListener('visibilitychange', function() {{ if (document.visibilityState === 'hidden') report(true); }});
  window.addEventListener('beforeunload', function() {{ report(true); }});
  setInterval(function() {{ report(false); }}, 20000);

  // 劫持 updateUI → 翻页后 300ms 上报
  if (typeof window.updateUI === 'function') {{
    var _orig = window.updateUI;
    window.updateUI = function() {{
      _orig.apply(this, arguments);
      setTimeout(function() {{ report(true); }}, 300);
    }};
  }}

  // 翻页按钮点击兜底
  document.addEventListener('click', function(e) {{
    if (e.target.closest('button')) setTimeout(function() {{ report(true); }}, 500);
  }}, true);

  // 初始上报（等页面加载完）
  setTimeout(function() {{ report(true); }}, 1500);

  window.__wanxueSyncReport = function(f) {{ report(f !== false); }};
}})();
</script>
<!-- ===== WanXue 同步器 END ===== -->
'''


def generate_sync_css() -> str:
    """同步器不需要额外 CSS，但保留接口"""
    return ""
