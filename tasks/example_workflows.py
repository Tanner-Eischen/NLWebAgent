import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from agent.orchestrator import WebAutomationAgent

logging.basicConfig(level=logging.INFO)


async def example_google_search():
    print("\n" + "=" * 60)
    print("EXAMPLE: Google Search")
    print("=" * 60)

    agent = WebAutomationAgent("example_google_search")
    await agent.initialize()

    result = None
    try:
        result = await agent.execute_task(
            task_description="Go to Google and search for 'autonomous agents'",
            start_url="https://www.google.com",
            max_steps=10,
        )
    finally:
        final = await agent.close()
        if final:
            result = final

    if not result:
        return

    print(f"\nStatus: {result['status']}")
    print(f"Steps: {result['steps_taken']}")
    for action in result["actions"]:
        print(
            f"  {action['step']}.{action['attempt']}: {action['action']} ({action['status']})"
        )

    if result.get("errors"):
        print("Errors:")
        for error in result["errors"]:
            print(f"  - {error}")

    if result.get("videos"):
        print("Videos:")
        for video in result["videos"]:
            print(f"  - {video}")


async def example_github():
    print("\n" + "=" * 60)
    print("EXAMPLE: GitHub Navigation")
    print("=" * 60)

    agent = WebAutomationAgent("example_github")
    await agent.initialize()

    result = None
    try:
        result = await agent.execute_task(
            task_description="Go to GitHub trending page",
            start_url="https://github.com/trending",
            max_steps=8,
        )
    finally:
        final = await agent.close()
        if final:
            result = final

    if not result:
        return

    print(f"\nStatus: {result['status']}")
    print(f"Steps: {result['steps_taken']}")

    if result.get("videos"):
        print("Videos:")
        for video in result["videos"]:
            print(f"  - {video}")


async def run_all():
    await example_google_search()
    await asyncio.sleep(2)
    await example_github()


if __name__ == "__main__":
    asyncio.run(run_all())
