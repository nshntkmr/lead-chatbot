"""Manage app logins.

    python -m scripts.manage_users add <username> [--name "Display Name"] [--admin]
    python -m scripts.manage_users passwd <username>
    python -m scripts.manage_users remove <username>
    python -m scripts.manage_users list
"""
import argparse
import getpass
import sys

from app import store


def _ask_password() -> str:
    pw = getpass.getpass("Password (min 8 chars): ")
    if len(pw) < 8:
        sys.exit("Password must be at least 8 characters.")
    if getpass.getpass("Repeat password: ") != pw:
        sys.exit("Passwords don't match.")
    return pw


def main() -> None:
    p = argparse.ArgumentParser(description="Manage chatbot users")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add"); a.add_argument("username"); a.add_argument("--name"); a.add_argument("--admin", action="store_true")
    a.add_argument("--password", help="Non-interactive (avoid on shared machines)")
    pw = sub.add_parser("passwd"); pw.add_argument("username"); pw.add_argument("--password")
    r = sub.add_parser("remove"); r.add_argument("username")
    sub.add_parser("list")
    args = p.parse_args()
    store.init()

    if args.cmd == "add":
        store.upsert_user(args.username, args.password or _ask_password(), args.name, args.admin)
        print(f"Saved user '{args.username.lower()}'.")
    elif args.cmd == "passwd":
        existing = {u["username"]: u for u in store.list_users()}
        u = existing.get(args.username.lower())
        if not u:
            sys.exit("No such user.")
        store.upsert_user(u["username"], args.password or _ask_password(), u["display_name"], bool(u["is_admin"]))
        print("Password updated.")
    elif args.cmd == "remove":
        print("Removed." if store.delete_user(args.username) else "No such user.")
    else:
        for u in store.list_users():
            print(f"{u['username']:<24} {u['display_name']:<30} {'admin' if u['is_admin'] else ''}")


if __name__ == "__main__":
    main()
