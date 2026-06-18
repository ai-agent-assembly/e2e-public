"""Dashboard production smoke checks (AAASM-3154).

Lightweight cross-repo validation that the community web dashboard
(``agent-assembly/dashboard``, Vite + React) still produces a working
*production* build and serves its built static assets. This is a regression
guard for the documented ``pnpm build`` / ``pnpm serve`` paths — **not** a
replacement for the dashboard package's own unit/component tests.

The build it guards is the one that broke in AAASM-3142 (a ``pnpm build``
that exits non-zero during TypeScript checking). By contract a real build
*failure* here is a HARD failure, while a missing toolchain / absent checkout
/ not-opted-in run skips cleanly with a justified reason.
"""
