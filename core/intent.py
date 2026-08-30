"""意图路由：判断用户消息需要哪些注入块，闲聊时少注入减少堆砌。

NagaAgent 用 nano 模型做路由，这里用规则匹配（零额外 LLM 成本），
基于已有的 _needs_search / check_care 等模式扩展。

分类：
- 闲聊（chitchat）：问候、日常、无明确需求 → 只保留 persona + 短上下文
- 需工具（tool）：搜索/生图/查日程 → 保留对应工具
- 回忆（recall）：翻旧账/回忆 → 保留记忆检索块
- 情感（emotional）：倾诉/抱怨/分享/道歉 → 保留画像/风格/偏好
- 游戏（game）：互动玩法 → 保留游戏/日记相关

失败时返回 None（回退全量注入，安全优先）。
"""
from .log import logger

# 闲聊关键词：问候、日常无意义客套 → 触发少注入
_CHITCHAT_WORDS = {
    "你好", "你好呀", "早", "早安", "晚安", "晚上好", "中午好", "下午好",
    "在吗", "在干嘛", "在不在", "干嘛呢", "干啥呢", "干嘛", "没事",
    "没事了", "没", "没什么", "嗯", "哦", "哦哦", "好", "好的", "好吧",
    "行", "行吧", "知道了", "睡了", "拜", "拜拜", "88", "886",
    "哈哈", "哈哈哈", "呵呵", "嘿嘿", "嘻嘻", "笑死", "有趣",
    "打卡", "签到", "我来了", "回来了",
}

# 需搜索的触发词（复用 _needs_search 的语义）
_SEARCH_WORDS = {
    "搜索", "搜", "查", "查查", "百度", "谷歌", "搜索一下",
    "搜一下", "查一下", "百度一下", "谷歌一下",
    "天气", "温度", "新闻", "热搜", "发生了什么",
}

# 需生图/画画的触发词（不用裸「画」——会误配「画面/漫画/油画」等普通词）
_DRAW_WORDS = {
    "画一个", "画一张", "画个", "画幅", "生成图片", "生图",
    "给我画", "帮我画", "想要看", "想看", "让我看看",
}

# 回忆/翻旧账
_RECALL_WORDS = {
    "上次", "之前", "以前", "还记得", "记得吗", "那天", "昨天", "刚才",
    "我说过", "你答应", "我们说好", "你不是说", "老地方", "那个",
    "不记得", "忘了", "忘记了", "记不记得",
}

# 情感/倾诉/分享
_EMOTIONAL_WORDS = {
    "烦", "难受", "不开心", "难过", "伤心", "委屈", "累", "好累",
    "压力", "焦虑", "烦躁", "郁闷", "崩溃", "好烦", "头疼",
    "开心", "高兴", "好开心", "喜欢", "超喜欢", "爱", "爱你",
    "跟你说个事", "告诉你", "心里话", "想跟你说", "倾诉",
    "对不起", "抱歉", "我错了", "原谅我", "别生气",
}


def classify(text: str) -> dict:
    """对用户消息做意图分类，返回需要保留的注入块集合。

    Returns:
        {
            "chitchat": bool,     # 纯粹闲聊 → 只保留 persona + 短上下文
            "need_search": bool,  # 需要搜索
            "need_draw": bool,    # 需要生图
            "need_recall": bool,  # 需要长期记忆检索
            "need_emotional": bool, # 需要情感相关注入（画像/风格/偏好）
        }
    """
    lowered = text.lower().strip()
    result = {
        "chitchat": False,
        "need_search": False,
        "need_draw": False,
        "need_recall": False,
        "need_emotional": False,
    }

    # 纯闲聊短句 → 整句匹配
    if lowered in _CHITCHAT_WORDS:
        result["chitchat"] = True
        return result

    # 搜索
    if any(w in lowered for w in _SEARCH_WORDS):
        result["need_search"] = True
        return result

    # 生图
    if any(w in lowered for w in _DRAW_WORDS):
        result["need_draw"] = True
        return result

    # 长消息（>10字）且含情感词 → 情感
    if len(text) >= 4 and any(w in lowered for w in _EMOTIONAL_WORDS):
        result["need_emotional"] = True
        return result

    # 回忆
    if any(w in lowered for w in _RECALL_WORDS):
        result["need_recall"] = True
        return result

    # 短句（<8字）且无其他特征 → 可能闲聊
    if len(text) < 8:
        # 但也不是纯问候词（已匹配过）→ 可能是"好的""嗯"等，算闲聊
        result["chitchat"] = True
        return result

    # 默认：普通对话，保留所有注入（安全）
    return result