"""End-to-end tests for the lock-staking module (backend/staking.py).

Exercises the full lifecycle at the blockchain level: staking locks funds,
rewards accrue per block independently per stake, mature withdrawal pays
principal + reward, early withdrawal pays principal only (rewards forfeited)
without touching other stakes, and stake state survives persistence.
"""

import os
import shutil
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import crypto, pow as pow_mod, staking
from backend.block import Block
from backend.blockchain import Blockchain
from backend.config import COINBASE_REWARD, build_config
from backend.storage import DataPaths
from backend.transaction import (create_coinbase, create_stake,
                                 create_unstake)

RATE = 0.01  # STAKING_REWARD_RATE_PER_BLOCK default


def _cfg(data_dir):
    args = types.SimpleNamespace(id="test", port=0, host="127.0.0.1",
                                 peers=None, data_dir=data_dir, mine=False,
                                 seed=False)
    cfg = build_config(args)
    cfg["INITIAL_DIFFICULTY_BITS"] = 4  # keep test mining cheap
    return cfg


class StakingTestBase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="lc-staking-")
        self.paths = DataPaths(self.dir, {})
        self.paths.ensure()
        self.bc = Blockchain(_cfg(self.dir), self.paths)
        self.bc.create_genesis()
        # Two key pairs: a funded staker and a stranger.
        self.priv = crypto.generate_private_key()
        self.me = crypto.address_from_private_key(self.priv)
        self.other_priv = crypto.generate_private_key()
        self.other = crypto.address_from_private_key(self.other_priv)
        # Mining rewards go to a separate miner so they don't skew balances.
        self.miner = crypto.address_from_private_key(
            crypto.generate_private_key())
        self.mine([], miner=self.me)  # block 1: fund `self.me` with 50

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def mine(self, txs, miner=None):
        """Mine a block containing ``txs``."""
        index = self.bc.height + 1
        coinbase = create_coinbase(miner or self.miner, COINBASE_REWARD, index)
        block = Block(index, self.bc.head.hash, [coinbase] + list(txs))
        block.difficulty = pow_mod.next_difficulty(self.bc, block)
        block._recompute_header()
        state = self.bc.state.copy()
        state, _ = self.bc.apply_block(block, state)
        block.set_state_root(state.root())
        pow_mod.mine(block, block.difficulty)
        status, msg = self.bc.add_block(block)
        self.assertEqual(status, "extended", msg)
        return block

    def stake_tx(self, amount, lock_blocks, sender_priv=None, sender=None):
        priv = sender_priv or self.priv
        addr = sender or self.me
        nonce = self.bc.state.nonce(addr)
        return create_stake(addr, amount, lock_blocks, 0, nonce, priv=priv)

    def unstake_tx(self, stake_id, sender_priv=None, sender=None):
        priv = sender_priv or self.priv
        addr = sender or self.me
        nonce = self.bc.state.nonce(addr)
        return create_unstake(addr, stake_id, 0, nonce, priv=priv)

    def balance(self, addr=None):
        return self.bc.state.balance(addr or self.me)

    def view(self, stake_id):
        return staking.stake_view(self.bc.state.stakes[stake_id],
                                  self.bc.height, RATE)


class TestStakeLifecycle(StakingTestBase):
    def test_stake_locks_funds_and_accrues_per_block(self):
        tx = self.stake_tx(10, 3)
        self.mine([tx])  # block 2: stake starts at height 2
        self.assertEqual(self.balance(), 50 - 10)
        self.assertEqual(self.bc.state.balance(staking.STAKING_POOL_ADDRESS), 10)

        stake = self.bc.state.stakes[tx.txid]
        self.assertEqual(stake["owner"], self.me)
        self.assertEqual(stake["amount"], 10)
        self.assertEqual(stake["start_height"], 2)
        self.assertEqual(stake["unlock_height"], 5)
        self.assertEqual(stake["status"], "active")

        # Rewards accrue per block, capped at the unlock height.
        self.assertEqual(self.view(tx.txid)["accrued_reward"], 0)
        self.mine([])  # height 3
        v = self.view(tx.txid)
        self.assertAlmostEqual(v["accrued_reward"], 10 * RATE * 1)
        self.assertEqual(v["blocks_remaining"], 2)
        self.assertFalse(v["matured"])
        self.mine([])  # height 4
        self.assertAlmostEqual(self.view(tx.txid)["accrued_reward"],
                               10 * RATE * 2)
        self.mine([])  # height 5: matured
        v = self.view(tx.txid)
        self.assertTrue(v["matured"])
        self.assertEqual(v["blocks_remaining"], 0)
        self.assertAlmostEqual(v["accrued_reward"], 10 * RATE * 3)
        self.mine([])  # height 6: accrual stays capped at unlock height
        self.assertAlmostEqual(self.view(tx.txid)["accrued_reward"],
                               10 * RATE * 3)

    def test_mature_withdrawal_pays_principal_plus_reward(self):
        tx = self.stake_tx(10, 3)
        self.mine([tx])            # stake at height 2, unlocks at 5
        self.mine([])              # 3
        self.mine([])              # 4
        self.mine([])              # 5 (mature)
        before = self.balance()
        wd = self.unstake_tx(tx.txid)
        self.mine([wd])            # height 6
        reward = 10 * RATE * 3
        self.assertAlmostEqual(self.balance(), before + 10 + reward)
        self.assertEqual(self.bc.state.balance(staking.STAKING_POOL_ADDRESS), 0)
        stake = self.bc.state.stakes[tx.txid]
        self.assertEqual(stake["status"], "withdrawn")
        self.assertFalse(stake["early"])
        self.assertAlmostEqual(stake["reward_paid"], reward)

    def test_early_withdrawal_forfeits_reward(self):
        tx = self.stake_tx(10, 10)
        self.mine([tx])            # stake at height 2, unlocks at 12
        self.mine([])              # 3 — some reward has accrued
        self.assertGreater(self.view(tx.txid)["accrued_reward"], 0)
        before = self.balance()
        wd = self.unstake_tx(tx.txid)
        self.mine([wd])            # height 4: early withdrawal
        self.assertAlmostEqual(self.balance(), before + 10)  # principal only
        stake = self.bc.state.stakes[tx.txid]
        self.assertEqual(stake["status"], "withdrawn")
        self.assertTrue(stake["early"])
        self.assertEqual(stake["reward_paid"], 0.0)


class TestMultipleIndependentStakes(StakingTestBase):
    def test_stakes_are_independent(self):
        # Two concurrent stakes with different amounts and lock periods.
        tx1 = self.stake_tx(10, 2)
        self.mine([tx1])           # stake1 at height 2, unlocks at 4
        tx2 = self.stake_tx(20, 6)
        self.mine([tx2])           # stake2 at height 3, unlocks at 9
        self.assertEqual(self.balance(), 50 - 30)
        self.assertEqual(len(self.bc.state.stakes), 2)

        self.mine([])              # height 4: stake1 matured, stake2 active
        v1, v2 = self.view(tx1.txid), self.view(tx2.txid)
        self.assertTrue(v1["matured"])
        self.assertFalse(v2["matured"])
        self.assertAlmostEqual(v1["accrued_reward"], 10 * RATE * 2)
        self.assertAlmostEqual(v2["accrued_reward"], 20 * RATE * 1)

        # Early-withdraw stake2: principal back, its reward forfeited...
        before = self.balance()
        self.mine([self.unstake_tx(tx2.txid)])   # height 5
        self.assertAlmostEqual(self.balance(), before + 20)
        # ...while stake1's accrued reward is untouched.
        self.assertAlmostEqual(self.view(tx1.txid)["accrued_reward"],
                               10 * RATE * 2)
        self.assertEqual(self.view(tx1.txid)["status"], "active")

        # Mature-withdraw stake1 afterwards: full principal + reward.
        before = self.balance()
        self.mine([self.unstake_tx(tx1.txid)])   # height 6
        self.assertAlmostEqual(self.balance(), before + 10 + 10 * RATE * 2)

        views = staking.stakes_of(self.bc.state, self.me, self.bc.height, RATE)
        self.assertEqual(len(views), 2)
        self.assertTrue(all(v["status"] == "withdrawn" for v in views))

    def test_cannot_withdraw_twice_or_as_stranger(self):
        tx = self.stake_tx(10, 1)
        self.mine([tx])            # height 2, unlocks at 3
        self.mine([])              # height 3 (mature)
        self.mine([self.unstake_tx(tx.txid)])  # height 4: withdrawn

        # Second withdrawal of the same stake reverts.
        state, receipt = self.bc._execute_transaction(
            self.unstake_tx(tx.txid), self.bc.state.copy(), self.me, 5)
        self.assertFalse(receipt["ok"])
        self.assertIn("already withdrawn", receipt["error"])

        # A stranger cannot withdraw my stake (revert at execution; the
        # mempool also rejects it up front).
        state, receipt = self.bc._execute_transaction(
            self.unstake_tx(tx.txid, sender_priv=self.other_priv,
                            sender=self.other),
            self.bc.state.copy(), self.me, 5)
        self.assertFalse(receipt["ok"])

    def test_invalid_stake_params_revert(self):
        for bad in (0, -5):
            state, receipt = self.bc._execute_transaction(
                self.stake_tx(bad, 3), self.bc.state.copy(), self.me, 2)
            self.assertFalse(receipt["ok"])
        state, receipt = self.bc._execute_transaction(
            self.stake_tx(10, 0), self.bc.state.copy(), self.me, 2)
        self.assertFalse(receipt["ok"])
        # Overdraft: cannot stake more than the balance.
        state, receipt = self.bc._execute_transaction(
            self.stake_tx(1000, 3), self.bc.state.copy(), self.me, 2)
        self.assertFalse(receipt["ok"])
        self.assertEqual(len(self.bc.state.stakes), 0)


class TestStakingPersistence(StakingTestBase):
    def test_stakes_survive_reload_and_state_root(self):
        tx = self.stake_tx(10, 5)
        self.mine([tx])
        self.mine([])
        root_before = self.bc.state.root()

        # Reload the chain from disk: stakes and the committed root persist.
        bc2 = Blockchain(_cfg(self.dir), DataPaths(self.dir, {}))
        bc2.load()
        self.assertEqual(bc2.state.root(), root_before)
        self.assertIn(tx.txid, bc2.state.stakes)
        self.assertEqual(bc2.validate_full_chain()["valid"], True)

    def test_summary(self):
        tx = self.stake_tx(10, 4)
        self.mine([tx])
        self.mine([])
        s = staking.summary(self.bc.state, self.bc.height, RATE)
        self.assertEqual(s["active_stakes"], 1)
        self.assertEqual(s["total_locked"], 10)
        self.assertAlmostEqual(s["total_accrued"], 10 * RATE * 1)
        self.assertEqual(s["pool_balance"], 10)


if __name__ == "__main__":
    unittest.main()
