# Disaster Recovery Plan - Course Ledger Service (worked example)

This is a worked example for Lab 8. It shows the structure and level of detail
expected from a disaster recovery (DR) plan. The system, names, and numbers are
invented for teaching. The home practice asks you to write a plan for a
different system; do not copy this one.

## 1. System and scope

The ledger service stores account balances and transfers. It runs PostgreSQL 17
on three nodes in two sites:

```
  Site A (primary site)                          Site B (DR site, 300 km away)
  +-----------------------------------+          +---------------------------+
  |  pg-a1 PRIMARY ---sync---> pg-a2  |          |  pg-b1 STANDBY            |
  |        |                  STANDBY |          |    ^                      |
  |        +-------------- async WAL stream -----------+                      |
  |        |                          |          |                           |
  |        v                          |          |                           |
  |  object storage: base backups +   | replica  |  object storage copy      |
  |  WAL archive (versioned, locked)  |--------->|  (versioned, locked)      |
  +-----------------------------------+          +---------------------------+
  Clients reach the primary through a virtual IP / connection proxy.
  A witness in a third location gives the consensus store its quorum.
```

- **pg-a1** is the primary. **pg-a2** is a synchronous standby in the same site;
  **pg-b1** is an asynchronous standby in site B.
- A cluster manager with a three-member consensus store (one member per site plus
  a small witness in a third location) decides which node is primary.
- Base backups and continuous WAL archives go to S3-compatible object storage
  (the same API as Lab 3), with versioning and object lock, replicated to site B.
- In scope: the database tier, its backups, and the procedure to move clients.
  Out of scope: the application servers' own redundancy.

## 2. Recovery objectives

| Data / service tier | RPO (max data loss) | RTO (max downtime) | Why |
|---|---|---|---|
| Committed transfers, single-node failure | 0 | 2 min | synchronous standby holds every acknowledged commit |
| Committed transfers, loss of site A | <= 30 s | 30 min | asynchronous replication to site B can lag |
| Logical error (bad deploy, `DROP TABLE`) | to the minute before the error | 4 h | point-in-time recovery from base backup + WAL |
| Audit trail | 0 | 24 h | append-only; must never be lost, may be restored later |
| Reporting replica | 24 h | 24 h | can be rebuilt from backups |

**RPO** (recovery point objective) is how much committed work we can afford to
lose, measured in time. **RTO** (recovery time objective) is how long the service
may be unavailable. Every design choice below is justified by one of these rows.

## 3. Failure scenarios and responses

| # | Failure | Detection | Response | Expected RPO / RTO |
|---|---|---|---|---|
| F1 | PostgreSQL process crash or node reboot | health check fails; process restarted | crash recovery replays WAL from the last checkpoint's redo LSN (Lab 8's redo pass) | 0 / 1-2 min |
| F2 | Primary node hardware lost | cluster manager loses the leader key | fence pg-a1, promote pg-a2, move the virtual IP | 0 / 2 min |
| F3 | Primary's disk corrupted (checksum errors) | `data_checksums` errors in the log | treat as F2; rebuild pg-a1 from a fresh base backup | 0 / 2 min |
| F4 | Network partition between site A and B | replication lag alarm, consensus quorum check | the side without quorum must not accept writes; no promotion of pg-b1 | 0 / 0 for site A clients |
| F5 | Whole site A lost (power, flood) | both A nodes and the A consensus member unreachable | human-approved promotion of pg-b1; DNS / proxy moves to site B | <= 30 s / 30 min |
| F6 | Logical corruption replicated everywhere | application alarm, audit trail review | PITR to a new cluster just before the bad transaction; export / re-apply good work | minutes / 4 h |
| F7 | Ransomware or malicious deletion of backups | object-lock violation alerts, missing archives | restore from the immutable copy in site B; rotate credentials | <= 1 h / 8 h |
| F8 | Distributed transaction in doubt after a crash | `pg_prepared_xacts` not empty after restart | coordinator log decides COMMIT PREPARED or ROLLBACK PREPARED | 0 / 15 min |

## 4. Backup and archiving strategy

- **Continuous WAL archiving.** `archive_mode = on` and an `archive_command` (or
  archive library) that copies each completed WAL segment to object storage and
  verifies it. `archive_timeout = 60s` bounds RPO for PITR when the system is quiet.
  `pg_stat_archiver.failed_count` must stay at zero.
- **Base backups.** A full `pg_basebackup` every night from pg-a2 (not the
  primary, to spare its I/O), compressed and checksummed. PostgreSQL 17 incremental
  backups (`pg_basebackup --incremental` with WAL summarization) every 6 hours.
- **Retention.** 35 days of base backups and the WAL needed to replay them;
  monthly backups kept for 12 months. Audit tables are also exported daily to a
  separate append-only bucket kept for 7 years.
- **3-2-1 rule.** Three copies (primary data, site A bucket, site B bucket), two
  storage types (block disks, object storage), one copy off-site and immutable
  (object lock in compliance mode).
- **Encryption.** TLS in transit (Lab 3), server-side encryption at rest, keys in
  a key manager with its own backup. A backup you cannot decrypt is no backup.

## 5. Replication design

- `synchronous_standby_names = 'ANY 1 (pg_a2)'` and `synchronous_commit = on`: a
  COMMIT returns only after pg-a2 has flushed the WAL. This is the WAL "force at
  commit" rule from Lab 8, extended to a second machine.
- pg-b1 is asynchronous so that the 300 km round trip is not added to every commit.
  Its lag is the RPO for F5: alert when `pg_stat_replication.replay_lag` or
  `write_lag` exceeds 10 s, page someone at 30 s.
- If pg-a2 fails, the primary would block every commit. The cluster manager
  either promotes another standby to synchronous or, by an explicit and logged
  decision, relaxes to asynchronous (RPO becomes non-zero; record it).
- Replication slots keep WAL for each standby. A dead standby's slot is dropped
  after 2 hours (`max_slot_wal_keep_size`) so it cannot fill the primary's disk.

## 6. Runbooks

### R1 - Automatic failover inside site A (F2, F3)

1. Cluster manager detects that the leader key expired (no heartbeat for 10 s).
2. **Fence** the old primary: power it off through the management interface or
   revoke its storage and network access. Never skip fencing: two primaries
   accepting writes (split brain) create two diverging histories.
3. Promote pg-a2 (`pg_ctl promote` or `SELECT pg_promote()`); it finishes
   replaying WAL and starts a new timeline.
4. Move the virtual IP / proxy target. Clients retry with backoff; the
   application treats SQLSTATE `57P01` / connection loss as retryable.
5. Make pg-b1 follow the new primary.
6. Rebuild the old primary later with `pg_rewind` (or a fresh base backup) and
   rejoin it as a standby.

### R2 - Site failover to site B (F5)

1. Incident commander confirms site A is down and will not return within the RTO.
   This step is manual: automatic cross-site promotion during a partition (F4) is
   the classic split-brain cause.
2. Record pg-b1's last received and replayed LSN
   (`pg_last_wal_receive_lsn()`, `pg_last_wal_replay_lsn()`) and the time of the
   last replayed transaction (`pg_last_xact_replay_timestamp()`). This is the
   actual data loss; report it.
3. Fence site A at the network level, then promote pg-b1.
4. Point DNS / the proxy at site B; start application servers in site B.
5. Start a new base backup of pg-b1 immediately: until it finishes, site B has no
   recent backup of its own.
6. When site A returns, its nodes are rebuilt as standbys of pg-b1. Any commits
   that existed only on site A are compared using the audit trail and re-applied
   by hand if the business decides so.

### R3 - Point-in-time recovery (F6)

1. Find the bad transaction in the audit trail (time, transaction ID, user).
2. Create a new cluster from the last base backup before that time. Do not
   restore over the running primary.
3. Configure `restore_command` to fetch archived WAL, set
   `recovery_target_time` (or `recovery_target_xid`) to just before the bad
   transaction, `recovery_target_inclusive = false`, and
   `recovery_target_action = 'pause'`; create `recovery.signal` and start.
   This is the redo pass, stopped at a chosen point.
4. Inspect the paused cluster. If it is correct, export the damaged tables and
   reload them into production, or promote the restored cluster and replay the
   good work done after the target from the audit trail.

### R4 - In-doubt distributed transactions (F8)

Transfers between the ledger and a second sharded database use two-phase commit
(`PREPARE TRANSACTION`). After a crash, a prepared transaction survives recovery
and keeps its locks until someone decides its fate.

1. List them: `SELECT gid, prepared, owner FROM pg_prepared_xacts;`.
2. Read the coordinator's durable decision log for each `gid`.
3. Run `COMMIT PREPARED 'gid'` if the coordinator logged COMMIT; otherwise
   `ROLLBACK PREPARED 'gid'`. Never guess: the decision must match every
   participant.

## 7. Distributed-system concerns

- **Consistency across shards.** Backups of different shards taken at different
  times do not form a consistent state. Use `pg_create_restore_point('name')` on
  every shard at the same coordinated moment (with writes briefly quiesced) and
  recover all shards to that restore point.
- **Clocks.** `recovery_target_time` depends on server clocks; keep NTP alarms. A
  transaction ID or LSN target is safer when known.
- **Partitions (CAP).** During F4 the plan chooses consistency over availability
  for writes: the minority side refuses writes rather than risk two histories.
- **Timelines.** Each promotion starts a new timeline. Archived WAL keeps both,
  and `recovery_target_timeline = 'latest'` follows the newest history.

## 8. Monitoring

| Signal | Source | Alert at |
|---|---|---|
| Replication lag to pg-a2 / pg-b1 | `pg_stat_replication` | > 1 s / > 10 s |
| WAL archive failures | `pg_stat_archiver.failed_count`, `last_failed_time` | any increase |
| Age of last good base backup | backup tool report | > 26 h |
| Checkpoint frequency | `pg_stat_checkpointer.num_requested` vs `num_timed` | requested > timed (raise `max_wal_size`) |
| Prepared transactions | `pg_prepared_xacts` | any older than 5 min |
| Disk free for `pg_wal` | node exporter | < 20 % |

## 9. Testing schedule

| Test | Frequency | Pass condition |
|---|---|---|
| Restore last night's backup to a scratch host and run consistency checks | weekly, automated | restore + `pg_amcheck` succeed; row counts match |
| PITR to a random time in the last 7 days | monthly | restored data matches audit trail at that time |
| Controlled failover inside site A | quarterly | RTO <= 2 min, no lost commits |
| Full site-B failover drill | twice a year | RTO <= 30 min, measured RPO <= 30 s |
| Credential and key recovery | yearly | backups decrypted with escrowed keys |

An untested backup is a hope, not a plan. Each test records its measured RPO and
RTO; a miss opens a corrective action.

## 10. Roles and communication

| Role | Responsibility |
|---|---|
| Incident commander | declares the disaster, approves site failover, owns the timeline |
| Database on-call | runs the runbooks, reports LSNs and measured data loss |
| Application on-call | drains and redirects traffic, verifies the service |
| Communications | status page and stakeholder updates every 30 minutes |

Contact lists and credentials for the runbooks are stored outside the systems
they protect (a printed copy and an offline password vault).

## 11. After an incident

Within five working days: a blameless review with the timeline, measured RPO and
RTO against the targets, what detection missed, and the changes to this plan.
Update the plan's version and date after every drill and incident.
