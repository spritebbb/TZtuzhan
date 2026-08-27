"""四阶段测试：初识/熟悉/亲密/恋人（用完即删）。"""
import asyncio

from core import affection
from core.pipeline import process
from core.userdb import db

STAGES = [(0, "初识"), (30, "熟悉"), (60, "亲密"), (90, "恋人")]
PROBES = ["在干嘛呢", "我好喜欢你", "我们是恋人了吗", "抱一下好不好"]


async def main() -> None:
    for aff, name in STAGES:
        uid = f"stage-{aff}"
        db.ensure_user(uid)
        affection.set_affection(uid, aff)
        print(f"\n========== 阶段「{name}」(aff 初始={aff}) ==========")
        for t in PROBES:
            r = await process(uid, t, mock=False)
            u = db.get_user(uid)
            print(f"  你> {t}")
            print(f"  菟菚> {r}")
            print(f"      [aff={u['affection']} 阶段「{affection.stage_of(u['affection'])}」]")


if __name__ == "__main__":
    asyncio.run(main())
