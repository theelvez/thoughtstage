# Review target

Decide whether `submission.py` is safe to ship unchanged. The function receives a
DB-API 2.0 compatible database connection and a username supplied by an
authenticated but otherwise untrusted user.

Requirements:

1. Treat `username` as untrusted input.
2. Return the matching user's `id`, `username`, and `email`, or `None`.
3. Do not expose additional columns or log credentials.
4. A blocking security vulnerability requires rejection.
5. Approval applies to the exact recorded file. Promised future remediation does
   not make the current submission approvable.
