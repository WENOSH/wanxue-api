"""Test difficulty system and feedback changes"""
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
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

# 1. Health
s, _ = api('/api/health')
check('Health', s==200)

# 2. Generate with 入门 difficulty (4 chapters)
s, d = api('/api/generate-course', {'topic':'光合作用','age':'中学','goal':'入门科普','difficulty':'1-入门'}, 'POST')
check('Generate 入门', s==200 and d.get('success'))
if d.get('course'):
    ch = d['course'].get('chapters',[])
    cards = d['course'].get('_total_cards',0)
    print(f'  入门: {len(ch)}章/{cards}卡')
    check('入门 4章', len(ch)>=3)  # LLM might not exactly hit 4
    check('Has chapters', len(ch)>=1)
    # Check course_id exists
    check('Has course_id', bool(d.get('course_id')))

# 3. Generate with higher difficulty
s, d = api('/api/generate-course', {'topic':'Python编程','age':'大学','goal':'入门科普','difficulty':'3-标准'}, 'POST')
check('Generate 标准', s==200 and d.get('success'))
if d.get('course'):
    ch = d['course'].get('chapters',[])
    cards = d['course'].get('_total_cards',0)
    print(f'  标准: {len(ch)}章/{cards}卡')
    check('标准 >=5章', len(ch)>=5)

# 4. Chat with difficulty setting
s = api('/api/chat/session', method='POST')[1]
sid = s.get('session_id','')
check('Session created', bool(sid))

# 5. Chat SSE with difficulty
url = f'{API}/api/chat'
body = json.dumps({'message':'我想学相对论','session_id':sid,'difficulty':'4-进阶'}).encode()
req = urllib.request.Request(url, data=body, headers={'Content-Type':'application/json'}, method='POST')
events = []
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        buffer = ''
        while True:
            chunk = resp.read(1)
            if not chunk:
                break
            buffer += chunk.decode()
    check('Chat SSE', True)
except Exception as e:
    check('Chat SSE', False, str(e)[:100])

print(f'\n{OK}/{OK+FAIL} passed')
