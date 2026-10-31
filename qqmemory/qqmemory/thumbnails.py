"""Small display copies; the original file remains untouched for the lightbox."""

import re
import os
import tempfile
import threading
from pathlib import Path
from PIL import Image, ImageOps

_lock = threading.Lock()


def thumbnail(source, digest, directory):
    if not re.fullmatch(r"[a-f0-9]{64}", digest or ""):
        return source
    directory = Path(directory)
    target = directory / (digest + "-768-v1.jpg")
    if target.is_file():
        return target
    with _lock:
        if target.is_file():
            return target
        directory.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with Image.open(source) as original:
                image = ImageOps.exif_transpose(original)
                image.thumbnail((768, 768))
                if image.mode != "RGB":
                    rgba = image.convert("RGBA")
                    image = Image.new("RGB", rgba.size, "white")
                    image.paste(rgba, mask=rgba.getchannel("A"))
                fd, temporary = tempfile.mkstemp(prefix=".thumb-", suffix=".jpg", dir=directory)
                os.close(fd)
                image.save(temporary, "JPEG", quality=88)
                os.replace(temporary, target)
                temporary = None
            return target
        except (OSError, ValueError, Image.DecompressionBombError):
            return source
        finally:
            if temporary:
                Path(temporary).unlink(missing_ok=True)
