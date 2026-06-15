"""Smoke tests for the Agent Assembly Node.js/TypeScript SDK."""

from __future__ import annotations

import subprocess
import textwrap

import pytest

from tests.public.conftest import skip_if_binary_missing

COMPONENT = "node-sdk"
PACKAGE = "@agent-assembly/sdk"

_ESM_SMOKE = textwrap.dedent("""\
    import { initAssembly, ENFORCEMENT_MODES } from '@agent-assembly/sdk';
    const hasInit = typeof initAssembly === 'function';
    const hasModes = typeof ENFORCEMENT_MODES === 'object' && ENFORCEMENT_MODES !== null;
    if (!hasInit || !hasModes) {
      const msg = `[${COMPONENT}] unexpected exports: initAssembly=${typeof initAssembly} `
        + `ENFORCEMENT_MODES=${typeof ENFORCEMENT_MODES}\\n`;
      process.stderr.write(msg);
      process.exit(1);
    }
    console.log('ok');
""".replace("${COMPONENT}", COMPONENT))


def _node_has_package() -> bool:
    """Return True when @agent-assembly/sdk can be resolved by node."""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", f"import '{PACKAGE}'"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


@pytest.mark.sdk
def test_node_sdk_importable() -> None:
    """@agent-assembly/sdk can be imported via ESM."""
    skip_if_binary_missing("node")
    if not _node_has_package():
        pytest.skip(f"npm package {PACKAGE!r} not installed — run 'npm install {PACKAGE}'")


@pytest.mark.sdk
def test_node_sdk_public_exports() -> None:
    """initAssembly and ENFORCEMENT_MODES are exported from the package."""
    skip_if_binary_missing("node")
    if not _node_has_package():
        pytest.skip(f"npm package {PACKAGE!r} not installed — run 'npm install {PACKAGE}'")

    result = subprocess.run(
        ["node", "--input-type=module", "-e", _ESM_SMOKE],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"[{COMPONENT}] ESM smoke failed (exit {result.returncode})\n"
        f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
    )
    assert "ok" in result.stdout, (
        f"[{COMPONENT}] Expected 'ok' in output, got: {result.stdout.strip()!r}"
    )


# Functional-install check: from the installed package, assert `initAssembly`
# is callable and `ENFORCEMENT_MODES` is exactly the expected set of modes.
# `ENFORCEMENT_MODES` is a readonly array (["enforce", "observe", "disabled"]),
# so we compare against the canonical value rather than only its `typeof`.
_FUNCTIONAL_SMOKE = textwrap.dedent("""\
    import { initAssembly, ENFORCEMENT_MODES } from '@agent-assembly/sdk';

    const EXPECTED = ['enforce', 'observe', 'disabled'];
    const errors = [];

    if (typeof initAssembly !== 'function') {
      errors.push(`initAssembly is ${typeof initAssembly}, expected function`);
    }
    if (!Array.isArray(ENFORCEMENT_MODES)
        || ENFORCEMENT_MODES.length !== EXPECTED.length
        || !EXPECTED.every((m, i) => ENFORCEMENT_MODES[i] === m)) {
      errors.push(`ENFORCEMENT_MODES is ${JSON.stringify(ENFORCEMENT_MODES)}, `
        + `expected ${JSON.stringify(EXPECTED)}`);
    }

    if (errors.length > 0) {
      process.stderr.write(`[${COMPONENT}] ${errors.join('; ')}\\n`);
      process.exit(1);
    }
    console.log('ok');
""".replace("${COMPONENT}", COMPONENT))


@pytest.mark.sdk
def test_node_sdk_functional_install() -> None:
    """Installed package exposes a callable initAssembly and canonical modes."""
    skip_if_binary_missing("node")
    if not _node_has_package():
        pytest.skip(f"npm package {PACKAGE!r} not installed — run 'npm install {PACKAGE}'")

    result = subprocess.run(
        ["node", "--input-type=module", "-e", _FUNCTIONAL_SMOKE],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"[{COMPONENT}] functional install check failed (exit {result.returncode})\n"
        f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
    )
    assert "ok" in result.stdout, (
        f"[{COMPONENT}] Expected 'ok' in output, got: {result.stdout.strip()!r}"
    )


# Load the napi native addon from the *installed* package. The package `exports`
# map deliberately does not expose `./package.json` or the `./native/...` paths
# (see AAASM-2968), so we cannot `import '@agent-assembly/sdk/native/...'` nor
# `require('@agent-assembly/sdk/package.json')`. Instead we resolve the package
# main entry (which honours the exports map), walk up to the package root, and
# require `native/aa-ffi-node/index.cjs` from disk — exactly how the SDK's own
# loader (`src/native/client.ts`) reaches the addon. The loaded binding must
# expose the napi surface (`connect`, `sendEvent`, `disconnect`).
_NATIVE_ADDON_SMOKE = textwrap.dedent("""\
    import { createRequire } from 'node:module';
    import { fileURLToPath, pathToFileURL } from 'node:url';
    import path from 'node:path';
    import fs from 'node:fs';

    const PACKAGE = '@agent-assembly/sdk';
    const require = createRequire(pathToFileURL(path.join(process.cwd(), 'package.json')));

    // Resolve the package main entry (honours the exports map), then walk up to
    // the directory whose package.json declares our package name.
    const entry = fileURLToPath(import.meta.resolve(PACKAGE));
    let dir = path.dirname(entry);
    let pkgRoot = null;
    while (dir !== path.dirname(dir)) {
      const pj = path.join(dir, 'package.json');
      if (fs.existsSync(pj)) {
        const name = JSON.parse(fs.readFileSync(pj, 'utf8')).name;
        if (name === PACKAGE) { pkgRoot = dir; break; }
      }
      dir = path.dirname(dir);
    }
    if (!pkgRoot) {
      process.stderr.write(`[${COMPONENT}] could not locate package root for ${PACKAGE}\\n`);
      process.exit(1);
    }

    // The napi addon is shipped under native/aa-ffi-node/ (per the package
    // `files` allow-list): index.cjs is the loader, *.node is the binary.
    const nativeCjs = path.join(pkgRoot, 'native', 'aa-ffi-node', 'index.cjs');
    if (!fs.existsSync(nativeCjs)) {
      process.stderr.write(`[${COMPONENT}] native loader missing: ${nativeCjs}\\n`);
      process.exit(1);
    }

    // index.cjs resolves and requires the platform .node addon; a successful
    // require means the native binary actually loaded into the process.
    const binding = require(nativeCjs);
    const surface = ['connect', 'sendEvent', 'disconnect'];
    const missing = surface.filter((fn) => typeof binding[fn] !== 'function');
    if (missing.length > 0) {
      process.stderr.write(`[${COMPONENT}] native binding missing fns: ${missing.join(', ')}\\n`);
      process.exit(1);
    }
    console.log('ok');
""".replace("${COMPONENT}", COMPONENT))


@pytest.mark.sdk
def test_node_sdk_native_addon_loads() -> None:
    """The napi native addon resolves and loads from the installed package.

    Goes beyond the JS-only smoke: locates the package root via the exports
    map, requires the shipped native loader, and asserts the napi binding
    (connect/sendEvent/disconnect) is actually loaded into the process.
    """
    skip_if_binary_missing("node")
    if not _node_has_package():
        pytest.skip(f"npm package {PACKAGE!r} not installed — run 'npm install {PACKAGE}'")

    result = subprocess.run(
        ["node", "--input-type=module", "-e", _NATIVE_ADDON_SMOKE],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"[{COMPONENT}] native addon load failed (exit {result.returncode})\n"
        f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
    )
    assert "ok" in result.stdout, (
        f"[{COMPONENT}] Expected 'ok' in output, got: {result.stdout.strip()!r}"
    )
