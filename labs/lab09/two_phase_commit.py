"""A distributed transaction coordinator with two-phase commit (2PC) and presumed abort.

A bank keeps accounts on two shards. A transfer debits one shard and credits the other, so
it must commit on both or on neither. Each shard (participant) and the coordinator keep a
durable log, as in Lab 8. Crashes lose everything except that log and the committed data.

Phase 1 (prepare): the coordinator asks every participant to PREPARE. A participant checks
its constraints, locks the rows, forces a PREPARED record (with the writes) to its log, and
votes YES; or it votes NO and forgets the transaction.
Phase 2 (decision): if every vote is YES, the coordinator forces COMMIT to its own log -- that
is the commit point -- and tells everyone. Otherwise it aborts. After all participants
acknowledge, it writes END. With presumed abort, "no decision in the log" means ABORT.

The famous weakness: a participant that voted YES may not decide on its own. If the
coordinator fails before telling it the decision, it stays in doubt, holding its locks.

    python labs/lab09/two_phase_commit.py --scenario all
"""

from __future__ import annotations

import argparse


class SimulatedCrash(Exception):
    pass


class Participant:
    """One shard: committed balances, a durable log, and volatile locks / staged writes."""

    def __init__(self, name: str, balances: dict[str, int]) -> None:
        self.name = name
        self.data = dict(balances)  # committed state (durable)
        self.log: list[tuple] = []  # durable: ("PREPARED", tx, writes) / ("COMMIT", tx) / ("ABORT", tx)
        self.locks: dict[str, str] = {}  # row -> tx (volatile, rebuilt from the log after a crash)
        self.staged: dict[str, dict[str, int]] = {}  # tx -> writes
        self.up = True
        self.vote_no_next = False  # failure injection: refuse the next prepare

    def _require_up(self) -> None:
        if not self.up:
            raise ConnectionError(f"{self.name} is down")

    def prepare(self, tx: str, deltas: dict[str, int]) -> str:
        self._require_up()
        writes = {}
        for account, delta in deltas.items():
            holder = self.locks.get(account)
            new_balance = self.data.get(account, 0) + delta
            if (holder not in (None, tx)) or new_balance < 0 or self.vote_no_next:
                self.vote_no_next = False
                return "NO"  # unilateral abort is allowed before voting YES
            writes[account] = new_balance
        for account in writes:
            self.locks[account] = tx
        self.staged[tx] = writes
        self.log.append(("PREPARED", tx, dict(writes)))  # forced before the YES vote leaves
        return "YES"

    def commit(self, tx: str) -> None:
        self._require_up()
        if ("COMMIT", tx) in self.log:
            return  # idempotent: the decision may be resent after a coordinator restart
        self.data.update(self.staged.pop(tx, {}))
        self.log.append(("COMMIT", tx))
        self._unlock(tx)

    def abort(self, tx: str) -> None:
        self._require_up()
        if ("ABORT", tx) in self.log:
            return
        self.staged.pop(tx, None)
        self.log.append(("ABORT", tx))
        self._unlock(tx)

    def _unlock(self, tx: str) -> None:
        self.locks = {row: holder for row, holder in self.locks.items() if holder != tx}

    def in_doubt(self) -> list[str]:
        """Transactions this shard prepared but for which it has no decision."""
        prepared = [r[1] for r in self.log if r[0] == "PREPARED"]
        decided = {r[1] for r in self.log if r[0] in ("COMMIT", "ABORT")}
        return [tx for tx in prepared if tx not in decided]

    def crash(self) -> None:
        self.up = False
        self.locks.clear()
        self.staged.clear()

    def restart(self) -> list[str]:
        """Rebuild locks and staged writes of in-doubt transactions from the durable log."""
        self.up = True
        for record in self.log:
            if record[0] == "PREPARED" and record[1] in self.in_doubt():
                self.staged[record[1]] = dict(record[2])
                for row in record[2]:
                    self.locks[row] = record[1]
        return self.in_doubt()

    def ask_coordinator(self, coordinator: "Coordinator") -> dict[str, str]:
        """Termination protocol: ask for the outcome of every in-doubt transaction."""
        outcomes = {}
        for tx in self.in_doubt():
            decision = coordinator.decision(tx)  # raises ConnectionError if the coordinator is down
            (self.commit if decision == "COMMIT" else self.abort)(tx)
            outcomes[tx] = decision
        return outcomes


class Coordinator:
    def __init__(self, participants: dict[str, Participant]) -> None:
        self.participants = participants
        self.log: list[tuple] = []  # durable: ("COMMIT", tx, names) / ("ABORT", tx) / ("END", tx)
        self.up = True
        self.crash_at: str | None = None  # "after-prepare", "after-decision", "after-first-commit"
        self.messages = 0

    def _maybe_crash(self, point: str) -> None:
        if self.crash_at == point:
            self.crash_at = None
            self.up = False
            raise SimulatedCrash(point)

    def decision(self, tx: str) -> str:
        if not self.up:
            raise ConnectionError("coordinator is down")
        for record in self.log:
            if record[0] in ("COMMIT", "ABORT") and record[1] == tx:
                return record[0]
        return "ABORT"  # presumed abort: no decision record means the transaction aborted

    def run(self, tx: str, plan: dict[str, dict[str, int]]) -> str:
        """Execute a distributed transaction. plan = {participant: {account: delta}}."""
        if not self.up:
            raise ConnectionError("coordinator is down")
        votes = {}
        for name, deltas in plan.items():
            self.messages += 2  # PREPARE + vote
            try:
                votes[name] = self.participants[name].prepare(tx, deltas)
            except ConnectionError:
                votes[name] = "NO"  # a timeout counts as a NO vote
        self._maybe_crash("after-prepare")
        if all(v == "YES" for v in votes.values()):
            self.log.append(("COMMIT", tx, tuple(plan)))  # forced: the commit point
            self._maybe_crash("after-decision")
            acked = []
            for i, name in enumerate(plan):
                acked.append(self._send(name, tx, "COMMIT"))
                if i == 0:
                    self._maybe_crash("after-first-commit")
            if all(acked):
                self.log.append(("END", tx))  # only when every participant has acknowledged
            return "COMMIT"
        # Presumed abort: no ABORT record needs forcing; tell the YES voters to release locks.
        for name, vote in votes.items():
            if vote == "YES":
                self._send(name, tx, "ABORT")
        return "ABORT"

    def _send(self, name: str, tx: str, decision: str) -> bool:
        """Deliver a decision. Returns True when the participant acknowledged it."""
        self.messages += 2  # decision + ack
        try:
            participant = self.participants[name]
            (participant.commit if decision == "COMMIT" else participant.abort)(tx)
            return True
        except ConnectionError:
            return False  # it will ask after restarting, or we resend after our own restart

    def restart(self) -> list[str]:
        """Resend the decision of every committed transaction that has no END record."""
        self.up = True
        ended = {r[1] for r in self.log if r[0] == "END"}
        resent = []
        for record in self.log:
            if record[0] == "COMMIT" and record[1] not in ended:
                if all([self._send(name, record[1], "COMMIT") for name in record[2]]):
                    self.log.append(("END", record[1]))
                resent.append(record[1])
        return resent


# ------------------------------------------------------------------ scenarios
def make_bank() -> tuple[Coordinator, Participant, Participant]:
    shard1 = Participant("shard1", {"alice": 100, "bob": 40})
    shard2 = Participant("shard2", {"carol": 50, "dave": 10})
    return Coordinator({"shard1": shard1, "shard2": shard2}), shard1, shard2


def transfer(amount: int, src="alice", dst="carol") -> dict[str, dict[str, int]]:
    return {"shard1": {src: -amount}, "shard2": {dst: amount}}


def total(shard1: Participant, shard2: Participant) -> int:
    return sum(shard1.data.values()) + sum(shard2.data.values())


def show(title, coord, s1, s2, outcome=None) -> None:
    print(f"  {title}: outcome={outcome}  shard1={s1.data} shard2={s2.data}  total={total(s1, s2)}")
    print(f"     coordinator log {coord.log}")
    print(f"     shard1 log {s1.log}  locks {s1.locks}")
    print(f"     shard2 log {s2.log}  locks {s2.locks}")


def scenario_commit() -> None:
    print("1. Normal transfer of 30 from alice (shard1) to carol (shard2)")
    coord, s1, s2 = make_bank()
    outcome = coord.run("T1", transfer(30))
    show("after", coord, s1, s2, outcome)
    print(f"     messages: {coord.messages} (2 per participant per phase)")


def scenario_vote_no() -> None:
    print("2. A participant votes NO (overdraft): nobody commits")
    coord, s1, s2 = make_bank()
    outcome = coord.run("T2", transfer(500))
    show("after", coord, s1, s2, outcome)


def scenario_participant_down() -> None:
    print("3. shard2 is down during PREPARE: the timeout counts as NO")
    coord, s1, s2 = make_bank()
    s2.crash()
    outcome = coord.run("T3", transfer(30))
    s2.restart()
    show("after", coord, s1, s2, outcome)


def scenario_coordinator_crash_before_decision() -> None:
    print("4. Coordinator crashes after collecting YES votes, before deciding -> participants BLOCK")
    coord, s1, s2 = make_bank()
    coord.crash_at = "after-prepare"
    try:
        coord.run("T4", transfer(30))
    except SimulatedCrash as point:
        print(f"     crash at {point}")
    print(f"     in doubt: shard1 {s1.in_doubt()}, shard2 {s2.in_doubt()}; locks {s1.locks} {s2.locks}")
    try:
        s1.ask_coordinator(coord)
    except ConnectionError as failure:
        print(f"     shard1 asks the coordinator: {failure} -> still blocked; alice is locked")
    print(f"     a new transfer from alice cannot even prepare: {s1.prepare('T5', {'alice': -1})}")
    coord.restart()
    print(f"     coordinator restarts; no decision in its log -> presumed ABORT: "
          f"{s1.ask_coordinator(coord)} {s2.ask_coordinator(coord)}")
    show("after", coord, s1, s2)


def scenario_coordinator_crash_after_decision() -> None:
    print("5. Coordinator crashes after forcing COMMIT, having told only shard1")
    coord, s1, s2 = make_bank()
    coord.crash_at = "after-first-commit"
    try:
        coord.run("T6", transfer(30))
    except SimulatedCrash as point:
        print(f"     crash at {point}")
    print(f"     shard1 committed, shard2 in doubt {s2.in_doubt()}; total right now = {total(s1, s2)} "
          "(the money is 'in flight')")
    resent = coord.restart()
    print(f"     coordinator restart resends COMMIT for {resent}")
    show("after", coord, s1, s2, "COMMIT")


def scenario_participant_crash_after_yes() -> None:
    print("6. shard2 votes YES, then crashes before the decision arrives")
    coord, s1, s2 = make_bank()
    original = s2.commit

    def crash_instead(tx):
        s2.crash()
        return original(tx)

    s2.commit = crash_instead
    coord.run("T7", transfer(30))
    s2.commit = original
    in_doubt = s2.restart()
    print(f"     after restart shard2 rebuilds locks {s2.locks} for in-doubt {in_doubt}")
    print(f"     coordinator log has no END for T7 yet: {coord.log}")
    print(f"     it asks the coordinator: {s2.ask_coordinator(coord)}")
    print(f"     a coordinator restart now would resend COMMIT and close it: {coord.restart()}")
    show("after", coord, s1, s2, "COMMIT")


SCENARIOS = {
    "commit": scenario_commit,
    "vote-no": scenario_vote_no,
    "participant-down": scenario_participant_down,
    "coordinator-crash-before-decision": scenario_coordinator_crash_before_decision,
    "coordinator-crash-after-decision": scenario_coordinator_crash_after_decision,
    "participant-crash-after-yes": scenario_participant_crash_after_yes,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", choices=[*SCENARIOS, "all"], default="all")
    args = parser.parse_args()
    for name, run in SCENARIOS.items():
        if args.scenario in (name, "all"):
            run()
            print()


if __name__ == "__main__":
    main()
