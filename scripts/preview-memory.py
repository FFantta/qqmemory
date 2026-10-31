from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "qqmemory"))
from qqmemory.mac_app import Controller, create_server

root = Path(__file__).resolve().parent.parent / "qqmemory/local-data"
controller = Controller(root)
server, url, _ = create_server(controller)
print(url, flush=True)
server.serve_forever()
