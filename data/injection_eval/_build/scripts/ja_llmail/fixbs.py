import sys

p = sys.argv[1]
b = open(p, "rb").read()
print("before", b.count(b"\x08"))
b = b.replace(b"\x08", b"\\b")
with open(p, "wb") as fh:
    fh.write(b)
print("after", open(p, "rb").read().count(b"\x08"))
