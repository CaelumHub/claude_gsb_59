"""Lock-staking rewards: multiple independent stakes per account.

A *stake* locks ``amount`` coins for ``lock_blocks`` blocks.  While locked,
the stake accrues rewards every block at a fixed rate of the principal
(``STAKING_REWARD_RATE_PER_BLOCK``); accrual stops at the unlock height.

Every stake is fully independent: it has its own id, principal, lock period
and unlock height, and its own reward counter.  An account may hold any
number of stakes simultaneously, each maturing on its own schedule.

* **Mature withdrawal** (current height >= unlock height): the principal is
  returned from the staking pool and the accrued reward is minted to the
  owner.
* **Early withdrawal**: only the principal is returned; every reward that
  stake had accrued is forfeited.  Other stakes of the same account are not
  affected.

Stakes live in :class:`~state.WorldState` (``state.stakes``) so they are
part of the committed state root, persist with the per-block snapshots, and
follow rollbacks/reorgs automatically.  All functions that mutate state are
deterministic in ``(state, tx, height)`` — they are executed identically on
every node during block application.
"""

from .config import (STAKING_MAX_LOCK_BLOCKS, STAKING_MIN_LOCK_BLOCKS,
                     STAKING_REWARD_RATE_PER_BLOCK)

# Reserved module account that custodies locked principal.
STAKING_POOL_ADDRESS = "0x" + "0" * 39 + "1"

STATUS_ACTIVE = "active"
STATUS_WITHDRAWN = "withdrawn"


class StakingError(Exception):
    """Raised when a staking operation is invalid (the transaction reverts)."""


def reward_rate(cfg=None):
    """The per-block reward rate (fraction of principal per block)."""
    if cfg is not None:
        return float(cfg.get("STAKING_REWARD_RATE_PER_BLOCK",
                             STAKING_REWARD_RATE_PER_BLOCK))
    return float(STAKING_REWARD_RATE_PER_BLOCK)


# --------------------------------------------------------------------- #
# Stake record helpers (pure views — no mutation)
# --------------------------------------------------------------------- #
def accrued_reward(stake, height, rate):
    """Reward accrued by ``stake`` as of ``height``.

    Accrual is linear in elapsed blocks and stops at the unlock height.
    For withdrawn stakes this reports what was actually paid out (0 for
    early withdrawals, whose rewards were forfeited).
    """
    if stake["status"] == STATUS_WITHDRAWN:
        return float(stake.get("reward_paid", 0.0))
    elapsed = max(0, min(int(height), int(stake["unlock_height"]))
                  - int(stake["start_height"]))
    return float(stake["amount"]) * float(rate) * elapsed


def projected_reward(stake, rate):
    """Total reward the stake will have accrued at its unlock height."""
    return float(stake["amount"]) * float(rate) * int(stake["lock_blocks"])


def blocks_remaining(stake, height):
    """Blocks until the stake unlocks (0 once matured or withdrawn)."""
    if stake["status"] != STATUS_ACTIVE:
        return 0
    return max(0, int(stake["unlock_height"]) - int(height))


def matured(stake, height):
    return stake["status"] == STATUS_ACTIVE \
        and int(height) >= int(stake["unlock_height"])


def stake_view(stake, height, rate):
    """A stake rendered for queries, with live reward/lock figures."""
    return {
        "id": stake["id"],
        "owner": stake["owner"],
        "amount": stake["amount"],
        "start_height": stake["start_height"],
        "lock_blocks": stake["lock_blocks"],
        "unlock_height": stake["unlock_height"],
        "status": stake["status"],
        "accrued_reward": accrued_reward(stake, height, rate),
        "projected_reward": projected_reward(stake, rate),
        "blocks_remaining": blocks_remaining(stake, height),
        "matured": matured(stake, height),
        "withdrawn_height": stake.get("withdrawn_height"),
        "reward_paid": stake.get("reward_paid", 0.0),
        "early": bool(stake.get("early", False)),
    }


# --------------------------------------------------------------------- #
# State transitions (called during block execution — must be deterministic)
# --------------------------------------------------------------------- #
def validate_stake_params(amount, lock_blocks):
    """Return ``(ok, reason)`` for stake parameters."""
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return False, "invalid stake amount"
    if amount <= 0:
        return False, "stake amount must be positive"
    try:
        lock_blocks = int(lock_blocks)
    except (TypeError, ValueError):
        return False, "invalid lock_blocks"
    if lock_blocks < STAKING_MIN_LOCK_BLOCKS:
        return False, f"lock_blocks must be >= {STAKING_MIN_LOCK_BLOCKS}"
    if lock_blocks > STAKING_MAX_LOCK_BLOCKS:
        return False, f"lock_blocks must be <= {STAKING_MAX_LOCK_BLOCKS}"
    return True, "ok"


def create_stake(state, owner, amount, lock_blocks, height, stake_id):
    """Lock ``amount`` from ``owner`` into a new stake; return the record."""
    ok, reason = validate_stake_params(amount, lock_blocks)
    if not ok:
        raise StakingError(reason)
    amount = float(amount)
    lock_blocks = int(lock_blocks)
    if state.balance(owner) < amount:
        raise StakingError("insufficient balance to stake")
    if stake_id in state.stakes:
        raise StakingError("duplicate stake id")
    # Custody the principal in the staking pool account.
    state.add_balance(owner, -amount)
    state.add_balance(STAKING_POOL_ADDRESS, amount)
    stake = {
        "id": stake_id,
        "owner": owner,
        "amount": amount,
        "start_height": int(height),
        "lock_blocks": lock_blocks,
        "unlock_height": int(height) + lock_blocks,
        "status": STATUS_ACTIVE,
        "withdrawn_height": None,
        "reward_paid": 0.0,
        "early": False,
    }
    state.stakes[stake_id] = stake
    return stake


def withdraw(state, owner, stake_id, height, rate):
    """Withdraw stake ``stake_id`` for ``owner`` at ``height``.

    Mature stakes pay back principal plus the accrued reward (the reward is
    minted, like the coinbase reward).  Early withdrawals pay back only the
    principal; the stake's accrued reward is forfeited.  Either way only
    this one stake is touched.
    """
    stake = state.stakes.get(stake_id)
    if stake is None:
        raise StakingError("stake not found")
    if stake["owner"] != owner:
        raise StakingError("only the stake owner can withdraw")
    if stake["status"] != STATUS_ACTIVE:
        raise StakingError("stake already withdrawn")

    amount = float(stake["amount"])
    early = int(height) < int(stake["unlock_height"])
    reward = 0.0 if early else accrued_reward(stake, height, rate)

    if state.balance(STAKING_POOL_ADDRESS) < amount:
        raise StakingError("staking pool underfunded")
    state.add_balance(STAKING_POOL_ADDRESS, -amount)
    state.add_balance(owner, amount)
    if reward > 0:
        state.add_balance(owner, reward)

    stake["status"] = STATUS_WITHDRAWN
    stake["withdrawn_height"] = int(height)
    stake["reward_paid"] = reward
    stake["early"] = early
    return {
        "stake_id": stake_id,
        "owner": owner,
        "principal": amount,
        "reward": reward,
        "early": early,
        "height": int(height),
    }


# --------------------------------------------------------------------- #
# Queries
# --------------------------------------------------------------------- #
def stakes_of(state, owner, height, rate):
    """All stakes of ``owner`` (newest first) with live reward figures."""
    stakes = [stake_view(s, height, rate) for s in state.stakes.values()
              if s["owner"] == owner]
    stakes.sort(key=lambda s: (s["start_height"], s["id"]), reverse=True)
    return stakes


def summary(state, height, rate):
    """Global staking statistics for dashboards."""
    active = [s for s in state.stakes.values() if s["status"] == STATUS_ACTIVE]
    return {
        "height": int(height),
        "reward_rate_per_block": float(rate),
        "min_lock_blocks": STAKING_MIN_LOCK_BLOCKS,
        "max_lock_blocks": STAKING_MAX_LOCK_BLOCKS,
        "total_stakes": len(state.stakes),
        "active_stakes": len(active),
        "total_locked": sum(s["amount"] for s in active),
        "total_accrued": sum(accrued_reward(s, height, rate) for s in active),
        "pool_balance": state.balance(STAKING_POOL_ADDRESS),
    }
