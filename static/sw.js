// sw.js - Service Worker for FitAI
const CACHE_NAME = 'fitai-v1.0.0';
const urlsToCache = [
    '/',
    '/manifest.json',
    'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js',
    'https://cdnjs.cloudflare.com/ajax/libs/flatpickr/4.6.13/flatpickr.min.js',
    'https://cdnjs.cloudflare.com/ajax/libs/flatpickr/4.6.13/flatpickr.min.css'
];

// インストール時
self.addEventListener('install', function(event) {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(function(cache) {
                console.log('Opened cache');
                return cache.addAll(urlsToCache);
            })
    );
});

// フェッチ時（ネットワーク優先、フォールバックでキャッシュ）
self.addEventListener('fetch', function(event) {
    // APIリクエストはキャッシュしない
    if (event.request.url.includes('/api/') || 
        event.request.url.includes('/ui/') ||
        event.request.url.includes('/fitbit/') ||
        event.request.url.includes('/coach/')) {
        return fetch(event.request);
    }

    event.respondWith(
        fetch(event.request)
            .then(function(response) {
                // レスポンスが有効な場合、キャッシュに保存
                if (response.status === 200) {
                    const responseToCache = response.clone();
                    caches.open(CACHE_NAME)
                        .then(function(cache) {
                            cache.put(event.request, responseToCache);
                        });
                }
                return response;
            })
            .catch(function() {
                // ネットワークエラーの場合、キャッシュから返す
                return caches.match(event.request)
                    .then(function(response) {
                        return response || new Response('オフラインです', {
                            status: 200,
                            headers: { 'Content-Type': 'text/plain; charset=utf-8' }
                        });
                    });
            })
    );
});

// アクティベート時（古いキャッシュを削除）
self.addEventListener('activate', function(event) {
    event.waitUntil(
        caches.keys().then(function(cacheNames) {
            return Promise.all(
                cacheNames.map(function(cacheName) {
                    if (cacheName !== CACHE_NAME) {
                        console.log('Deleting old cache:', cacheName);
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
});