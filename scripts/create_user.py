from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import audit
from app.db import get_conn
from app.repositories import users
from app.security import hash_password, registration_error


def main() -> int:
    ap = argparse.ArgumentParser(description="建立登入帳號")
    ap.add_argument("username")
    ap.add_argument("--password")
    ap.add_argument("--reset", action="store_true", help="帳號已存在時重設密碼")
    args = ap.parse_args()

    username = args.username.strip()
    password = args.password or getpass.getpass("密碼：")
    reason = registration_error(username, password)
    if reason == "username":
        audit.record(
            username=username, ip="local", action="註冊被拒",
            detail={"reason": "username"}, secrets=(password,),
        )
        print("帳號只允許 3 到 32 碼的英數字或底線")
        return 1
    if reason == "password":
        audit.record(
            username=username, ip="local", action="註冊被拒",
            detail={"reason": "password"}, secrets=(password,),
        )
        print("密碼至少 12 碼，而且要同時含英文字母和數字")
        return 1

    with get_conn() as conn:
        existing = users.get_by_username(conn, username)
        if existing:
            if not args.reset:
                audit.record(
                    user_id=existing["id"], username=username, ip="local",
                    action="註冊被拒", detail={"reason": "exists"}, secrets=(password,),
                )
                print(f"帳號 {username} 已存在；要重設密碼請加 --reset")
                return 1
            users.set_password(conn, username, hash_password(password))
            user_id = existing["id"]
            detail = {"reset": True}
            print(f"✅ 已重設 {username} 的密碼")
        else:
            row = users.create_user(conn, username, hash_password(password))
            user_id = row["id"]
            detail = {}
            print(f"✅ 已建立帳號 {row['username']}（id={row['id']}）")
    audit.record(
        user_id=user_id, username=username, ip="local",
        action="建立帳號", detail=detail, secrets=(password,),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
