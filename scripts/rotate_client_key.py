#!/usr/bin/env python3
"""API klient kalitini almashtirish (yiliga kamida bir marta tavsiya etiladi).

  .venv/bin/python scripts/rotate_client_key.py --list
  .venv/bin/python scripts/rotate_client_key.py --client-id cli_xxx            # yangi kalit chiqaradi
  .venv/bin/python scripts/rotate_client_key.py --client-id cli_xxx --revoke-old   # yangi kalit + eskilarini bekor qiladi
  .venv/bin/python scripts/rotate_client_key.py --client-id cli_xxx --scopes ask,feedback,review

Yangi kalit faqat bir marta ko'rsatiladi: uni darhol bot .env dagi RAG_API_KEY ga yozing, botni qayta
yarating (scripts/local_up.sh yoki deploy.sh), keyin --revoke-old bilan eskisini o'chiring.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.gateway.clients import get_client_store  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="klientlar va kalitlar ro'yxati")
    ap.add_argument("--client-id")
    ap.add_argument("--revoke-old", action="store_true", help="yangi kalitdan boshqa barcha faol kalitlarni bekor qilish")
    ap.add_argument("--scopes", help="huquqlarni qayta belgilash, masalan: ask,feedback,review")
    args = ap.parse_args()
    store = get_client_store()

    if args.list:
        for c in store.list_clients():
            print(f"{c.client_id}  {c.name}  scopes={','.join(c.scopes)}  active={c.is_active}")
            for k in store.list_keys(c.client_id):
                state = "bekor" if k.revoked_at else "faol"
                print(f"    {k.key_id}  {k.prefix}  {state}")
        return 0
    if not args.client_id:
        ap.error("--client-id yoki --list kerak")

    if args.scopes:
        client = store.update_client(args.client_id, scopes=[s.strip() for s in args.scopes.split(",") if s.strip()])
        print(f"Huquqlar: {','.join(client.scopes)}")
    raw, info = store.issue_key(args.client_id)
    print(f"Yangi kalit ({info.key_id}): {raw}")
    if args.revoke_old:
        revoked = [k.key_id for k in store.list_keys(args.client_id) if k.key_id != info.key_id and not k.revoked_at]
        for key_id in revoked:
            store.revoke_key(key_id)
        print(f"Bekor qilingan eski kalitlar: {len(revoked)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
