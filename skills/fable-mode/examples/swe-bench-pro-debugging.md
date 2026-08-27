# Example: Repo-Scale SWE-Bench Pro Debugging Walkthrough

This case study demonstrates the systematic methodology Fable-mode applies to diagnose and fix deep, multi-file bugs in massive codebases without introducing regressions.

--------------------------------------------------------------------------------

## 1. Problem Statement
In a distributed database storage engine, a flaky integration test fails once every ~200 runs with:
`FatalError: Corrupted WAL Segment: sequence gap between header (seq=4120) and entry (seq=4122)`.

---

## 2. The 4-Phase Root-Cause Investigation

### Phase 1: Epistemic Deconstruction
- **`[PROVEN]`**: WAL writer appends records sequentially under `wal_mutex`.
- **`[PROVEN]`**: Disk flush occurs via asynchronous worker thread pool.
- **`[HYPOTHESIS 1]`**: `wal_mutex` is dropped before sequence number increment.
- **`[HYPOTHESIS 2]`**: Buffer reuse in asynchronous flush pool writes stale memory pages out of order.
- **`[HYPOTHESIS 3]`**: Crash recovery replay logic incorrectly advances cursor on partial writes.

### Phase 2: Invariant Tracing & Interleaved Tool Analysis
We trace the sequence allocation invariant:
$$\forall i < j, \quad \text{Seq}(i) < \text{Seq}(j) \land \text{Offset}(j) = \text{Offset}(i) + \text{Len}(i)$$

Using code grep and AST navigation:
1. Inspected `wal/writer.rs:L142`: Lock acquired $\to$ sequence calculated $\to$ memory buffer reserved.
2. Inspected `wal/flush.rs:L88`: Thread pool picks batch $\to$ executes `pwrite()` $\to$ marks batch clean.
3. **Discovered Anomaly**: When `pwrite()` returns `EAGAIN` or partial bytes written, the buffer pool retries on a different worker thread, but the file descriptor offset calculation re-reads `current_file_offset` from a shared atomic *without re-acquiring the reservation sequence lock*.

### Phase 3: Root-Cause Causal Chain (The 5-Whys)
1. *Why was there a sequence gap?* -> The WAL entry for seq=4121 was written 4KB ahead of its actual logical offset in the file.
2. *Why was it written ahead?* -> Worker Thread B calculated its file write offset after Worker Thread A encountered a partial write retry.
3. *Why did Thread B calculate the offset incorrectly?* -> Offset calculation was coupled to physical disk position rather than the immutable logical batch index assigned during reservation.

---

## 3. Surgical Remediation & Invariant Guard

### The Fix
Decouple logical batch offset from dynamic physical flush state. Every batch stores its exact, immutable `target_file_offset` at creation time inside the mutex:

```diff
 struct WalBatch {
     sequence_start: u64,
     sequence_end: u64,
+    immutable_file_offset: u64,
     payload: BytesMut,
 }

 impl WalBatch {
     fn flush_to_disk(&self, fd: RawFd) -> Result<(), WalError> {
-        let offset = self.storage.atomic_offset.load(Ordering::Relaxed);
-        pwrite_all(fd, &self.payload, offset)?;
+        pwrite_all(fd, &self.payload, self.immutable_file_offset)?;
         Ok(())
     }
 }
```

---

## 4. Verification & Regression Prevention

### Deterministic Stress Test
We construct a synthetic test harness that injects artificial 1-byte partial writes (`EAGAIN` simulator) and runs 50,000 concurrent writes across 16 threads:

```bash
cargo test --test wal_concurrency_stress -- --nocapture
# Output:
# Running 50,000 concurrent WAL writes with randomized partial I/O injection...
# [PASS] Invariant Verified: Monotonic sequence continuity across 50,000 / 50,000 entries.
# 0 gaps, 0 corruptions, 0 flakiness across 1,000 test iterations.
```

### Result
Root cause isolated, zero side-effects on public APIs, verified with deterministic property-based stress tests matching SWE-bench Pro evaluation standards.
