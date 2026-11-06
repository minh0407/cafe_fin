# P2: SchemaEditor keeps uncertain commands immutable

The independently reproduced create-book failure committed A, lost its response,
then let the user edit to B and send a new signature/key, creating two books.
SchemaEditor now serializes one exact method/path/body, including request key
and expected version, before sending. A synchronous in-flight guard rejects a
second submission. Transport/unknown outcomes retain that command for an
explicit retry; inputs, column actions, JSON and modal close stay locked.
Recognized definitive validation/conflict rejection releases the editor.

Session generation and open/book epochs fence success/error/finally callbacks.
Actor changes retire and unmount the old editor, clear the command and prevent
cached AntD children or old PATCH props from becoming the next actor's target.
A fresh editor epoch is required. Same-book version refetch does not replace an
uncertain payload. The implementation does not change backend idempotency,
schema revision semantics, import totals or any benchmark engine.

The same component now exposes income_value/expense_value Inputs and collapses
advanced JSON. Values remain explicit user configuration; no direction or
financial meaning is inferred.

Final validation: focused **11/11 PASS in 21.9s**, including real authenticated
SQLite POST/PATCH commit-then-drop-ACK cases. POST leaves one book/version1/schema1;
PATCH leaves one book/version2/schema2. Retry raw body, method/path, key and
expected version match exactly, with one Saved/Closed callback. Other cases cover
definitive rejection, unknown500, local JSON validation, generation/open epochs
and uncertain-PATCH actor retirement. Standard mock **17/17 PASS in 24.5s**;
normal real1000 flow **PASS21.7s** (23.7s total); strict frontend/harness TypeScript
and build PASS. All browser work uses the dedicated test1424 origin adapter.

An earlier normalflow export UI failure remains separately documented in ui.md.
The failed attempt did not capture a raw COMPLETED/null response; its suggested
two-reader race is an inference. The subsequent real flow captured two valid
COMPLETED/file_id responses. This SchemaEditor fix does not claim to repair that
unconfirmed issue, nor does it claim native WebView2/installer acceptance.
