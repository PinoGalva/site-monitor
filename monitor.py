#!/usr/bin/env python3
"""Monitor di uptime e velocita' per piu' siti. Solo libreria standard.

  python monitor.py check   # uptime + tempi di risposta (ogni 5 minuti)
  python monitor.py daily   # PageSpeed Insights + scadenza SSL (una volta al giorno)

Dati in docs/data/ (letti dalla dashboard docs/index.html).
Variabili d'ambiente: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID (avvisi), PSI_API_KEY (opzionale).
"""
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, 'docs', 'data')
CHECKS = os.path.join(DATA, 'checks.jsonl')
PSI = os.path.join(DATA, 'psi.jsonl')
STATE = os.path.join(DATA, 'state.json')
UA = 'SiteMonitor/1.0 (+uptime check)'


def now():
    return datetime.now(timezone.utc)


def load_config():
    with open(os.path.join(ROOT, 'config.json'), encoding='utf-8') as f:
        return json.load(f)


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, rows):
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, separators=(',', ':')) + '\n')


def load_state():
    if os.path.exists(STATE):
        with open(STATE, encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(state, f, indent=1, ensure_ascii=False)


def notify(text):
    token, chat = os.environ.get('TELEGRAM_TOKEN'), os.environ.get('TELEGRAM_CHAT_ID')
    print('ALERT:', text)
    if not token or not chat:
        return
    body = urllib.parse.urlencode({'chat_id': chat, 'text': text, 'disable_web_page_preview': 'true'}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request('https://api.telegram.org/bot%s/sendMessage' % token, data=body), timeout=20)
    except Exception as exc:  # un avviso fallito non deve far fallire il job
        print('Telegram non raggiungibile:', exc)


def fetch(entry, timeout=25):
    """Una richiesta GET: stato finale, tempo al primo byte (ms), tempo totale (ms)."""
    row = {'url': entry['url'], 'ok': False, 'status': None, 'ttfb': None, 'total': None, 'err': None}
    req = urllib.request.Request(entry['url'], headers={'User-Agent': UA, 'Accept-Encoding': 'identity'})
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            row['ttfb'] = round((time.perf_counter() - start) * 1000)
            body = resp.read(2_000_000)
            row['status'] = resp.status
    except urllib.error.HTTPError as exc:
        row['status'] = exc.code
        row['ttfb'] = round((time.perf_counter() - start) * 1000)
        row['err'] = 'HTTP %d' % exc.code
        body = b''
    except Exception as exc:
        row['err'] = type(exc).__name__ + ': ' + str(exc)[:120]
        return row
    row['total'] = round((time.perf_counter() - start) * 1000)
    expected = entry.get('expect_status', 200)
    row['ok'] = row['status'] == expected
    needle = entry.get('expect_text')
    if row['ok'] and needle and needle.encode('utf-8') not in body:
        row['ok'] = False
        row['err'] = 'testo atteso non trovato'
    return row


def cmd_check():
    cfg = load_config()
    state = load_state()
    stamp = now().isoformat(timespec='seconds')
    rows = read_jsonl(CHECKS)
    cutoff = (now() - timedelta(days=cfg.get('keep_days', 14))).isoformat()
    rows = [r for r in rows if r['t'] >= cutoff]

    for site in cfg['sites']:
        for entry in site['urls']:
            res = fetch(entry)
            if not res['ok'] and res['status'] is None:  # secondo tentativo: evita falsi allarmi di rete
                time.sleep(3)
                res = fetch(entry)
            res.update({'t': stamp, 'site': site['name']})
            rows.append(res)

            key = entry['url']
            st = state.setdefault(key, {'fails': 0, 'down': False, 'slow': False, 'since': None})
            if res['ok']:
                if st['down']:
                    notify('✅ %s di nuovo online\n%s\nOffline dal %s' % (site['name'], key, st['since']))
                st.update({'fails': 0, 'down': False, 'since': None})
                slow = res['total'] is not None and res['total'] > cfg['slow_ms']
                if slow and not st['slow']:
                    notify('🐢 %s lento: %d ms\n%s' % (site['name'], res['total'], key))
                st['slow'] = slow
            else:
                st['fails'] += 1
                if st['fails'] >= cfg.get('down_after_failures', 2) and not st['down']:
                    st['down'], st['since'] = True, stamp
                    notify('🔴 %s NON raggiungibile\n%s\n%s' % (site['name'], key, res['err'] or 'stato %s' % res['status']))
            print('%s %s %s %sms' % ('OK ' if res['ok'] else 'KO ', res['status'], key, res['total']))

    write_jsonl(CHECKS, rows)
    save_state(state)


def ssl_days_left(host):
    ctx = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=15) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            cert = tls.getpeercert()
    return (datetime.strptime(cert['notAfter'], '%b %d %H:%M:%S %Y %Z').replace(tzinfo=timezone.utc) - now()).days


def psi_run(url, strategy='mobile'):
    params = {'url': url, 'strategy': strategy, 'category': 'performance'}
    if os.environ.get('PSI_API_KEY'):
        params['key'] = os.environ['PSI_API_KEY']
    api = 'https://www.googleapis.com/pagespeedonline/v5/runPagespeed?' + urllib.parse.urlencode(params)
    with urllib.request.urlopen(api, timeout=120) as resp:
        data = json.load(resp)
    lh = data['lighthouseResult']
    audit = lambda k: round(lh['audits'][k]['numericValue'], 3 if k == 'cumulative-layout-shift' else 0)
    return {
        'score': round(lh['categories']['performance']['score'] * 100),
        'fcp': audit('first-contentful-paint'), 'lcp': audit('largest-contentful-paint'),
        'tbt': audit('total-blocking-time'), 'cls': audit('cumulative-layout-shift'),
        'si': audit('speed-index'),
    }


def cmd_daily():
    cfg = load_config()
    rows = read_jsonl(PSI)
    stamp = now().isoformat(timespec='seconds')
    for site in cfg['sites']:
        row = {'t': stamp, 'site': site['name'], 'url': site.get('psi_url') or site['urls'][0]['url']}
        try:
            row.update(psi_run(row['url']))
            print('PSI', site['name'], row['score'])
        except Exception as exc:
            row['err'] = str(exc)[:150]
            print('PSI errore', site['name'], exc)
        try:
            host = urllib.parse.urlparse(row['url']).hostname
            row['ssl_days'] = ssl_days_left(host)
            if row['ssl_days'] < cfg.get('ssl_warn_days', 14):
                notify('🔐 Certificato SSL di %s scade tra %d giorni' % (host, row['ssl_days']))
        except Exception as exc:
            print('SSL errore', exc)
        rows.append(row)
    write_jsonl(PSI, rows[-2000:])


if __name__ == '__main__':
    os.makedirs(DATA, exist_ok=True)
    commands = {'check': cmd_check, 'daily': cmd_daily}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(__doc__)
    commands[sys.argv[1]]()
