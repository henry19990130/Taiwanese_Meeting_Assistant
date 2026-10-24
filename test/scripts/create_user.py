from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.db import get_conn
from app.repositories import users
from app.security import hash_password

def main() -> int:
    ap = argparse.ArgumentParser(description="建立登入帳號")
    ap.add_argument("username")
    ap.add_argument("--password")
    ap.add_argument("--reset", action="store_true", help="帳號已存在時重設密碼")
    args = ap.parse_args()

    username = args.username.strip()
    if not 1 <= len(username) <= 100:
        print("帳號長度須為 1–100 字元")
        return 1
    password = args.password or getpass.getpass("密碼：")
    if len(password) < 6:
        print("密碼至少 6 個字元")
        return 1

    with get_conn() as conn:
        if users.get_by_username(conn, username):
            if not args.reset:
                print(f"帳號 {username} 已存在；要重設密碼請加 --reset")
                return 1
            users.set_password(conn, username, hash_password(password))
            print(f"✅ 已重設 {username} 的密碼")
        else:
            row = users.create_user(conn, username, hash_password(password))
            print(f"✅ 已建立帳號 {row['username']}（id={row['id']}）")
    return 0

if __name__ == "__main__":
    sys.exit(main())
