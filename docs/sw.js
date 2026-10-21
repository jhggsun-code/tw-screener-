self.addEventListener('install',e=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(clients.claim()));
self.addEventListener('fetch',e=>{e.respondWith(fetch(e.request).then(r=>{var c=r.clone();
caches.open('v1').then(x=>x.put(e.request,c));return r;}).catch(()=>caches.match(e.request)));});