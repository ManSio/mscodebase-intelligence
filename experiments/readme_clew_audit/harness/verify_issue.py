import subprocess, json
out = subprocess.run(
    ['gh', 'issue', 'view', '1', '--repo', 'earlgreyhot1701D/readme-clew-2', '--json', 'body'],
    capture_output=True, text=True, encoding='utf-8').stdout
body = json.loads(out)['body']
print('chars    :', len(body))
print('U+FFFD   :', body.count('\ufffd'))
print('em-dash  :', body.count('\u2014'))
print('backticks:', body.count('`'))
for s in ['canvas-parser', 'lodash-es', '474/474', 'mentionsWord', 'core.autocrlf', 'socket.io', 'yocto-queue']:
    print(f'  {s:16} {"OK" if s in body else "MISSING"}')