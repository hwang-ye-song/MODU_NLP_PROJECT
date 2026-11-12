import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ad_lib
R = sys.argv[1]
for s in ['workspace', 'travel', 'banking', 'slack']:
    S = ad_lib.Suite(R, s); env = S.load_env()
    for k, tool, kind, t in ad_lib.items(s, env):
        esc = 'ESC' if (chr(92) + 'x' in t or chr(92) + 'u' in t) else ''
        print(s, k[0], str(k[1])[:28].replace(' ', '_'), len(t), esc)
