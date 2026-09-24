"""Built-in smart-contract templates for the template library.

Each template is a complete, sandbox-valid contract written against the
contract API (``state``, ``msg``, ``emit``, ``require``, ``transfer``,
``balance_of``).  They are exposed on the template-library page and can be
deployed with one click.
"""

TEMPLATES = [
    {
        "name": "token",
        "title": "可替代代币 (ERC-20 风格)",
        "category": "金融",
        "description": "发行一种可转账的代币，包含铸造、转账、余额查询与总量查询。",
        "constructor": [
            {"name": "name", "type": "string", "desc": "代币名称"},
            {"name": "symbol", "type": "string", "desc": "代币符号"},
            {"name": "supply", "type": "int", "desc": "初始发行量"},
        ],
        "functions": [
            {"name": "transfer", "desc": "向指定地址转账", "params": ["to", "amount"]},
            {"name": "balance_of", "desc": "查询某地址余额", "params": ["addr"]},
            {"name": "total_supply", "desc": "查询代币总量", "params": []},
        ],
        "source": '''# 可替代代币模板 (ERC-20 风格)
def init(name, symbol, supply):
    require(state.get("name") is None, "合约已初始化")
    state["name"] = name
    state["symbol"] = symbol
    state["total_supply"] = supply
    state["bal_" + msg.sender] = supply
    emit("Minted", to=msg.sender, amount=supply)

def transfer(to, amount):
    amount = int(amount)
    require(amount > 0, "转账金额必须为正")
    bal = state.get("bal_" + msg.sender, 0)
    require(bal >= amount, "余额不足")
    state["bal_" + msg.sender] = bal - amount
    state["bal_" + to] = state.get("bal_" + to, 0) + amount
    emit("Transfer", frm=msg.sender, to=to, amount=amount)

def balance_of(addr):
    return state.get("bal_" + addr, 0)

def total_supply():
    return state.get("total_supply", 0)
''',
    },
    {
        "name": "kv_store",
        "title": "键值存储",
        "category": "存储",
        "description": "一个简单的持久化键值对存储，支持写入与读取。",
        "constructor": [],
        "functions": [
            {"name": "set", "desc": "写入键值", "params": ["key", "value"]},
            {"name": "get", "desc": "读取键值", "params": ["key"]},
        ],
        "source": '''# 键值存储模板
def init():
    state["owner"] = msg.sender
    state["count"] = 0
    emit("Initialized", owner=msg.sender)

def set(key, value):
    key = str(key)
    require(key != "", "键不能为空")
    state[key] = value
    state["count"] = state.get("count", 0) + 1
    emit("Set", key=key, value=value, by=msg.sender)

def get(key):
    return state.get(str(key), None)
''',
    },
    {
        "name": "voting",
        "title": "投票合约",
        "category": "治理",
        "description": "创建候选人、投票、查看票数。每个地址限投一次。",
        "constructor": [
            {"name": "candidates", "type": "list", "desc": "候选人列表，如 ['Alice','Bob']"},
        ],
        "functions": [
            {"name": "vote", "desc": "给候选人投票", "params": ["candidate"]},
            {"name": "tally", "desc": "查询候选人票数", "params": ["candidate"]},
        ],
        "source": '''# 投票合约模板
def init(candidates):
    require(state.get("owner") is None, "已初始化")
    state["owner"] = msg.sender
    state["candidates"] = list(candidates)
    for c in candidates:
        state["vote_" + str(c)] = 0
    emit("Created", candidates=candidates)

def vote(candidate):
    require(str(candidate) in state.get("candidates", []), "候选人不存在")
    require(state.get("voted_" + msg.sender, False) is False, "已投过票")
    state["voted_" + msg.sender] = True
    state["vote_" + str(candidate)] = state.get("vote_" + str(candidate), 0) + 1
    emit("Voted", voter=msg.sender, candidate=str(candidate))

def tally(candidate):
    return state.get("vote_" + str(candidate), 0)
''',
    },
    {
        "name": "escrow",
        "title": "托管合约",
        "category": "金融",
        "description": "买家存入资金，买家确认后资金释放给卖家，买家可申请退款。",
        "constructor": [
            {"name": "seller", "type": "address", "desc": "卖家地址"},
        ],
        "functions": [
            {"name": "deposit", "desc": "买家存入资金", "params": []},
            {"name": "release", "desc": "买家确认放款给卖家", "params": []},
            {"name": "refund", "desc": "买家申请退款", "params": []},
            {"name": "amount", "desc": "查询托管金额", "params": []},
        ],
        "source": '''# 托管合约模板
def init(seller):
    require(state.get("seller") is None, "已初始化")
    state["seller"] = seller
    state["buyer"] = msg.sender
    state["amount"] = 0
    state["released"] = False
    emit("Created", seller=seller, buyer=msg.sender)

def deposit():
    require(msg.sender == state["buyer"], "只有买家可存入")
    require(state["released"] is False, "合约已结束")
    state["amount"] = state.get("amount", 0) + msg.value
    emit("Deposited", by=msg.sender, amount=msg.value)

def release():
    require(msg.sender == state["buyer"], "只有买家可确认放款")
    require(state["released"] is False, "已放款")
    state["released"] = True
    transfer(state["seller"], state["amount"])
    emit("Released", seller=state["seller"], amount=state["amount"])

def refund():
    require(msg.sender == state["buyer"], "只有买家可退款")
    require(state["released"] is False, "已放款")
    state["released"] = True
    transfer(state["buyer"], state["amount"])
    emit("Refunded", buyer=state["buyer"], amount=state["amount"])

def amount():
    return state.get("amount", 0)
''',
    },
    {
        "name": "auction",
        "title": "拍卖合约",
        "category": "金融",
        "description": "英式拍卖：出价必须高于当前最高价，拍卖结束后最高出价者胜出。",
        "constructor": [
            {"name": "item", "type": "string", "desc": "拍卖品名称"},
            {"name": "starting_price", "type": "int", "desc": "起拍价"},
            {"name": "end_height", "type": "int", "desc": "结束区块高度"},
        ],
        "functions": [
            {"name": "bid", "desc": "出价（需附带 value）", "params": []},
            {"name": "highest_bidder", "desc": "查询最高出价者", "params": []},
            {"name": "highest_bid", "desc": "查询最高出价", "params": []},
        ],
        "source": '''# 拍卖合约模板
def init(item, starting_price, end_height):
    require(state.get("item") is None, "已初始化")
    state["item"] = item
    state["highest_bid"] = int(starting_price)
    state["highest_bidder"] = msg.sender
    state["end_height"] = int(end_height)
    state["ended"] = False
    emit("AuctionCreated", item=item, start=int(starting_price))

def bid():
    require(block_height < state["end_height"], "拍卖已结束")
    require(msg.value > state["highest_bid"], "出价必须高于当前最高价")
    prev_bidder = state["highest_bidder"]
    prev_bid = state["highest_bid"]
    # 退回上一出价人
    transfer(prev_bidder, prev_bid)
    state["highest_bid"] = msg.value
    state["highest_bidder"] = msg.sender
    emit("Bid", bidder=msg.sender, amount=msg.value)

def highest_bidder():
    return state["highest_bidder"]

def highest_bid():
    return state["highest_bid"]
''',
    },
    {
        "name": "crowdfunding",
        "title": "众筹合约",
        "category": "金融",
        "description": "众筹目标金额，支持出资与查询进度，达到目标后项目方可提现。",
        "constructor": [
            {"name": "goal", "type": "int", "desc": "众筹目标金额"},
        ],
        "functions": [
            {"name": "contribute", "desc": "出资（需附带 value）", "params": []},
            {"name": "progress", "desc": "查询已筹金额", "params": []},
            {"name": "withdraw", "desc": "项目方提现（需达到目标）", "params": []},
        ],
        "source": '''# 众筹合约模板
def init(goal):
    require(state.get("owner") is None, "已初始化")
    state["owner"] = msg.sender
    state["goal"] = int(goal)
    state["raised"] = 0
    state["withdrawn"] = False
    emit("CampaignStarted", goal=int(goal))

def contribute():
    require(state["withdrawn"] is False, "众筹已结束")
    state["raised"] = state.get("raised", 0) + msg.value
    state["contrib_" + msg.sender] = state.get("contrib_" + msg.sender, 0) + msg.value
    emit("Contribution", from_=msg.sender, amount=msg.value)

def progress():
    return state.get("raised", 0)

def withdraw():
    require(msg.sender == state["owner"], "只有项目方可提现")
    require(state["raised"] >= state["goal"], "未达到众筹目标")
    require(state["withdrawn"] is False, "已提现")
    state["withdrawn"] = True
    transfer(state["owner"], state["raised"])
    emit("Withdrawn", amount=state["raised"])
''',
    },
    {
        "name": "staking_rewards",
        "title": "锁仓奖励（多笔独立质押）",
        "category": "金融",
        "description": (
            "同一账户可同时发起多笔质押，每笔独立指定数量与锁定区块数，"
            "独立按区块累积奖励、独立到期。到期可取回本金加奖励；提前取出"
            "仅返还本金，该笔奖励作废，且不影响其他质押。"
        ),
        "constructor": [
            {"name": "reward_per_block", "type": "float",
             "desc": "每区块奖励率（按本金比例，如 0.01 表示每区块为本金的 1%）"},
            {"name": "min_lock_blocks", "type": "int", "desc": "最短锁定区块数"},
            {"name": "max_lock_blocks", "type": "int", "desc": "最长锁定区块数"},
        ],
        "functions": [
            {"name": "stake", "desc": "发起一笔质押（需附带本金 value，参数为锁定区块数）",
             "params": ["lock_blocks"]},
            {"name": "unstake", "desc": "取回一笔质押：到期返还本金+奖励，提前仅返还本金",
             "params": ["stake_id"]},
            {"name": "fund_pool", "desc": "向奖励池注资（需附带 value），任何人可调用",
             "params": []},
            {"name": "reward_of", "desc": "查询某账户某笔质押当前已累积奖励",
             "params": ["addr", "stake_id"]},
            {"name": "remaining_blocks", "desc": "查询某笔质押距解锁还剩多少区块",
             "params": ["addr", "stake_id"]},
            {"name": "is_matured", "desc": "查询某笔质押是否已到期",
             "params": ["addr", "stake_id"]},
            {"name": "get_stake", "desc": "查询某笔质押的完整信息（本金/计息/解锁进度）",
             "params": ["addr", "stake_id"]},
            {"name": "stake_ids", "desc": "查询某账户持有的全部质押 ID",
             "params": ["addr"]},
            {"name": "pool_info", "desc": "查询奖励池余额、预留奖励、在押本金等全局信息",
             "params": []},
        ],
        "source": '''# 锁仓奖励合约（多笔独立质押 / 独立计息 / 独立到期）
#
# 每笔质押独立指定数量与锁定区块数，拥有独立的 stake_id，
# 按区块独立累积奖励、独立到期，账户内各笔互不影响。
#   到期取出：本金 + 全部奖励
#   提前取出：仅本金，该笔已累积奖励全部作废（退回奖励池）
# 奖励来自奖励池，任何人可通过 fund_pool 注资。
# 每区块奖励 = 本金 * reward_per_block，自质押所在区块起算，到期封顶。

def init(reward_per_block, min_lock_blocks, max_lock_blocks):
    require(state.get("rate") is None, "合约已初始化")
    rate = float(reward_per_block)
    lo = int(min_lock_blocks)
    hi = int(max_lock_blocks)
    require(rate > 0, "每区块奖励率必须为正")
    require(lo >= 1, "最短锁定期至少为 1 个区块")
    require(hi >= lo, "最长锁定期不能短于最短锁定期")
    state["rate"] = rate
    state["min_lock"] = lo
    state["max_lock"] = hi
    state["total_principal"] = 0.0   # 所有在押本金之和
    state["reserved"] = 0.0         # 为所有在押质押预留的到期奖励之和
    state["active"] = 0             # 当前有效质押笔数
    state["next_id"] = 0            # 全局质押 ID 计数器
    emit("PoolCreated", rate=rate, min_lock=lo, max_lock=hi, owner=msg.sender)

def fund_pool():
    require(msg.value > 0, "注资金额必须为正")
    emit("PoolFunded", by=msg.sender, amount=msg.value,
         available=_available() + msg.value)

def stake(lock_blocks):
    lock_blocks = int(lock_blocks)
    amount = msg.value
    require(amount > 0, "质押数量必须为正")
    require(lock_blocks >= state["min_lock"], "低于最短锁定期")
    require(lock_blocks <= state["max_lock"], "超过最长锁定期")
    rate = float(state["rate"])
    need = amount * rate * lock_blocks
    # 奖励池必须能覆盖这笔质押到期时的全部奖励，到期兑付才不会失败。
    require(_available() >= need, "奖励池余额不足，无法覆盖该笔质押的全部奖励")

    sid = int(state["next_id"]) + 1
    state["next_id"] = sid
    start = block_height
    unlock = start + lock_blocks
    state["s_" + str(sid)] = [msg.sender, amount, start, lock_blocks, unlock]
    ids = state.get("stakes_" + msg.sender, [])
    ids.append(sid)
    state["stakes_" + msg.sender] = ids
    state["total_principal"] = float(state["total_principal"]) + amount
    state["reserved"] = float(state["reserved"]) + need
    state["active"] = int(state["active"]) + 1
    emit("Staked", stake_id=sid, owner=msg.sender, amount=amount,
         start=start, lock_blocks=lock_blocks, unlock=unlock,
         reward_per_block=amount * rate)

def unstake(stake_id):
    sid_num = int(stake_id)
    key = "s_" + str(sid_num)
    s = state.get(key)
    require(s is not None, "质押不存在")
    require(s[0] == msg.sender, "只能取回自己的质押")

    amount = float(s[1])
    lock_blocks = int(s[3])
    unlock = int(s[4])
    rate = float(state["rate"])
    elapsed = _elapsed(int(s[2]), lock_blocks)
    matured = block_height >= unlock
    reward = amount * rate * elapsed
    payout = amount + reward if matured else amount

    # 释放该笔在创建时预留的全部奖励：到期时正好等于应付奖励；
    # 提前取出时预留奖励留回奖励池（该笔奖励作废，可供其他质押使用）。
    state["reserved"] = float(state["reserved"]) - amount * rate * lock_blocks
    state["total_principal"] = float(state["total_principal"]) - amount
    state["active"] = int(state["active"]) - 1
    ids = [i for i in state.get("stakes_" + msg.sender, []) if i != sid_num]
    state["stakes_" + msg.sender] = ids
    del state[key]

    transfer(msg.sender, payout)
    emit("Unstaked", stake_id=sid_num, owner=msg.sender, matured=matured,
         principal=amount, reward_paid=reward if matured else 0.0,
         reward_forfeited=0.0 if matured else reward)

def reward_of(addr, stake_id):
    return _earned(addr, stake_id)

def earned(addr, stake_id):
    return _earned(addr, stake_id)

def remaining_blocks(addr, stake_id):
    s = _must_get(addr, stake_id)
    left = int(s[4]) - block_height
    return left if left > 0 else 0

def is_matured(addr, stake_id):
    s = _must_get(addr, stake_id)
    return block_height >= int(s[4])

def get_stake(addr, stake_id):
    sid_num = int(stake_id)
    s = _must_get(addr, sid_num)
    amount = float(s[1])
    start = int(s[2])
    lock_blocks = int(s[3])
    unlock = int(s[4])
    elapsed = _elapsed(start, lock_blocks)
    left = unlock - block_height
    if left < 0:
        left = 0
    return {
        "stake_id": sid_num,
        "owner": s[0],
        "principal": amount,
        "start_block": start,
        "lock_blocks": lock_blocks,
        "unlock_block": unlock,
        "elapsed_blocks": elapsed,
        "remaining_blocks": left,
        "reward_per_block": amount * float(state["rate"]),
        "earned_reward": amount * float(state["rate"]) * elapsed,
        "matured": block_height >= unlock,
    }

def stake_ids(addr):
    return state.get("stakes_" + addr, [])

def pool_info():
    return {
        "rate": float(state["rate"]),
        "min_lock": int(state["min_lock"]),
        "max_lock": int(state["max_lock"]),
        "balance": this_balance(),
        "total_principal": float(state["total_principal"]),
        "reserved_reward": float(state["reserved"]),
        "available_reward": _available(),
        "active_stakes": int(state["active"]),
    }

# --------------------------------------------------------------------------- #
# 内部辅助函数
# --------------------------------------------------------------------------- #
def _must_get(addr, stake_id):
    s = state.get("s_" + str(int(stake_id)))
    require(s is not None, "质押不存在")
    require(s[0] == addr, "该质押不属于此账户")
    return s

def _elapsed(start, lock_blocks):
    elapsed = block_height - int(start)
    if elapsed > lock_blocks:
        elapsed = lock_blocks
    if elapsed < 0:
        elapsed = 0
    return elapsed

def _earned(addr, stake_id):
    s = _must_get(addr, stake_id)
    amount = float(s[1])
    return amount * float(state["rate"]) * _elapsed(int(s[2]), int(s[3]))

def _available():
    # 合约余额扣除全部在押本金与已预留奖励后，才可用于新质押的奖励。
    free = (this_balance() - float(state["total_principal"])
            - float(state["reserved"]))
    return free if free > 0 else 0.0
''',
    },
    {
        "name": "counter",
        "title": "计数器",
        "category": "基础",
        "description": "最简单的合约，演示状态持久化与事件。",
        "constructor": [],
        "functions": [
            {"name": "increment", "desc": "计数 +1", "params": []},
            {"name": "get", "desc": "查询当前计数", "params": []},
        ],
        "source": '''# 计数器模板
def init():
    state["count"] = 0
    emit("Created", by=msg.sender)

def increment():
    state["count"] = state.get("count", 0) + 1
    emit("Incremented", value=state["count"])

def get():
    return state.get("count", 0)
''',
    },
]


def get_templates():
    return TEMPLATES


def get_template(name):
    for t in TEMPLATES:
        if t["name"] == name:
            return t
    return None


def template_catalog():
    """Return templates without their source (for the list view)."""
    return [
        {
            "name": t["name"],
            "title": t["title"],
            "category": t["category"],
            "description": t["description"],
            "constructor": t["constructor"],
            "functions": t["functions"],
        }
        for t in TEMPLATES
    ]
