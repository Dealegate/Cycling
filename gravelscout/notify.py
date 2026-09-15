"""Delivery channels: Telegram and GitHub issues.

Both are optional and configured through environment variables, so the scout
runs perfectly well with neither (it just writes the Markdown report).
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

from .models import Assessment, Listing
from .report import price_str


def _post(url: str, payload: dict, headers: dict | None = None) -> tuple[int, str]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read().decode("utf-8", "replace")[:400]
    except Exception as exc:  # noqa: BLE001 - notification failures must not kill a run
        return 0, str(exc)


# --------------------------------------------------------------------------
# Telegram
# --------------------------------------------------------------------------
def telegram_enabled() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


def telegram_send(listing: Listing, a: Assessment, status: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False
    mark = {"new": "\U0001f195", "price-drop": "\U0001f4c9", "upgraded": "\U0001f504"}.get(status, "")
    spec = ", ".join(b for b in (a.groupset, a.brakes and a.brakes.replace("_", " "),
                                 a.size_label and f"size {a.size_label}") if b)
    text = (f"{mark} <b>{_esc(listing.title)}</b>\n"
            f"{price_str(listing)} — {_esc(listing.location or '?')}\n"
            f"{_esc(spec) or 'spec not stated'}\n"
            f"verdict: {a.verdict} ({a.score}/100)\n"
            f"{listing.url}")
    status_code, _body = _post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        {"chat_id": chat, "text": text, "parse_mode": "HTML",
         "disable_web_page_preview": False})
    return status_code == 200


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def telegram_get(method: str) -> dict:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return {"ok": False, "description": "TELEGRAM_BOT_TOKEN is not set"}
    try:
        with urllib.request.urlopen(
                f"https://api.telegram.org/bot{token}/{method}", timeout=25) as r:
            return json.loads(r.read().decode())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "description": str(exc)}


def telegram_diagnose() -> int:
    """Check the bot credentials and print the chat ids the bot can see.

    Telegram will not tell a bot its own chat ids until somebody writes to it,
    so the flow is: create the bot with @BotFather, send it any message, then
    run this to read the chat id back out of getUpdates.
    """
    me = telegram_get("getMe")
    if not me.get("ok"):
        print(f"getMe failed: {me.get('description')}")
        print("Create a bot by messaging @BotFather, then export the token:")
        print("  export TELEGRAM_BOT_TOKEN=123456:AA...")
        return 2
    bot = me["result"]
    print(f"bot ok: @{bot.get('username')} ({bot.get('first_name')})")

    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not chat_id:
        updates = telegram_get("getUpdates")
        chats = {}
        for u in updates.get("result", []):
            msg = u.get("message") or u.get("channel_post") or {}
            chat = msg.get("chat") or {}
            if chat.get("id"):
                chats[chat["id"]] = chat.get("title") or chat.get("username") or chat.get("first_name")
        if not chats:
            print("TELEGRAM_CHAT_ID is not set and the bot has no messages yet.")
            print(f"Send any message to @{bot.get('username')} in Telegram, then run this again.")
            return 2
        print("Chat ids the bot can see:")
        for cid, name in chats.items():
            print(f"  export TELEGRAM_CHAT_ID={cid}    # {name}")
        return 2

    status, body = _post(f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/sendMessage",
                         {"chat_id": chat_id,
                          "text": "gravelscout is wired up. This is what a hit will look like:\n"
                                  "<b>Liv Devote Advanced 2, vel. S</b>\nEUR 1 500 \u2014 Beograd\n"
                                  "SHIMANO GRX RX600 2x11, hydraulic disc, size S\nverdict: match (100/100)",
                          "parse_mode": "HTML"})
    if status == 200:
        print(f"test message delivered to chat {chat_id}")
        return 0
    print(f"sendMessage failed ({status}): {body}")
    return 2


# --------------------------------------------------------------------------
# GitHub issues - one issue per candidate, so the phone gets a notification and
# there is somewhere to write "messaged the seller" / "sold".
# --------------------------------------------------------------------------
def github_enabled() -> bool:
    return bool(os.getenv("GITHUB_TOKEN") and os.getenv("GITHUB_REPOSITORY"))


def github_issue(listing: Listing, a: Assessment, status: str, body_md: str) -> bool:
    token, repo = os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPOSITORY")
    if not (token and repo):
        return False
    labels = ["candidate", a.verdict]
    if status in ("price-drop", "upgraded"):
        labels.append(status)
    title = f"[{a.score}] {listing.title[:90]} - {price_str(listing)}"
    code, _ = _post(
        f"https://api.github.com/repos/{repo}/issues",
        {"title": title, "body": body_md, "labels": labels},
        {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    return code in (200, 201)


def issue_body(listing: Listing, a: Assessment, status: str) -> str:
    lines = [f"**{listing.url}**", "",
             f"- Status: `{status}` - verdict `{a.verdict}` ({a.score}/100)",
             f"- {price_str(listing)} - {listing.location or 'location unknown'} - source `{listing.source}`"]
    spec = [b for b in (a.bike_type, a.groupset,
                        a.brakes and a.brakes.replace("_", " "), a.bar,
                        a.size_label and f"size {a.size_label}") if b]
    if spec:
        lines.append(f"- Spec read from the ad: {', '.join(spec)}")
    if a.fit:
        g = a.fit.get("geometry") or {}
        lines += [f"- Fit check: **{a.fit['verdict']}** ({g.get('label', '')})"]
        lines += [f"  - {n}" for n in a.fit.get("notes", [])]
    if a.reasons:
        lines += ["", "**Confirmed**"] + [f"- {r}" for r in a.reasons]
    if a.unknowns:
        lines += ["", "**Not stated in the ad - ask the seller**"] + [f"- {u}" for u in a.unknowns]
    if a.todos:
        lines += ["", "**To check**"] + [f"- [ ] {t}" for t in a.todos]
    if listing.images:
        lines += ["", "**Photos**", ""] + [f"<img src=\"{u}\" width=\"320\">" for u in listing.images[:4]]
    if listing.description:
        lines += ["", "<details><summary>Ad text</summary>", "",
                  "```", listing.description[:3000], "```", "", "</details>"]
    return "\n".join(lines)
