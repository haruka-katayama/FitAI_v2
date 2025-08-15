// sw.js — API は触らない版（network-first for static, cache fallback）
// バージョンを上げると更新が確実に反映されます
const CACHE_NAME = 'fitai-static-v1.0.3';

// 事前キャッシュしたい静的ファイル（必要に応じて調整）
const STATIC_ASSETS = [
  '/',            // ルート
  '/index.html',  // エントリ
  '/static/logo.png',
  // '/static/styles.css',
  // '/static/app.js',
];

// --- Install: 事前キャッシュ & 即時制御に切替 ---
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(STATIC_ASSETS))
      .catch(() => Promise.resolve()) // オフライン初回等で失敗しても進める
  );
  self.skipWaiting();
});

// --- Activate: 旧キャッシュの掃除 & 即時制御 ---
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  clients.claim();
});

// --- Fetch: API（/ui, /api, /fitbit, /coach）や非GETは一切触らない ---
//       静的GETだけ network-first（成功時にキャッシュへ保存、失敗時はキャッシュをフォールバック）
self.addEventListener('fetch', (event) => {
  const req = event.request;

  // 非GETは触らない（POST/PUT/DELETE等はそのままブラウザに任せる）
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // 異なるオリジンは触らない（必要ならここを調整）
  if (url.origin !== self.location.origin) return;

  // API 系パスは触らない（重要：これで二重送信を防止）
  const isApiPath =
    url.pathname.startsWith('/ui/') ||
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/fitbit/') ||
    url.pathname.startsWith('/coach/');

  if (isApiPath) return;

  // ここから静的ファイルのみを扱う（1本化：必ず respondWith を使う）
  event.respondWith(
    fetch(req)
      .then((res) => {
        // 成功したらキャッシュへ保存（200系のみ）
        if (res && res.status === 200) {
          const resClone = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, resClone));
        }
        return res;
      })
      .catch(async () => {
        // ネットワーク失敗時はキャッシュをフォールバック
        const cached = await caches.match(req);
        if (cached) return cached;

        // ナビゲーション要求なら index.html をフォールバック（任意）
        if (req.mode === 'navigate') {
          const fallback = await caches.match('/index.html');
          if (fallback) return fallback;
        }

        // それでも無ければ失敗のまま
        throw new Error('Network error and no cache.');
      })
  );
});
