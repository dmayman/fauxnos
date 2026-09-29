#!/usr/bin/env python3
"""Demo proxy: real Fauxnos API plus three fake rooms (Garage, Office, Bedroom).

Everything passes through to the real server except calls that touch a fake
room, which are answered from in-memory state. Fake rooms can join real
groups (and each other) but never reach snapcast, so no audio goes anywhere.

    python3 dev/spoof_rooms_proxy.py            # listens on :8090
    REAL=http://fauxnos000.local:8080 PORT=8090 python3 dev/spoof_rooms_proxy.py

Point the web dev server at it with FAUXNOS_API=http://localhost:8090, and
the simulator with `defaults write dm.Fauxnos fauxnos.serverHost localhost:8090`.
"""
import copy
import json
import os
import re
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REAL = os.environ.get('REAL', 'http://fauxnos000.local:8080')
PORT = int(os.environ.get('PORT', '8090'))

FAKES = {'fauxnos901': 'Garage', 'fauxnos902': 'Office', 'fauxnos903': 'Bedroom'}
# Each fake is anchored to a client id: itself (own group) or the room it joined.
anchor = {f: f for f in FAKES}
volume = {f: 40 for f in FAKES}
lock = threading.Lock()


def resolve(f):
    """Follow fake→fake anchors to a real client id or a fake that's home."""
    seen = set()
    while f in FAKES and anchor[f] != f and f not in seen:
        seen.add(f)
        f = anchor[f]
    return f


def snapclient(f):
    return {
        'id': f, 'connected': True,
        'config': {'instance': 1, 'latency': 0, 'name': '',
                   'volume': {'muted': False, 'percent': volume[f]}},
        'host': {'name': f, 'ip': '0.0.0.0', 'mac': '', 'arch': '', 'os': 'spoofed'},
        'lastSeen': {'sec': 0, 'usec': 0},
        'snapclient': {'name': 'Snapclient', 'protocolVersion': 2, 'version': 'fake'},
    }


def fake_client(f):
    return {'client_id': f, 'name': FAKES[f], 'connected': True, 'has_adc': False,
            'dac_overlay': 'hifiberry-dac', 'dac_overlay_locked': False,
            'server_port': 0, 'zeroconf_port': 0, 'mac': ''}


def inject_groups(data):
    groups = data.get('groups', [])
    by_member = {c['id']: g for g in groups for c in g.get('clients', [])}
    homes = {}
    for f in FAKES:
        r = resolve(f)
        if r in by_member:
            by_member[r]['clients'].append(snapclient(f))
            continue
        home = r if r in FAKES else f  # real anchor went offline → stay home
        homes.setdefault(home, []).append(f)
    for home, members in homes.items():
        members.sort(key=lambda m: m != home)
        groups.append({
            'id': f'fake-group-{home}', 'name': '', 'muted': False,
            'home_client_id': home,
            'clients': [snapclient(m) for m in members],
            'sources': [{'id': 'spotify', 'label': 'Spotify', 'type': 'internal',
                         'category': 'default', 'volume_controller': 'snapcast'}],
            'stream_id': f'source_{home}_spotify',
            'available_streams': [{'id': f'source_{home}_spotify', 'status': 'idle'}],
        })
    data['groups'] = groups
    return data


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def do_GET(self): self.handle_any()
    def do_POST(self): self.handle_any()
    def do_PUT(self): self.handle_any()
    def do_DELETE(self): self.handle_any()
    def do_PATCH(self): self.handle_any()

    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_any(self):
        n = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(n) if n else b''
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            body = {}
        path = self.path.split('?')[0]

        with lock:
            fake = self.fake_response(path, body)
        if fake is not None:
            return self.send_json(*fake) if isinstance(fake, tuple) else self.send_json(fake)

        status, headers, resp = self.forward(raw)
        if status == 200 and self.command == 'GET' and path in ('/api/clients', '/api/groups'):
            data = json.loads(b''.join(resp))
            with lock:
                if path == '/api/clients':
                    data['clients'] = data.get('clients', []) + [fake_client(f) for f in FAKES]
                else:
                    inject_groups(data)
            return self.send_json(data)

        self.send_response(status)
        for k, v in headers:
            if k.lower() not in ('transfer-encoding', 'connection', 'content-length'):
                self.send_header(k, v)
        self.send_header('Transfer-Encoding', 'chunked')
        self.end_headers()
        for chunk in resp:  # streamed so SSE update logs still work
            self.wfile.write(b'%x\r\n%s\r\n' % (len(chunk), chunk))
            self.wfile.flush()
        self.wfile.write(b'0\r\n\r\n')

    def fake_response(self, path, body):
        """Answer calls that involve a fake room; None means forward."""
        cid, target = body.get('client_id'), body.get('target_client_id')
        if path == '/api/groups/join' and cid in FAKES:
            anchor[cid] = target if target != cid else cid
            return {'ok': True}
        if path == '/api/groups/join' and target in FAKES:
            return ({'error': 'Spoofed rooms cannot host real speakers'}, 409)
        if path == '/api/groups/return-home' and cid in FAKES:
            for o in FAKES:  # anything riding on this fake stays where it was
                if anchor[o] == cid and o != cid:
                    anchor[o] = resolve(cid)
            anchor[cid] = cid
            return {'ok': True}
        if path == '/api/groups/return-home' and not cid:
            for f in FAKES:
                anchor[f] = f
            return None
        if path == '/api/groups/source' and body.get('home_client_id') in FAKES:
            return {'ok': True}
        m = re.match(r'^/api/clients/(fauxnos9\d\d)(/.*)?$', path)
        if m and m.group(1) in FAKES:
            f, sub = m.group(1), m.group(2) or ''
            if sub == '/volume' and self.command == 'POST':
                volume[f] = int(body.get('value', volume[f]))
            if sub == '/sources':
                return {'sources': []}
            if sub == '' and self.command == 'GET':
                return fake_client(f)
            return {'ok': True}
        return None

    def forward(self, raw):
        req = urllib.request.Request(REAL + self.path, data=raw or None, method=self.command)
        for k in ('Content-Type', 'Accept'):
            if self.headers.get(k):
                req.add_header(k, self.headers[k])
        try:
            r = urllib.request.urlopen(req, timeout=600)
        except urllib.error.HTTPError as e:
            r = e
        except urllib.error.URLError as e:
            body = json.dumps({'error': f'upstream: {e.reason}'}).encode()
            return 502, [('Content-Type', 'application/json')], [body]

        def chunks():
            while True:
                c = r.read1(8192) if hasattr(r, 'read1') else r.read(8192)
                if not c:
                    break
                yield c
        return r.status if hasattr(r, 'status') else r.code, r.headers.items(), chunks()

    def log_message(self, fmt, *args):
        pass


if __name__ == '__main__':
    print(f'spoof proxy :{PORT} → {REAL} (+ {", ".join(FAKES.values())})')
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
