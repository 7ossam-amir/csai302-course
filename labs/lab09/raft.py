"""A simplified Raft for Lab 9: leader election, heartbeats, and majority-committed log entries.

The simulation is deterministic: one seeded random generator draws every election
timeout and message delay. Time moves in integer ticks (think "milliseconds").
Each tick, the network delivers the messages that are due, then every running node
looks at its timers.

What is implemented, following the Raft paper (Ongaro and Ousterhout, 2014):

* terms, RequestVote with the "candidate log is at least as up to date" rule,
  one vote per term, randomized election timeouts, and step-down on a higher term;
* heartbeats as AppendEntries, log matching with prevLogIndex / prevLogTerm,
  deletion of conflicting entries, and commit only by a majority of the current term;
* a no-op entry when a node becomes leader, and lease-based reads that a leader serves
  only while a majority has answered it recently.

What is left out: snapshots, membership changes, persistence to disk, pre-vote,
batching, and client sessions. Network partitions are modelled as groups of nodes
that can only talk inside their own group.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

FOLLOWER, CANDIDATE, LEADER = "follower", "candidate", "leader"


@dataclass(frozen=True)
class Entry:
    term: int
    command: tuple | None  # ("set", key, value), or None for a leader's no-op


@dataclass
class Message:
    kind: str  # RequestVote, Vote, Append, AppendReply
    src: str
    dst: str
    term: int
    last_log_index: int = 0
    last_log_term: int = 0
    granted: bool = False
    prev_index: int = 0
    prev_term: int = 0
    entries: tuple = ()
    leader_commit: int = 0
    success: bool = False
    match_index: int = 0


class Network:
    """Delivers messages after a random delay, unless a partition separates the two nodes."""

    def __init__(self, rng: random.Random, delay=(5, 15)) -> None:
        self.rng = rng
        self.delay = delay
        self.groups: list[set[str]] | None = None  # None = everyone can talk
        self.in_flight: list[tuple[int, int, Message]] = []
        self.sent = self.dropped = 0
        self._seq = 0

    def connected(self, a: str, b: str) -> bool:
        if self.groups is None:
            return True
        return any(a in group and b in group for group in self.groups)

    def send(self, message: Message, now: int) -> None:
        self.sent += 1
        if not self.connected(message.src, message.dst):
            self.dropped += 1
            return
        self._seq += 1
        self.in_flight.append((now + self.rng.randint(*self.delay), self._seq, message))

    def due(self, now: int) -> list[Message]:
        ready = sorted(m for m in self.in_flight if m[0] <= now)
        self.in_flight = [m for m in self.in_flight if m[0] > now]
        delivered = []
        for _, _, message in ready:
            if self.connected(message.src, message.dst):  # the partition may have started in flight
                delivered.append(message)
            else:
                self.dropped += 1
        return delivered


class RaftNode:
    def __init__(self, node_id: str, peers: list[str], cluster: "Cluster") -> None:
        self.id = node_id
        self.peers = [p for p in peers if p != node_id]
        self.cluster = cluster
        # persistent state (survives stop/start)
        self.current_term = 0
        self.voted_for: str | None = None
        self.log: list[Entry] = []
        # volatile state
        self.state = FOLLOWER
        self.leader_id: str | None = None
        self.commit_index = 0
        self.kv: dict[str, object] = {}
        self.last_applied = 0
        self.votes: set[str] = set()
        self.next_index: dict[str, int] = {}
        self.match_index: dict[str, int] = {}
        self.last_ack: dict[str, int] = {}
        self.election_deadline = 0
        self.next_heartbeat = 0
        self.reset_election_timer(0)

    # ---------------------------------------------------------------- helpers
    @property
    def majority(self) -> int:
        return (len(self.peers) + 1) // 2 + 1

    @property
    def last_log_index(self) -> int:
        return len(self.log)

    @property
    def last_log_term(self) -> int:
        return self.log[-1].term if self.log else 0

    def term_at(self, index: int) -> int:
        return self.log[index - 1].term if index > 0 else 0

    def reset_election_timer(self, now: int) -> None:
        self.election_deadline = now + self.cluster.rng.randint(*self.cluster.election_timeout)

    def send(self, now: int, **fields) -> None:
        self.cluster.network.send(Message(src=self.id, term=self.current_term, **fields), now)

    def become_follower(self, term: int, now: int) -> None:
        if self.state == LEADER:
            self.cluster.event(now, f"{self.id} steps down (saw term {term})")
            self.reset_election_timer(now)  # a leader's timer was not running: start a fresh one
        if term > self.current_term:
            self.current_term = term
            self.voted_for = None
        self.state = FOLLOWER

    def apply_committed(self, now: int) -> None:
        while self.last_applied < self.commit_index:
            self.last_applied += 1
            command = self.log[self.last_applied - 1].command
            if command is not None:
                _, key, value = command
                self.kv[key] = value

    # ---------------------------------------------------------------- timers
    def tick(self, now: int) -> None:
        if self.state == LEADER:
            if now >= self.next_heartbeat:
                self.broadcast_append(now)
        elif now >= self.election_deadline:
            self.start_election(now)

    def start_election(self, now: int) -> None:
        self.current_term += 1
        self.state = CANDIDATE
        self.voted_for = self.id
        self.votes = {self.id}
        self.leader_id = None
        self.reset_election_timer(now)
        self.cluster.event(now, f"{self.id} starts election for term {self.current_term}")
        self.cluster.elections += 1
        for peer in self.peers:
            self.send(now, kind="RequestVote", dst=peer,
                      last_log_index=self.last_log_index, last_log_term=self.last_log_term)
        self.maybe_win(now)

    def maybe_win(self, now: int) -> None:
        if self.state == CANDIDATE and len(self.votes) >= self.majority:
            self.state = LEADER
            self.leader_id = self.id
            self.cluster.record_leader(self.current_term, self.id, now)
            self.log.append(Entry(self.current_term, None))  # no-op: lets earlier entries commit
            self.next_index = {p: self.last_log_index for p in self.peers}
            self.match_index = {p: 0 for p in self.peers}
            self.last_ack = {p: now for p in self.peers}
            self.broadcast_append(now)

    def broadcast_append(self, now: int) -> None:
        self.next_heartbeat = now + self.cluster.heartbeat_interval
        for peer in self.peers:
            prev = self.next_index[peer] - 1
            self.send(now, kind="Append", dst=peer, prev_index=prev, prev_term=self.term_at(prev),
                      entries=tuple(self.log[prev:]), leader_commit=self.commit_index)
        self.advance_commit(now)

    def advance_commit(self, now: int) -> None:
        for n in range(self.last_log_index, self.commit_index, -1):
            if self.log[n - 1].term != self.current_term:
                break  # Raft never commits an older term's entry by counting replicas
            replicas = 1 + sum(1 for p in self.peers if self.match_index[p] >= n)
            if replicas >= self.majority:
                self.commit_index = n
                self.cluster.event(now, f"{self.id} commits up to index {n} (term {self.current_term})")
                self.apply_committed(now)
                break

    def has_lease(self, now: int) -> bool:
        """A leader may serve a read only while a majority answered it within one minimum timeout."""
        if self.state != LEADER:
            return False
        window = self.cluster.election_timeout[0]
        fresh = 1 + sum(1 for p in self.peers if now - self.last_ack[p] <= window)
        return fresh >= self.majority

    # -------------------------------------------------------------- messages
    def receive(self, m: Message, now: int) -> None:
        if m.term > self.current_term:
            self.become_follower(m.term, now)
        handler = getattr(self, f"on_{m.kind}")
        handler(m, now)

    def on_RequestVote(self, m: Message, now: int) -> None:
        up_to_date = (m.last_log_term, m.last_log_index) >= (self.last_log_term, self.last_log_index)
        granted = (m.term == self.current_term and self.voted_for in (None, m.src) and up_to_date)
        if granted:
            self.voted_for = m.src
            self.reset_election_timer(now)
        self.send(now, kind="Vote", dst=m.src, granted=granted)

    def on_Vote(self, m: Message, now: int) -> None:
        if self.state == CANDIDATE and m.term == self.current_term and m.granted:
            self.votes.add(m.src)
            self.maybe_win(now)

    def on_Append(self, m: Message, now: int) -> None:
        if m.term < self.current_term:
            self.send(now, kind="AppendReply", dst=m.src, success=False)
            return
        if self.state != FOLLOWER:
            self.become_follower(m.term, now)
        self.leader_id = m.src
        self.reset_election_timer(now)
        if m.prev_index > self.last_log_index or self.term_at(m.prev_index) != m.prev_term:
            self.send(now, kind="AppendReply", dst=m.src, success=False)
            return
        for offset, entry in enumerate(m.entries):
            index = m.prev_index + 1 + offset
            if index <= self.last_log_index and self.log[index - 1].term != entry.term:
                del self.log[index - 1:]  # conflict: drop this entry and everything after it
            if index > self.last_log_index:
                self.log.append(entry)
        match = m.prev_index + len(m.entries)
        if m.leader_commit > self.commit_index:
            self.commit_index = min(m.leader_commit, match)
            self.apply_committed(now)
        self.send(now, kind="AppendReply", dst=m.src, success=True, match_index=match)

    def on_AppendReply(self, m: Message, now: int) -> None:
        if self.state != LEADER or m.term != self.current_term:
            return
        self.last_ack[m.src] = now
        if m.success:
            self.match_index[m.src] = max(self.match_index[m.src], m.match_index)
            self.next_index[m.src] = self.match_index[m.src] + 1
            self.advance_commit(now)
        else:
            self.next_index[m.src] = max(1, self.next_index[m.src] - 1)  # back up and retry


class Cluster:
    """N Raft nodes, one network, and a clock."""

    def __init__(self, node_ids=("A", "B", "C", "D", "E"), *, seed: int = 9,
                 election_timeout=(150, 300), heartbeat_interval: int = 50, delay=(5, 15)) -> None:
        self.rng = random.Random(seed)
        self.election_timeout = election_timeout
        self.heartbeat_interval = heartbeat_interval
        self.network = Network(self.rng, delay)
        self.now = 0
        self.events: list[tuple[int, str]] = []
        self.leaders_by_term: dict[int, set[str]] = {}
        self.elections = 0
        self.stopped: set[str] = set()
        self.nodes = {}
        for node_id in node_ids:
            self.nodes[node_id] = RaftNode(node_id, list(node_ids), self)

    # ------------------------------------------------------------ bookkeeping
    def event(self, now: int, text: str) -> None:
        self.events.append((now, text))

    def record_leader(self, term: int, node_id: str, now: int) -> None:
        self.leaders_by_term.setdefault(term, set()).add(node_id)
        self.event(now, f"{node_id} becomes LEADER of term {term}")

    def election_safety(self) -> bool:
        """Raft's guarantee: at most one leader per term."""
        return all(len(ids) == 1 for ids in self.leaders_by_term.values())

    # ----------------------------------------------------------------- clock
    def step(self) -> None:
        self.now += 1
        for message in self.network.due(self.now):
            if message.dst not in self.stopped:
                self.nodes[message.dst].receive(message, self.now)
        for node_id in sorted(self.nodes):
            if node_id not in self.stopped:
                self.nodes[node_id].tick(self.now)

    def run(self, ticks: int) -> None:
        for _ in range(ticks):
            self.step()

    def run_until(self, condition, limit: int = 5000) -> bool:
        for _ in range(limit):
            if condition():
                return True
            self.step()
        return condition()

    # ---------------------------------------------------------- failures
    def partition(self, *groups) -> None:
        self.network.groups = [set(g) for g in groups]
        self.event(self.now, "PARTITION " + " | ".join("".join(sorted(g)) for g in groups))

    def heal(self) -> None:
        self.network.groups = None
        self.event(self.now, "HEAL: all nodes connected")

    def stop(self, node_id: str) -> None:
        self.stopped.add(node_id)
        self.event(self.now, f"{node_id} STOPS")

    def start(self, node_id: str) -> None:
        """Restart: term, vote, and log persist; everything else is rebuilt."""
        old = self.nodes[node_id]
        node = RaftNode(node_id, list(self.nodes), self)
        node.current_term, node.voted_for, node.log = old.current_term, old.voted_for, old.log
        node.reset_election_timer(self.now)
        self.nodes[node_id] = node
        self.stopped.discard(node_id)
        self.event(self.now, f"{node_id} RESTARTS as follower in term {node.current_term}")

    # ------------------------------------------------------------- clients
    def leaders(self) -> list[str]:
        """Nodes that currently believe they lead (there can be two during a partition)."""
        return sorted(n for n, node in self.nodes.items() if node.state == LEADER and n not in self.stopped)

    def write(self, node_id: str, key: str, value) -> int | None:
        """Ask node_id to append a write. Returns its log index, or None if node_id is not a leader."""
        node = self.nodes[node_id]
        if node_id in self.stopped or node.state != LEADER:
            return None
        node.log.append(Entry(node.current_term, ("set", key, value)))
        return node.last_log_index

    def is_committed(self, node_id: str, index: int, term: int) -> bool:
        node = self.nodes[node_id]
        return node.commit_index >= index and node.term_at(index) == term

    def read(self, node_id: str, key: str, *, linearizable: bool = True):
        """Linearizable reads go through a leader that holds a lease; others read local state."""
        node = self.nodes[node_id]
        if linearizable and not node.has_lease(self.now):
            raise RuntimeError(f"{node_id} cannot serve a linearizable read (no leader lease)")
        return node.kv.get(key)

    def status(self) -> str:
        rows = []
        for node_id, node in sorted(self.nodes.items()):
            down = " (stopped)" if node_id in self.stopped else ""
            rows.append(f"  {node_id}: {node.state:<9} term {node.current_term:<2} log {node.last_log_index:<2} "
                        f"commit {node.commit_index:<2} kv {node.kv}{down}")
        return "\n".join(rows)


def main() -> None:
    cluster = Cluster(seed=9)
    cluster.run_until(lambda: len(cluster.leaders()) == 1)
    leader = cluster.leaders()[0]
    print(f"t={cluster.now}: first leader is {leader}")
    index = cluster.write(leader, "x", 1)
    term = cluster.nodes[leader].current_term
    cluster.run_until(lambda: cluster.is_committed(leader, index, term))
    print(f"t={cluster.now}: x=1 committed at index {index}")
    cluster.run(100)
    cluster.stop(leader)
    cluster.run_until(lambda: any(l != leader for l in cluster.leaders()))
    print(f"t={cluster.now}: after {leader} stops, new leader is {cluster.leaders()}")
    cluster.start(leader)
    cluster.run(300)
    print("\nEvents:")
    for now, text in cluster.events:
        print(f"  t={now:<4} {text}")
    print("\nFinal state:")
    print(cluster.status())
    print(f"\nElection safety (one leader per term): {cluster.election_safety()}; "
          f"messages sent {cluster.network.sent}, dropped {cluster.network.dropped}")


if __name__ == "__main__":
    main()
