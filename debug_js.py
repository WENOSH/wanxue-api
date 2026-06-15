"""Check JS syntax errors in deployed app.html"""
import urllib.request
resp = urllib.request.urlopen('https://wanxue-api.onrender.com/static/app.html', timeout=15)
content = resp.read().decode('utf-8')

# Check braces in last 3000 chars (JS)
last = content[-3000:]
opens = [0, 0, 0]  # { [ (
for c in last:
    if c == '{': opens[0] += 1
    elif c == '}': opens[0] -= 1
    elif c == '[': opens[1] += 1
    elif c == ']': opens[1] -= 1
    elif c == '(': opens[2] += 1
    elif c == ')': opens[2] -= 1
print('Braces:', opens)

# Find key functions
for func in ['function requireLogin', 'function openAuthModal', 'function init()', 'init();']:
    pos = content.find(func)
    print(f"  '{func}': {'FOUND at ' + str(pos) if pos >= 0 else 'NOT FOUND'}")

# The problem: is there an error before init() is called?
# Check the code just before the script end
script_end = content.rfind('</script>')
code_before = content[script_end-100:script_end]
print(f"\nCode before </script>: ...{code_before}")
