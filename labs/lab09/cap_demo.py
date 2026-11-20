"""Network partitions and the CAP trade-off, measured on two small replicated stores.

* CP: the Raft cluster from raft.py. Writes and linearizable reads need a majority.
* AP: a last-writer-wins (LWW) store. Every replica accepts reads and writes locally and
  copies them to the replicas it can reach; after a partition heals, replicas merge by
  timestamp, as Dynamo-style systems do with LWW conflict resolution.

The same client workload runs against both during a partition {A, B} | {C, D, E}.

    python labs/lab09/cap_demo.py --scenario all
"""

import argparse
import random
from dataclasses import dataclass

from raft import Cluster


# ------------------------------------------------------------------- AP store
@dataclass(frozen=True)
class Version:
    timestamp: int
    node: str
    value: object


class LWWStore:
    """Always available; replicas may disagree during a partition and lose writes on merge."""

    def __init__(self, node_ids=("A", "B", "C", "D", "E")) -> None:
        self.replicas: dict[str, dict[str, Version]] = {n: {} for n in node_ids}
        self.groups: list[set[str]] | None = None
        self.accepted = 0
        self.partition_writes: dict[tuple[str, int], Version] = {}  # (key, side) -> that side's last write

    def reachable(self, node: str) -> list[str]:
        if self.groups is None:
            return list(self.replicas)
        return sorted(next(g for g in self.groups if node in g))

    def write(self, node: str, key: str, value, timestamp: int) -> bool:
        version = Version(timestamp, node, value)
        for peer in self.reachable(node):
            current = self.replicas[peer].get(key)
            if current is None or (version.timestamp, version.node) > (current.timestamp, current.node):
                self.replicas[peer][key] = version
        self.accepted += 1
        if self.groups is not None:
            side = next(i for i, g in enumerate(self.groups) if node in g)
            self.partition_writes[(key, side)] = version
        return True  # available: the write never waits for a majority

    def read(self, node: str, key: str):
        version = self.replicas[node].get(key)
        return None if version is None else version.value

    def partition(self, *groups) -> None:
        self.groups = [set(g) for g in groups]
        self.partition_writes = {}

    def heal(self) -> None:
        keys = {k for replica in self.replicas.values() for k in replica}
        for key in keys:
            winner = max((r[key] for r in self.replicas.values() if key in r),
                         key=lambda v: (v.timestamp, v.node))
            for replica in self.replicas.values():
                replica[key] = winner
        self.lost = [v for (key, _), v in self.partition_writes.items()
                     if next(iter(self.replicas.values()))[key] != v]
        self.groups = None

    def lost_writes(self) -> list[Version]:
        """After heal: each side's final value for a key it wrote during the partition that the
        merge threw away. The client was told those writes succeeded."""
        return list(self.lost)


# --------------------------------------------------------------- workloads
MINORITY, MAJORITY = ("A", "B"), ("C", "D", "E")


def cp_partition_scenario(verbose: bool = True) -> dict:
    """Raft under a partition that isolates the current leader in the minority."""
    cluster = Cluster(seed=9)
    cluster.run_until(lambda: len(cluster.leaders()) == 1)
    old = cluster.leaders()[0]
    index = cluster.write(old, "x", "before")
    cluster.run_until(lambda: cluster.is_committed(old, index, cluster.nodes[old].current_term))
    cluster.run(60)
    others = [n for n in cluster.nodes if n != old]
    minority = (old, others[0])
    majority = tuple(others[1:])
    cluster.partition(minority, majority)
    old_term = cluster.nodes[old].current_term
    stale_index = cluster.write(old, "x", "minority-write")  # accepted into the old leader's log ...
    cluster.run_until(lambda: any(n in majority for n in cluster.leaders()))
    new = next(n for n in cluster.leaders() if n in majority)
    new_index = cluster.write(new, "x", "majority-write")
    new_term = cluster.nodes[new].current_term
    cluster.run_until(lambda: cluster.is_committed(new, new_index, new_term))
    cluster.run(200)

    results = {"leaders_during_partition": cluster.leaders(), "old_leader": old, "new_leader": new}
    results["minority_write_committed"] = cluster.is_committed(old, stale_index, old_term)
    results["majority_write_committed"] = cluster.is_committed(new, new_index, new_term)
    reads = {}
    for node in (old, new):
        try:
            reads[node] = cluster.read(node, "x")
        except RuntimeError:
            reads[node] = "REFUSED (no lease)"
    results["linearizable_reads"] = reads
    results["stale_local_read_on_old_leader"] = cluster.read(old, "x", linearizable=False)
    partition_events = len(cluster.events)

    cluster.heal()
    cluster.run(400)
    results["after_heal_leaders"] = cluster.leaders()
    results["after_heal_values"] = {n: node.kv.get("x") for n, node in sorted(cluster.nodes.items())}
    results["minority_entry_survived"] = any(
        e.command == ("set", "x", "minority-write") for node in cluster.nodes.values() for e in node.log)
    results["election_safety"] = cluster.election_safety()

    if verbose:
        print(f"Partition {''.join(minority)} | {''.join(majority)} with the old leader {old} in the minority")
        print(f"  leaders during the partition: {results['leaders_during_partition']} "
              f"(old {old} in term {old_term}, new {new} in term {new_term})")
        print(f"  write to old leader {old} committed? {results['minority_write_committed']}  -> unavailable")
        print(f"  write to new leader {new} committed? {results['majority_write_committed']}")
        print(f"  linearizable reads: {reads}")
        print(f"  a NON-linearizable local read on {old} returns {results['stale_local_read_on_old_leader']!r} (stale)")
        print("  after heal:")
        for now, text in cluster.events[partition_events:]:
            print(f"    t={now:<5} {text}")
        print(f"  values {results['after_heal_values']}; the minority write survived anywhere? "
              f"{results['minority_entry_survived']}; election safety {results['election_safety']}")
    return results


def ap_partition_scenario(verbose: bool = True) -> dict:
    store = LWWStore()
    store.write("A", "x", "before", timestamp=1)
    store.partition(MINORITY, MAJORITY)
    store.write("A", "x", "minority-write", timestamp=3)  # minority clock happens to run ahead
    store.write("C", "x", "majority-write", timestamp=2)
    reads = {node: store.read(node, "x") for node in ("A", "C")}
    store.heal()
    final = store.read("C", "x")
    lost = store.lost_writes()
    if verbose:
        print("Same partition, last-writer-wins store")
        print("  writes accepted on both sides: 2 of 2  -> available")
        print(f"  reads during the partition: {reads}  -> replicas disagree")
        print(f"  after heal every replica holds {final!r}; acknowledged writes lost: "
              f"{[v.value for v in lost]}")
        print("  The loser is chosen by clock value, not by real order: the majority's write vanished.")
    return {"reads": reads, "final": final, "lost": [v.value for v in lost]}


def availability_table(seed: int = 4, requests: int = 200) -> None:
    """Random clients on both sides of the partition: how many requests succeed, and how many anomalies."""
    rng = random.Random(seed)
    cluster = Cluster(seed=seed)
    cluster.run_until(lambda: len(cluster.leaders()) == 1)
    leader = cluster.leaders()[0]
    others = [n for n in cluster.nodes if n != leader]
    minority, majority = (leader, others[0]), tuple(others[1:])
    cluster.partition(minority, majority)
    cluster.run(600)  # the majority elects its own leader
    store = LWWStore(tuple(cluster.nodes))
    store.partition(minority, majority)

    stats = {"CP (Raft)": dict.fromkeys(["min_ok", "min_total", "maj_ok", "maj_total", "stale", "lost"], 0),
             "AP (LWW)": dict.fromkeys(["min_ok", "min_total", "maj_ok", "maj_total", "stale", "lost"], 0)}
    truth = {}
    pending = []
    for t in range(requests):
        side = minority if rng.random() < 0.4 else majority
        node = rng.choice(side)
        side_key = "min" if side is minority else "maj"
        key = f"k{rng.randint(0, 4)}"
        is_write = rng.random() < 0.5
        for system in stats:
            stats[system][f"{side_key}_total"] += 1
        # CP: requests go to the node's side leader, if that side has one with a lease.
        leaders = [n for n in cluster.leaders() if n in side and cluster.nodes[n].has_lease(cluster.now)]
        if leaders:
            if is_write:
                idx = cluster.write(leaders[0], key, t)
                pending.append((leaders[0], idx, cluster.nodes[leaders[0]].current_term, key, t))
            stats["CP (Raft)"][f"{side_key}_ok"] += 1
        # AP: every request succeeds locally.
        if is_write:
            store.write(node, key, t, timestamp=t)
            truth[key] = t
        elif store.read(node, key) != truth.get(key):
            stats["AP (LWW)"]["stale"] += 1
        stats["AP (LWW)"][f"{side_key}_ok"] += 1
        cluster.run(3)
    cluster.run(200)
    store.heal()
    stats["AP (LWW)"]["lost"] = len(store.lost_writes())
    committed = sum(cluster.is_committed(n, i, term) for n, i, term, _, _ in pending)
    stats["CP (Raft)"]["lost"] = len(pending) - committed  # acknowledged only after commit -> 0
    print(f"{requests} random requests during a partition {''.join(minority)} | {''.join(majority)} "
          f"(40% on the minority side)")
    print(f"  {'system':<11}{'minority ok':>13}{'majority ok':>13}{'stale reads':>13}{'lost writes':>13}")
    for system, s in stats.items():
        print(f"  {system:<11}{s['min_ok']:>6}/{s['min_total']:<6}{s['maj_ok']:>6}/{s['maj_total']:<6}"
              f"{s['stale']:>13}{s['lost']:>13}")
    print("  CP refuses the minority side but never returns stale data; AP answers everyone and pays")
    print("  with stale reads during the partition and silently discarded writes after it.")


def split_vote_experiment(runs: int = 200) -> None:
    """Why Raft randomizes election timeouts: elections needed and time to the first leader."""
    print(f"First election over {runs} seeded runs (5 nodes, message delay 5-15 ticks)")
    print(f"  {'timeout range':<16}{'no leader':>11}{'mean elections':>16}{'mean ticks':>12}{'worst ticks':>13}")
    for low, high in ((150, 150), (150, 160), (150, 300), (150, 600)):
        elections, ticks, failed = [], [], 0
        for seed in range(runs):
            cluster = Cluster(seed=seed, election_timeout=(low, high))
            if not cluster.run_until(lambda: len(cluster.leaders()) == 1, limit=5000):
                failed += 1
                continue
            elections.append(cluster.elections)
            ticks.append(cluster.now)
        label = f"[{low}, {high}]"
        if not ticks:
            print(f"  {label:<16}{failed:>7}/{runs:<3}{'-':>16}{'-':>12}{'-':>13}")
            continue
        print(f"  {label:<16}{failed:>7}/{runs:<3}{sum(elections) / len(ticks):>16.2f}"
              f"{sum(ticks) / len(ticks):>12.0f}{max(ticks):>13}")
    print("  'no leader' = no leader within 5,000 ticks. Equal timeouts make candidates collide and")
    print("  split the vote forever (every node times out together); a wider range")
    print("  separates them but makes every failover wait longer.")


SCENARIOS = {
    "cp": cp_partition_scenario,
    "ap": ap_partition_scenario,
    "availability": availability_table,
    "split-vote": split_vote_experiment,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", choices=[*SCENARIOS, "all"], default="all")
    args = parser.parse_args()
    for name, run in SCENARIOS.items():
        if args.scenario in (name, "all"):
            print("\n" + "=" * 78 + f"\n{name}\n" + "=" * 78)
            run()


if __name__ == "__main__":
    main()
