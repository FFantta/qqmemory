"""Stable localhost preview; keeps serving until explicitly stopped."""

from pathlib import Path
from urllib.parse import urlsplit
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "qqmemory"))
from werkzeug.serving import make_server
from werkzeug.wrappers import Response
from qqmemory.mac_app import Controller, create_server, data_root

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=17890)
args = parser.parse_args()
root = data_root()
controller = Controller(root)
_, url, app = create_server(
    controller,
    bind=False,
    token=os.environ.get("QQMEMORY_UI_TOKEN", os.environ.get("SPACE_MEMORY_UI_TOKEN")),
)
private_path = urlsplit(url).path + "?browse=1"


class PreviewRoot:
    def __call__(self, environ, start_response):
        if environ.get("PATH_INFO") == "/" and environ.get("REQUEST_METHOD") == "GET":
            return Response(
                "", status=302, headers={"Location": private_path, "Cache-Control": "no-store"}
            )(environ, start_response)
        return app(environ, start_response)


server = make_server("127.0.0.1", args.port, PreviewRoot(), threaded=True)
print(f"http://127.0.0.1:{args.port}/", flush=True)
server.serve_forever()
