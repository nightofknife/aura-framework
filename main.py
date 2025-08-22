# main.py (New API-driven version)

import sys
import asyncio
import threading
import tkinter as tk
import uvicorn
import argparse
from pathlib import Path

# --- Path Setup (same as before) ---
try:
    base_path = Path(sys._MEIPASS)
except AttributeError:
    base_path = Path(__file__).resolve().parent

if str(base_path) not in sys.path:
    sys.path.insert(0, str(base_path))

# --- Core Imports ---
from packages.aura_shared_utils.utils.logger import logger
from packages.aura_core.scheduler import Scheduler
from packages.aura_core.api import service_registry

# --- API and UI Imports ---
from api_server import app as fastapi_app
from api_server import get_scheduler_instance # Import the dependency function


def run_tkinter_ui(scheduler: Scheduler):
    """
    This function contains the logic to launch the legacy Tkinter UI.
    It runs in a separate thread to avoid blocking the main asyncio event loop.
    """
    logger.info("UI Thread: Initializing Tkinter UI...")
    try:
        # The original logic from AuraApplication._launch_ui()
        ui_launcher = service_registry.get_service_instance("ui_launcher")
        # This call will block this thread until the UI window is closed.
        ui_launcher.launch(scheduler)
        logger.info("UI Thread: Aura IDE has been closed.")
    except Exception as e:
        logger.error(f"UI Thread: Failed to launch UI: {e}", exc_info=True)
        # Optionally show an error dialog if Tkinter is available
        try:
            import tkinter.messagebox as messagebox
            temp_root = tk.Tk()
            temp_root.withdraw()
            messagebox.showerror("UI Error", f"Failed to launch the UI:\n\n{e}")
            temp_root.destroy()
        except Exception:
            pass


async def main(launch_ui: bool):
    """
    The new asynchronous main entry point for the Aura application.
    It orchestrates the startup of the Scheduler, the API server, and optionally the UI.
    """
    logger.info("Initializing Aura Core...")
    scheduler = Scheduler()

    # --- API Server Setup ---
    # This is the crucial step for dependency injection. We tell FastAPI that
    # whenever a route asks for `get_scheduler_instance`, it should be given
    # our live `scheduler` object.
    fastapi_app.dependency_overrides[get_scheduler_instance] = lambda: scheduler

    # Configure the Uvicorn server to run our FastAPI app.
    config = uvicorn.Config(fastapi_app, host="127.0.0.1", port=8000, log_level="info")
    server = uvicorn.Server(config)

    # --- Optional UI Setup ---
    if launch_ui:
        logger.info("UI flag detected. Launching Tkinter UI in a separate thread...")
        # The UI must run in its own thread because its mainloop is blocking.
        ui_thread = threading.Thread(target=run_tkinter_ui, args=(scheduler,), daemon=True)
        ui_thread.start()

    # --- Run Core Services Concurrently ---
    logger.info("Starting Aura Scheduler and API Server...")
    try:
        # Create tasks for the scheduler's main loop and the API server's loop.
        scheduler_task = asyncio.create_task(scheduler.run())
        server_task = asyncio.create_task(server.serve())

        # `asyncio.gather` runs both tasks concurrently. The application will
        # keep running until one of them exits or is cancelled (e.g., by Ctrl+C).
        await asyncio.gather(scheduler_task, server_task)

    finally:
        logger.info("Main loop is shutting down. Stopping scheduler...")
        # This ensures that even if the server crashes, we try to stop the scheduler.
        if scheduler.is_running.is_set():
            scheduler.stop_scheduler()
        logger.info("Aura services have been shut down.")


if __name__ == "__main__":
    # --- Command-line Argument Parsing ---
    parser = argparse.ArgumentParser(description="Run the Aura Automation Framework.")
    parser.add_argument(
        "--ui",
        action="store_true",
        help="Launch the legacy Tkinter desktop UI alongside the server."
    )
    args = parser.parse_args()

    try:
        # Start the main asynchronous event loop.
        asyncio.run(main(launch_ui=args.ui))
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutdown requested by user (Ctrl+C).")

