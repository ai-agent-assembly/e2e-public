"""Protocol conformance tests for the public Agent Assembly integration suite.

These tests validate observable protocol-contract behavior (verdict resolution,
invalid-input handling, payload shapes, cross-SDK constant parity) using
fixture data under ``tests/fixtures/conformance/``. Product-internal parsing
stays in the owning repos; this suite asserts only the public contract.
"""
