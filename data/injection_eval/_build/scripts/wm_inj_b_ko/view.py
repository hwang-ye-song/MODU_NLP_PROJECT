import re, sys
t = open(f'src/web-inj-{sys.argv[1]}.html', encoding='utf-8').read()
t = re.sub(r'\s(style|class|id)="[^"]*"', '', t)
t = re.sub(r'\n\s*\n', '\n', t)
print(t)
