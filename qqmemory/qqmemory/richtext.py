"""QQ mentions and emoji become text-safe display tokens; original text stays intact."""

import html
import re

TOKEN = re.compile(r"@\{uin:(\d{1,20}),nick:([^{}]*),who:\d+\}|\[em\](e\d{1,8})\[/em\]", re.I)


def tokens(text):
    text = text or ""
    out, offset = [], 0
    for match in TOKEN.finditer(text):
        if match.start() > offset:
            out.append({"type": "text", "text": text[offset : match.start()]})
        if match.group(1):
            out.append({"type": "mention", "uin": match.group(1), "nickname": match.group(2)})
        else:
            out.append({"type": "emoji", "code": match.group(3).lower()})
        offset = match.end()
    if offset < len(text):
        out.append({"type": "text", "text": text[offset:]})
    return out


def person_html(person, prefix=""):
    uin = str(person.get("uin") or "")
    name = person.get("nickname") or uin or "空间好友"
    title = "QQ：" + uin if re.fullmatch(r"\d{1,20}", uin) else "QQ号未取得"
    return (
        '<span class="person" title="'
        + html.escape(title, quote=True)
        + '">'
        + html.escape(prefix + name)
        + "</span>"
    )


def rich_html(text, resolve):
    out = []
    for token in tokens(text):
        if token["type"] == "text":
            out.append(html.escape(token["text"]))
        elif token["type"] == "mention":
            out.append(person_html(token, "@"))
        else:
            relative = resolve(token["code"])
            out.append(
                '<img class="qq-emoji" alt="QQ表情" src="'
                + html.escape(relative, quote=True)
                + '">'
                if relative
                else '<span class="emoji-missing">〔表情〕</span>'
            )
    return "".join(out)
