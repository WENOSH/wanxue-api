"""User System E2E Test"""
import urllib.request, json, sys
if sys.stdout.encoding != 'utf-8': sys.stdout.reconfigure(encoding='utf-8', errors='replace')
API = 'https://wanxue-api.onrender.com'
OK=0; FAIL=0

def check(n, ok, d=''):
    global OK,FAIL
    if ok: OK+=1; print(f'  [PASS] {n}')
    else: FAIL+=1; print(f'  [FAIL] {n} - {d}')

def api(path, data=None, method='GET'):
    url = f'{API}{path}'
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body,
        headers={'Content-Type': 'application/json'} if data else {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

# 1. Send SMS code
s, d = api('/api/auth/send-code', {'phone':'13800138001'}, 'POST')
check('Send code', s==200, str(d))

# 2. Register with test code 888888
s, d = api('/api/auth/register', {'phone':'13800138001','password':'test123','sms_code':'888888'}, 'POST')
check('Register', s==200 and d.get('success'))
token = d.get('token','')
check('Got token', bool(token))

# 3. Duplicate reject
s, d = api('/api/auth/register', {'phone':'13800138001','password':'test123','sms_code':'888888'}, 'POST')
check('Duplicate', s==200 and not d.get('success'))

# 4. Login
s, d = api('/api/auth/login', {'phone':'13800138001','password':'test123'}, 'POST')
check('Login', s==200 and d.get('success'))
token2 = d.get('token','')
check('New token', bool(token2))

# 5. Profile with token
req = urllib.request.Request(f'{API}/api/auth/profile', headers={'Authorization': f'Bearer {token2}'})
with urllib.request.urlopen(req, timeout=30) as d:
    r = json.loads(d.read())
    check('Profile', r.get('success'))

# 6. Summary
req = urllib.request.Request(f'{API}/api/auth/learning/summary', headers={'Authorization': f'Bearer {token2}'})
with urllib.request.urlopen(req, timeout=30) as d:
    r = json.loads(d.read())
    check('Summary', r.get('success'))

# 7. Advice
req = urllib.request.Request(f'{API}/api/auth/learning/advice', headers={'Authorization': f'Bearer {token2}'})
with urllib.request.urlopen(req, timeout=30) as d:
    r = json.loads(d.read())
    check('AI advice', r.get('success'))

# 8. No token = 401
s, _ = api('/api/auth/profile')
check('Reject no-token', s!=200)

print(f'\n{OK}/{OK+FAIL} passed')
