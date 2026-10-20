# trim.py
import json, sys

src, dst = sys.argv[1], sys.argv[2]
cut_start = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
cut_end = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0

with open(src, encoding="utf-8") as f:
    header = f.readline()
    events = [json.loads(line) for line in f if line.strip()]

total = events[-1][0]
end = total - cut_end
print(f"Original length: {total:.1f}s, keeping {cut_start:.1f}s to {end:.1f}s")

with open(dst, "w", encoding="utf-8") as out:
    out.write(header)
    for t, kind, data in events:
        if t > end:
            break
        out.write(json.dumps([max(0, round(t - cut_start, 6)), kind, data]) + "\n")
