import asyncio

import pytest

from earth_platform.shared.concurrency import KeyedLock


@pytest.mark.asyncio
async def test_canceled_waiter_releases_its_keyed_lock_reference():
    locks: KeyedLock[str] = KeyedLock()

    async with locks.hold("asset"):
        waiter = asyncio.create_task(hold_asset(locks))
        await asyncio.sleep(0)
        assert locks._entries["asset"].users == 2

        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

        assert locks._entries["asset"].users == 1

    assert locks._entries == {}


async def hold_asset(locks: KeyedLock[str]) -> None:
    async with locks.hold("asset"):
        pass
