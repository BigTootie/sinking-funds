"""Shared actions for Flet UI integration tests."""

import asyncio


async def tap(tester, key):
    await tester.tap(await wait_for_key_count(tester, key, 1))
    await tester.pump_and_settle()

async def enter(tester, key, value):
    await tester.enter_text(await wait_for_key_count(tester, key, 1), value)

async def wait_for_key_count(tester, key, count):
    for _ in range(50):
        await tester.pump_and_settle()
        finder = await tester.find_by_key(key)
        if finder.count == count:
            return finder
        await asyncio.sleep(0.05)
    raise AssertionError(f'Expected {key!r} to match {count} controls')
