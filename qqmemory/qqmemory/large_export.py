"""Disk-backed cloud exports: image bytes never accumulate in a giant string."""

import base64
import html
import os
from pathlib import Path
import re
import zipfile

PART_BYTES = 64 * 1024**2
SINGLE_HTML_BYTES = 16 * 1024**2
IMAGES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def standalone_html(source, destination):
    root = source.parent.resolve()
    document = source.read_text(encoding="utf-8")
    temporary = destination.with_suffix(".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            previous = 0
            for match in re.finditer(r'(src|href)="([^"]+)"', document):
                stream.write(document[previous : match.start()])
                value = html.unescape(match.group(2))
                if value.startswith(("data:", "#")):
                    stream.write(match.group(0))
                else:
                    target = (root / value).resolve()
                    mime = IMAGES.get(target.suffix.lower())
                    if not target.is_relative_to(root) or not target.is_file() or not mime:
                        raise ValueError("Invalid exported image")
                    stream.write(match.group(1) + '="data:' + mime + ";base64,")
                    with target.open("rb") as image:
                        while data := image.read(
                            57 * 1024
                        ):  # multiple of three: no intermediate padding
                            stream.write(base64.b64encode(data).decode("ascii"))
                    stream.write('"')
                previous = match.end()
            stream.write(document[previous:])
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def bundle_exports(
    source, directory, part_bytes=PART_BYTES, single_html_bytes=SINGLE_HTML_BYTES, progress=None
):
    """Each ZIP part is independently valid; merge their common folder for offline use."""
    progress = progress or (lambda _: None)
    root = source.parent.resolve()
    directory.mkdir(parents=True)
    paths = sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink())
    images = [p for p in paths if p.suffix.lower() in IMAGES]
    metadata = [p for p in paths if p not in images]
    parts, group, size = [], [], 0
    groups = []
    for path in images:
        count = path.stat().st_size
        if group and size + count > part_bytes:
            groups.append(group)
            group = []
            size = 0
        group.append(path)
        size += count
    if group or not groups:
        groups.append(group)
    instructions = "第1包包含index.html、首批图片及其他/中的报告；其余包为后续图片，大小不同是正常分包。请全部下载。将所有 ZIP 解压，合并其中同名的“空间记忆”文件夹及 media 子目录，再打开 index.html。请保留全部分包；仅下载一个分包时图片不完整。Mac 解压若生成多个同名编号文件夹，请将各包的 media 内容合并到第一包的 media 中。\n"
    for index, group in enumerate(groups, 1):
        filename = f"part-{index:03d}.zip"
        path = directory / filename
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            if index == 1:
                for p in metadata:
                    relative = p.relative_to(root).as_posix()
                    archive.write(
                        p, "空间记忆/" + (relative if p == source.resolve() else "其他/" + relative)
                    )
                archive.writestr("空间记忆/其他/分包使用说明.txt", instructions)
            for p in group:
                archive.write(p, "空间记忆/" + p.relative_to(root).as_posix())
        parts.append(dict(kind=f"part-{index:03d}", file=filename, size=path.stat().st_size))
        progress(f"已生成图片包 {index}/{len(groups)}")
    inline = sum(p.stat().st_size for p in images) <= single_html_bytes
    if inline:
        standalone_html(source, directory / "空间记忆.html")
    return parts, inline
