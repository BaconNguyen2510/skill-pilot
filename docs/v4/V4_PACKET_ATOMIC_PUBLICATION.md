# V4 Blind Packet Write-Once Publication: Crash Safety

## Defect and acceptance criterion

Previous blind packet generation used `open(path, 'x')` followed by incremental writes and fsync. Exclusive creation prevents overwriting another packet, but an interrupted writer can leave a **partially written final file**. Human reviewers or validators may mistake that incomplete file for a finished packet. The final output must either be absent or complete, and concurrent attempts must not overwrite each other.

## Research-first comparison (Python 3.12+ stdlib)

| Candidate | License/runtime dependencies | Performance/platform fit | Decision |
| --- | --- | --- | --- |
| Direct `open('x')`, write and fsync | PSF, zero dependencies | One file, minimal syscall overhead, but partial output is visible during writing | Rejected (current defect) |
| `tempfile.mkstemp` then `os.replace` | PSF, zero dependencies | Atomic same-filesystem replacement, but silently **overwrites existing packet**; breaks write-once protocol | Rejected |
| Same-directory `tempfile.mkstemp` + fsync + exclusive `os.link` + unlink temp | PSF, zero dependencies | O(bytes) write and O(1) publication; on POSIX/NTFS compatible filesystems destination appears after all data are written; preserves no-overwrite | **Selected** |
| SQLite transactions and private DB | PSF stdlib `sqlite3` (no extra packages) | Strong transaction story but changes human-review artifact format and requires export | Rejected for one small JSONL artifact |

Official primary specs: [Python 3.12 tempfile](https://docs.python.org/3.12/library/tempfile.html), [Python 3.12 os](https://docs.python.org/3.12/library/os.html), [Python pathlib hard links](https://docs.python.org/3/library/pathlib.html).

## Change

- A temporary file is created securely in the destination directory and fully written/fsynced before publication.
- `os.link(temp, destination)` fails with `FileExistsError` if a packet already exists, including under concurrent writers. The temporary name is always cleaned up after a handled failure or success.
- Empty packet publication is rejected; no-query requests fail early. Individual queries without candidates remain permitted so intentional abstention cases are not silently dropped.
- Automated tests simulate link failure and concurrent publishers, checking that no partial final file appears, exactly one complete packet wins, and old packets are not overwritten.

## Limits

Filesystems that do not support hard links fail closed with an OS error; no unsafe overwrite fallback is used. An abrupt process crash can leave a temporary file, but the final destination remains either absent or complete. This is **process-crash publication safety**, not a blanket guarantee of durability against sudden device power loss or hostile directory mutation. Real human evaluation remains pending. End-to-end benchmark latency is not claimed from these synthetic fixtures.

## Verification

Run the blind suite and four-cell CI at the exact post-change commit. If a test fails, fix the underlying issue before any further milestone. The previous verified run must not be reused as evidence for the changed code.
