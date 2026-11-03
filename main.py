import argparse
import asyncio
import sys

from app.agent.manus import Manus
from app.logger import logger


def render_console_header() -> None:
    """Render a compact terminal-only interface without changing agent behavior."""
    if not sys.stdout.isatty():
        return
    cyan = "\033[96m"
    violet = "\033[95m"
    dim = "\033[2m"
    reset = "\033[0m"
    print(f"{violet}╔══════════════════════════════════════╗{reset}")
    print(
        f"{violet}║{reset} {cyan}MANUS // SESSION CONSOLE{reset}              {violet}║{reset}"
    )
    print(
        f"{violet}║{reset} {dim}Prompt → run → inspect → report{reset}        {violet}║{reset}"
    )
    print(f"{violet}╚══════════════════════════════════════╝{reset}")


def parse_args() -> argparse.Namespace:
    """Parse local CLI options without treating them as entitlement evidence."""
    parser = argparse.ArgumentParser(description="Run a Manus agent session.")
    parser.add_argument(
        "--export-session-report",
        metavar="PATH",
        help=(
            "Request a Pro Markdown report after this session. It requires an "
            "authenticated account and a configured server subscription verifier."
        ),
    )
    return parser.parse_args()


async def main():
    args = parse_args()
    render_console_header()
    # Create and initialize Manus agent
    agent = await Manus.create()
    try:
        prompt = input("Enter your prompt: ")
        if not prompt.strip():
            logger.warning("Empty prompt provided.")
            return

        logger.warning("Processing your request...")
        await agent.run(prompt)
        logger.info("Request processing completed.")
        if args.export_session_report:
            logger.error(
                "Pro session-report export needs purchase setup: this CLI has no "
                "authenticated account context or configured server entitlement "
                "verifier. No local activation or report file was created."
            )
    except KeyboardInterrupt:
        logger.warning("Operation interrupted.")
    finally:
        # Ensure agent resources are cleaned up before exiting
        await agent.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
