"""Bounded public avatar/emoji preparation; never uses QQ login cookies."""

import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests
from .emoji import get_emoji
from .media import validate_image
from .richtext import tokens


def prepare_assets(posts, directory, seconds=30):
    directory = Path(directory)
    people = set()
    codes = set()
    primary = None
    for post in posts:
        author = str(post.get("author", {}).get("uin") or "")
        if primary is None and re.fullmatch(r"\d{1,20}", author):
            primary = author
        persons = [post.get("author", {})] + post.get("likes", [])
        texts = [post.get("content", "")]
        for comment in post.get("comments", []):
            persons.append(comment)
            persons.extend(comment.get("replies", []))
            texts.append(comment.get("content", ""))
            texts.extend(r.get("content", "") for r in comment.get("replies", []))
        for person in persons:
            uin = str(person.get("uin") or "")
            if re.fullmatch(r"\d{1,20}", uin):
                people.add(uin)
        for text in texts:
            for token in tokens(text):
                if token["type"] == "emoji":
                    codes.add(token["code"])
                elif token["type"] == "mention":
                    people.add(token["uin"])
    deadline = time.monotonic() + seconds

    def fetch(item):
        kind, key = item
        if time.monotonic() >= deadline:
            return
        if kind == "emoji":
            get_emoji(key, directory / "emojis")
            return
        path = directory / "avatars" / (key + ".img")
        if path.is_file():
            return
        try:
            with requests.get(
                "https://q1.qlogo.cn/g",
                params={"b": "qq", "nk": key, "s": 100},
                timeout=(3, 4),
                allow_redirects=False,
                stream=True,
            ) as response:
                response.raise_for_status()
                data = response.raw.read(512 * 1024 + 1)
                if len(data) > 512 * 1024:
                    raise ValueError("Avatar too large")
                validate_image(data)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except (requests.RequestException, OSError, ValueError):
            pass

    # Optional decoration must not make a paused archive wait on hundreds of hosts.
    tasks = (
        ([("avatar", primary)] if primary else [])
        + [("emoji", c) for c in sorted(codes)[:128]]
        + [("avatar", p) for p in sorted(people - {primary})[:63]]
    )
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="export-assets") as pool:
        list(pool.map(fetch, tasks))
