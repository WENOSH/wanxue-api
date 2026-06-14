// Wanxue PWA Service Worker
// 策略：app shell 缓存优先，API 请求网络优先（断网降级到缓存）

const CACHE_NAME = 'wanxue-v1';
const PRECACHE_URLS = [
  '/static/app.html',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

// 安装：预缓存关键资源
self.addEventListener('install', (event) => {
  console.log('[SW] installing...');
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())  // 立即激活新 SW
  );
});

// 激活：清旧缓存
self.addEventListener('activate', (event) => {
  console.log('[SW] activating...');
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// 拦截请求
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // API 请求：网络优先（断网降级）
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(event.request)
        .catch(() => new Response(
          JSON.stringify({ error: 'offline', message: '离线状态，请检查网络连接' }),
          { status: 503, headers: { 'Content-Type': 'application/json' } }
        ))
    );
    return;
  }

  // SSE 流（chat 端点）：绝不缓存，透传
  if (event.request.headers.get('Accept')?.includes('text/event-stream')) {
    return;  // 不响应，让浏览器正常处理
  }

  // 静态资源：缓存优先
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) {
        // 后台更新缓存
        fetch(event.request).then((response) => {
          if (response.ok) {
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, response));
          }
        }).catch(() => {});
        return cached;
      }
      // 没缓存就去网络
      return fetch(event.request).then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      }).catch(() => {
        // 离线 + 没缓存 → 返回友好提示
        if (event.request.mode === 'navigate') {
          return caches.match('/static/app.html');
        }
      });
    })
  );
});

// 接收消息：跳过等待（用于更新）
self.addEventListener('message', (event) => {
  if (event.data === 'SKIP_WAITING') self.skipWaiting();
});
