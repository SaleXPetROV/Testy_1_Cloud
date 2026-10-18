"""Helper: force one economic_tick run (used by test_iter5_* storage-full tests)."""
import asyncio
import os
import sys

sys.path.insert(0, "/app/backend")
import background_tasks  # noqa: E402

asyncio.run(background_tasks.economic_tick())
print("TICK_DONE")
