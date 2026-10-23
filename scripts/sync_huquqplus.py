#!/usr/bin/env python3
"""
CLI utility for Huquq+ sync operations (usable via cron or manual admin runs).
Usage:
    python scripts/sync_huquqplus.py full
    python scripts/sync_huquqplus.py queue
    python scripts/sync_huquqplus.py status
    python scripts/sync_huquqplus.py relink   # after a Lex.uz corpus rebuild/refresh
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.integrations.huquqplus_sync import full_sync, get_sync_status, process_queue, relink_posts


def cmd_full(args):
    print("Huquq+ to'liq sinxronlash boshlanmoqda...")
    res = asyncio.run(full_sync())
    print("Natija:", json.dumps(res, ensure_ascii=False, indent=2))


def cmd_queue(args):
    print(f"Huquq+ webhook navbati tekshirilmoqda (limit={args.limit})...")
    res = asyncio.run(process_queue(limit=args.limit))
    print("Natija:", json.dumps(res, ensure_ascii=False, indent=2))


def cmd_relink(args):
    from src.api.app import get_store
    res = relink_posts(get_store())
    print("Natija:", json.dumps(res, ensure_ascii=False, indent=2))


def cmd_status(args):
    status = get_sync_status()
    print("=== HUQUQ+ SINXRONLASH HOLATI ===")
    print(f"Faol maqolalar soni: {status['total_active_posts']}")
    print(f"Resolve bo'lmagan havolalar soni: {status['unresolved_refs_count']}")
    print("\nBo'limlar va tillar bo'yicha postlar:")
    for row in status["posts_summary"]:
        print(f"  - [{row['lang'].upper()}] {row['section']} ({row['status']}): {row['cnt']} ta")
    print("\nWebhook navbati holati:", json.dumps(status["queue_stats"], ensure_ascii=False))
    print("\nOxirgi sinxronlash yozuvlari:")
    for run in status["last_runs"]:
        print(f"  #{run['id']} [{run['kind']}] {run['started_at']} -> {run['finished_at'] or 'ishlamoqda'} "
              f"(qo'shildi: {run['added']}, yangilandi: {run['updated']}, o'chirildi: {run['removed']}, xatolar: {run['errors']}): {run['message']}")


def main():
    parser = argparse.ArgumentParser(description="Huquq+ portal sync CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # full
    p_full = subparsers.add_parser("full", help="To'liq sinxronlashni ishga tushirish (uz va ru)")
    p_full.set_defaults(func=cmd_full)

    # queue
    p_queue = subparsers.add_parser("queue", help="Webhook navbatidagi hodisalarni qayta ishlash")
    p_queue.add_argument("--limit", type=int, default=50, help="Qayta ishlanadigan hodisalar soni")
    p_queue.set_defaults(func=cmd_queue)

    # status
    p_status = subparsers.add_parser("status", help="Sinxronlash va navbat holatini ko'rish")
    p_status.set_defaults(func=cmd_status)

    p_relink = subparsers.add_parser("relink", help="Lex.uz havolalarini joriy korpus bo'yicha qayta bog'lash")
    p_relink.set_defaults(func=cmd_relink)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
