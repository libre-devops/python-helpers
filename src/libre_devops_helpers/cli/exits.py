"""Exit codes, the same for every command, so scripts can branch on them."""

OK = 0
# An error, or a token check that failed.
ERROR = 1
# A usage error (bad option or argument); Click uses this code itself.
USAGE = 2
# The command ran, but found something that needs attention: a device missing or not in
# the expected state, or a credential or secret close to expiry.
ATTENTION = 3
# Stopped with Ctrl-C.
INTERRUPTED = 130
