// sw.js — 静的ファイルのみ扱う許可リスト方式（APIは完全スルー）
const CACHE_NAME = 'fitai-static-v1.0.5';

// 必要なら事前キャッシュ（空でもOK）
const STATIC_ASSETS = [
  '/',            // ルート
  '/index.html',  // エントリ
  '/static/logo.png',
];

// --- Install: 事前キャッシュ & 即時有効化 ---
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(STATIC_ASSETS))
      .catch(() => Promise.resolve()) // 初回オフラインでも進める
  );
  self.skipWaiting();
});

// --- Activate: 旧キャッシュ掃除 & 直ちに制御開始 ---
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  clients.claim();
});

// --- Fetch: 静的GETだけを扱う（許可リスト拡張子）。API/非GET/クロスオリジンは全スルー ---
self.addEventListener('fetch', (event) => {
  const req = event.request;

  // 非GETは触らない（POST/PUT/DELETEなどはそのままブラウザに任せる）
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // クロスオリジンは触らない（必要あれば許可ドメインを追加）
  if (url.origin !== self.location.origin) return;

  // API/動的っぽいパスは触らない（念のため主要パスを除外）
  const isApiPath =
    url.pathname.startsWith('/ui/') ||
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/dashboard/') ||
    url.pathname.startsWith('/coach/') ||
    url.pathname.startsWith('/fitbit/') ||
    url.pathname.startsWith('/auth/');
  if (isApiPath) return;

  // 静的ファイルのみ扱う（許可拡張子）
  const isStaticFile = /\.(?:html|css|js|mjs|png|jpg|jpeg|webp|svg|ico|gif|json|map|txt|woff2?|ttf|eot)$/.test(url.pathname);
  if (!isStaticFile) return;

  // ここから静的だけ network-first（成功時キャッシュ、失敗時キャッシュフォールバック）
  event.respondWith(
    fetch(req)
      .then((res) => {
        // 200系だけキャッシュ
        if (res && res.status === 200) {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, clone));
        }
        return res;
      })
      .catch(async () => {
        // ネットワーク失敗時はキャッシュへ
        const cached = await caches.match(req);
        if (cached) return cached;

        // ナビゲーション要求なら index.html をフォールバック（任意）
        if (req.mode === 'navigate') {
          const fallback = await caches.match('/index.html');
          if (fallback) return fallback;
        }

        // それでも駄目なら失敗のまま
        throw new Error('Network error and no cache.');
      })
  );
});
