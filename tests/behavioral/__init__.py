"""Behavioral integration tests for the SDKs' designed contracts.

These tests assert *designed behaviour* of an installed SDK in isolation —
no gateway / core is started. They are distinct from ``tests/live/`` (which
builds and runs a real ``aa-gateway``) and from ``tests/public/`` (which
checks packaging / import surface only).
"""
