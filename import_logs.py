"""从 QQ 聊天记录提取"网友对话风格"，供菟菚参考（轻量风格适应，非微调）。

用法：
  ./.venv/Scripts/python.exe import_logs.py <聊天记录文件路径>
  # 支持 txt（每行消息，自动识别 时间戳/昵称:内容 等常见格式）或 json（[{sender,content}]）
  # 生成 D:/DSH/TZtuzhan/data/style_ref.txt，菟菚的 prompt 会自动带上它

注意：这只是用真实聊天记录的短句节奏做风格参考，不是对模型微调。
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

COMMON_PARTICLES = ["嗯", "啊", "哈", "好", "行", "哦", "呢", "吧", "嘛", "？", "！", "啦", "耶", "呀"]


def _strip_prefix(line: str) -> str:
    """去掉常见的时间戳/昵称前缀，尽量留下消息内容。"""
    line = re.sub(
        r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?", "", line
    ).strip()
    m = re.match(r"^[\[【]?([^\[\]:：()（）]{1,30})[\]】]?[:：]\s*(.+)$", line)
    if m and m.group(2):
        return m.group(2).strip()
    m = re.match(r"^[\[【]([^\]】]+)[\]】](.+)$", line)
    if m and m.group(2):
        return m.group(2).strip()
    return line


def parse_text(raw: str) -> list[str]:
    msgs = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        content = _strip_prefix(line)
        if content and not content.startswith(("系统消息", "管理员", "[图片]", "[表情]")):
            msgs.append(content)
    return msgs


def parse_json(raw: str) -> list[str]:
    try:
        data = json.loads(raw)
    except Exception:
        return []
    msgs = []
    if isinstance(data, list):
        for m in data:
            if isinstance(m, dict):
                c = m.get("content") or m.get("message") or m.get("msg")
                if isinstance(c, str):
                    msgs.append(c.strip())
    return [m for m in msgs if m]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", help="QQ 聊天记录文件路径（txt/json）")
    parser.add_argument("--out", default="data/style_ref.txt")
    args = parser.parse_args()

    raw = Path(args.file).read_text(encoding="utf-8-sig", errors="ignore")
    msgs = parse_json(raw) if args.file.lower().endswith(".json") else parse_text(raw)
    if not msgs:
        print("没有解析到消息，请确认文件格式（每行一条消息，或 json 数组）。")
        return

    short = [m for m in msgs if 0 < len(m) <= 20]
    total = len(msgs)
    avg = sum(len(m) for m in msgs) / total
    pct_short = len(short) / total * 100
    particles = Counter()
    for m in short:
        for p in COMMON_PARTICLES:
            if p in m:
                particles[p] += 1
    top_p = "、".join(p for p, _ in particles.most_common(8)) or "（无明显特征）"

    # 挑有代表性的短句示例（去重、优先带语气/问句）
    seen, samples = set(), []
    for m in sorted(short, key=lambda x: (len(x), x)):
        if m not in seen:
            seen.add(m)
            samples.append(m)
        if len(samples) >= 12:
            break

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = (
        "# 网友对话风格参考（来自真实聊天记录，模仿它的短句节奏）\n"
        f"统计：共 {total} 条消息，平均每条 {avg:.1f} 字，其中 {pct_short:.0f}% 是 20 字以内的短消息"
        "——大家习惯把话拆成短句一条条发，很少长篇大论。\n"
        f"常用语气词/尾缀：{top_p}\n"
        "短句示例（模仿这种随意、慵懒、短促的节奏，内容换成你自己的）：\n"
        + "\n".join(f"- {s}" for s in samples)
        + "\n"
    )
    out.write_text(text, encoding="utf-8")
    print(f"解析到 {total} 条消息，短句 {len(short)} 条，已写入 {out}")


if __name__ == "__main__":
    main()
