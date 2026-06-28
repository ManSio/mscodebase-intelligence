"""
Тест как Zed сохраняет файлы.
Следит за изменениями в указанном файле и логирует все события.
"""
import sys
import time
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent, FileDeletedEvent, FileMovedEvent
except ImportError:
    print("watchdog not installed: pip install watchdog")
    sys.exit(1)

class AllEventsHandler(FileSystemEventHandler):
    def on_any_event(self, event):
        event_type = type(event).__name__
        src = event.src_path
        dest = getattr(event, 'dest_path', None)

        if dest:
            logging.info(f"[WATCHER] {event_type}: {src} -> {dest}")
        else:
            logging.info(f"[WATCHER] {event_type}: {src}")

    def on_modified(self, event):
        if not event.is_directory:
            logging.info(f"[WATCHER] MODIFIED: {Path(event.src_path).name}")

    def on_created(self, event):
        if not event.is_directory:
            logging.info(f"[WATCHER] CREATED: {Path(event.src_path).name}")

    def on_deleted(self, event):
        if not event.is_directory:
            logging.info(f"[WATCHER] DELETED: {Path(event.src_path).name}")

    def on_moved(self, event):
        if not event.is_directory:
            logging.info(f"[WATCHER] MOVED: {Path(event.src_path).name} -> {Path(event.dest_path).name}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_zed_save.py <path_to_watch>")
        print("Example: python test_zed_save.py D:/Project/Bot_snow/src")
        sys.exit(1)

    watch_path = Path(sys.argv[1])
    if not watch_path.exists():
        print(f"Path does not exist: {watch_path}")
        sys.exit(1)

    logging.info(f"[WATCHER] Starting to watch: {watch_path}")
    logging.info(f"[WATCHER] Press Ctrl+C to stop")
    logging.info(f"[WATCHER] Now edit and save files in Zed to see events...")

    handler = AllEventsHandler()
    observer = Observer()
    observer.schedule(handler, str(watch_path), recursive=True)
    observer.daemon = True
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("[WATCHER] Stopping...")
        observer.stop()

    observer.join()
    logging.info("[WATCHER] Stopped")
