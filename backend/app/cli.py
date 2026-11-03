"""Utilidades de línea de comandos.

Ejemplos:
    python -m app.cli init-db
    python -m app.cli create-user --username admin
    python -m app.cli set-password --username admin
    python -m app.cli list-users
"""

from __future__ import annotations

import argparse
import getpass
import sys

from .auth.users import create_user, init_db, list_users, set_password


def _prompt_password() -> str:
    password = getpass.getpass("Contraseña: ")
    confirm = getpass.getpass("Repetir contraseña: ")
    if password != confirm:
        raise SystemExit("Las contraseñas no coinciden")
    if not password:
        raise SystemExit("La contraseña no puede estar vacía")
    return password


def _resolve_password(args: argparse.Namespace) -> str:
    return args.password if args.password is not None else _prompt_password()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Crea la base de usuarios si no existe")

    create = sub.add_parser("create-user", help="Crea un usuario")
    create.add_argument("--username", required=True)
    create.add_argument("--password", default=None, help="Si se omite, se pide por consola")

    change = sub.add_parser("set-password", help="Cambia la contraseña de un usuario")
    change.add_argument("--username", required=True)
    change.add_argument("--password", default=None, help="Si se omite, se pide por consola")

    sub.add_parser("list-users", help="Lista los usuarios")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "init-db":
            init_db()
            print("Base de datos lista.")
        elif args.command == "create-user":
            create_user(args.username, _resolve_password(args))
            print(f"Usuario '{args.username}' creado.")
        elif args.command == "set-password":
            if not set_password(args.username, _resolve_password(args)):
                print(f"El usuario '{args.username}' no existe.", file=sys.stderr)
                return 1
            print(f"Contraseña actualizada para '{args.username}'.")
        elif args.command == "list-users":
            for username in list_users():
                print(username)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
