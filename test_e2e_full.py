"""
WanXue API 完整端到端测试
模拟手机APP流程：创建会话 → 发消息生成课程 → 接收SSE → 查看课程 → 分享 → 预览
"""
import urllib.request, json, sys, re
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

API = 'https://wanxue-api.onrender.com'
OK = 0; FAIL = 0

def check(name, ok, detail=''):
    global OK, FAIL
    if ok: OK += 1; print(f'  [PASS] {name}')
    else: FAIL += 1; print(f'  [FAIL] {name} - {detail}')

def api(path, data=None, method='GET'):
    url = f'{API}{path}'
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body,
        headers={'Content-Type': 'application/json'} if data else {},
        method=method)
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            ctype = resp.headers.get('Content-Type', '')
            if 'text/event-stream' in ctype:
                return resp.status, resp.read().decode('utf-8')
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        return e.code, body
    except Exception as e:
        return None, str(e)

print('=== WanXue API 完整链路测试 ===')
print()

# 1. Health
status, _ = api('/api/health')
check('Health check', status == 200)

# 2. Create session
status, d = api('/api/chat/session', method='POST')
check('Create session', status == 200)
sid = d.get('session_id', '')
check('Has session_id', bool(sid))

# 3. Generate course via chat
print('\\n[chat] Generating course...')
data = json.dumps({'message': '我想学光合作用', 'session_id': sid}).encode()
req = urllib.request.Request(f'{API}/api/chat', data=data,
    headers={'Content-Type': 'application/json'}, method='POST')
with urllib.request.urlopen(req, timeout=180) as resp:
    events = resp.read().decode('utf-8')

has_done = 'event: course_done' in events
has_err = 'event: error' in events
check('course_done event received', has_done)
check('No error in stream', not has_err)

# Extract course_id
m = re.search(r'"_course_id"\s*:\s*"([^"]+)"', events)
cid = m.group(1) if m else None
check('course_id extracted', bool(cid), str(cid))
print(f'  [INFO] course_id = {cid}')

# 4-7: Verify course via all endpoints
if cid:
    for label, path in [
        ('Course HTML accessible', f'/api/courses/{cid}/index.html'),
        ('Preview API', f'/api/courses/{cid}/preview'),
        ('Share page', f'/api/share/{cid}'),
    ]:
        status, body = api(path)
        check(label, status == 200, f'status={status}')

    # 8. Courses list
    status, cl = api('/api/courses')
    check('Courses list (200)', status == 200)
    if status == 200:
        ids = [c['course_id'] for c in cl.get('courses', [])]
        check(f'Course in list ({cid})', cid in ids)

    # 9. Direct generation (non-chat path)
    status, gen = api('/api/generate-course', {
        'topic': '机器学习', 'age': '成人', 'goal': '入门'
    }, method='POST')
    check('Direct generate (200)', status == 200, f'status={status}')
    if status == 200 and isinstance(gen, dict):
        cid2 = gen.get('course_id', '')
        check('Direct gen has course_id', bool(cid2))
        status2, _ = api(f"/api/courses/{cid2}/index.html")
        check('Direct gen HTML accessible', status2 == 200)

print(f'\\n=== 结果: {OK}/{OK+FAIL} 通过 ===')
if FAIL == 0: print('全部通过！手机应该可以正常使用了。')
else: print(f'有 {FAIL} 项失败需要修复')
