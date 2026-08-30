"""全项目语法编译检查：只检查 core/ plugins/ tests/ 和根目录 .py。"""
import pathlib
import py_compile

root = pathlib.Path(__file__).resolve().parent
skip = {".venv", "Napcat", "data"}
bad = []
count = 0
for p in root.rglob("*.py"):
    rel = p.relative_to(root)
    if any(part in skip for part in rel.parts):
        continue
    count += 1
    try:
        py_compile.compile(str(p), doraise=True)
    except Exception as e:
        bad.append(f"{rel}: {e}")
print(f"检查 {count} 个文件")
if bad:
    print("❌ 语法错误:")
    for b in bad:
        print(" ", b)
else:
    print("✅ 全部语法 OK")
