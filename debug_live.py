"""Check deployed app.html for key functions"""
import urllib.request
try:
    resp = urllib.request.urlopen('https://wanxue-api.onrender.com/static/app.html', timeout=15)
    content = resp.read().decode('utf-8')
    
    for func in ['function requireLogin', 'function openAuthModal', 'function init()', 'init();', 'loadAuthState();']:
        pos = content.find(func)
        status = 'FOUND at ' + str(pos) if pos >= 0 else 'NOT FOUND'
        print(f'{status}: {func}')
    
    # Check braces near the end
    end_section = content[-5000:]
    brace_count = end_section.count('{') - end_section.count('}')
    paren_count = end_section.count('(') - end_section.count(')')
    print(f'\nLast 5k chars: braces diff={brace_count}, parens diff={paren_count}')
    
    # Check if the authOverlay has .show class
    if 'authOverlay.classList.add' in content:
        print('authOverlay.classList.add: FOUND')
    else:
        print('authOverlay.classList.add: NOT FOUND')
except Exception as e:
    print(f'Error: {e}')
