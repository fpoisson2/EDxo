from __future__ import annotations

import argparse
import json
import sys
import textwrap
from typing import Any

from src.agent.app_session import AppSession


HELP = """
EDxo Agent CLI

Examples:
  # Login (checks DB password and sets session)
  agent login --username admin --password admin1234

  # Plan de cours: start full generation via Celery
  agent pdc-generate-all --cours-id 123 --session H25 --info "notes..." --model gpt-4o

  # Check task status (generic)
  agent task-status --task-id <uuid>

  # Plan-cadre: trigger generation content (Celery) in 'wand' mode
  agent pc-generate --plan-id 42 --mode wand

  # Plan-cadre: apply improvement (replace all)
  agent pc-apply-replace-all --plan-id 42 --task-id <uuid>

  # Mark current account as profile-complete (bypass welcome redirect)
  agent complete-profile
"""


def ensure_logged(sess: AppSession) -> None:
    if not sess.user_id:
        print("Not logged in. Run: agent login --username ... --password ...", file=sys.stderr)
        sys.exit(2)


def cmd_login(args: argparse.Namespace, sess: AppSession) -> int:
    ok = sess.login_with_password(args.username, args.password)
    if not ok:
        print("Login failed: invalid credentials", file=sys.stderr)
        return 1
    print(f"Logged in as '{args.username}' (user_id={sess.user_id})")
    return 0


def cmd_version(_: argparse.Namespace, sess: AppSession) -> int:
    print(sess.version())
    return 0


def cmd_health(_: argparse.Namespace, sess: AppSession) -> int:
    print(json.dumps(sess.health(), ensure_ascii=False))
    return 0


def cmd_pdc_generate_all(args: argparse.Namespace, sess: AppSession) -> int:
    ensure_logged(sess)
    payload = {
        "cours_id": args.cours_id,
        "session": args.session,
    }
    if args.info:
        payload["additional_info"] = args.info
    if args.model:
        payload["ai_model"] = args.model
    r = sess.post_json("/generate_all_start", payload)
    # route is registered under plan_de_cours_bp at '/generate_all_start'
    if r.status_code == 404:
        # try with blueprint prefix explicitly
        r = sess.post_json("/generate_all_start", payload)
    data = r.get_json() or {}
    print(json.dumps(data, ensure_ascii=False))
    return 0 if data.get("success") else 1


def cmd_task_status(args: argparse.Namespace, sess: AppSession) -> int:
    ensure_logged(sess)
    r = sess.get(f"/task_status/{args.task_id}")
    print(json.dumps(r.get_json() or {}, ensure_ascii=False))
    return 0


def cmd_pc_generate(args: argparse.Namespace, sess: AppSession) -> int:
    ensure_logged(sess)
    # Use 'wand' mode to bypass form validation and let backend decide content scope
    form_data = {
        "mode": args.mode or "wand",
    }
    r = sess.post_form(f"/plan_cadre/{args.plan_id}/generate_content", form_data)
    data = r.get_json() or {}
    print(json.dumps(data, ensure_ascii=False))
    return 0 if data.get("success") else 1


def cmd_pc_apply_replace_all(args: argparse.Namespace, sess: AppSession) -> int:
    ensure_logged(sess)
    # Build a form that replaces all sections with the proposed content
    # based on the server-side expectations in apply_improvement
    form_data = {
        "task_id": args.task_id,
        # Replace lists and capacities entirely
        "action[competences_developpees]": "replace",
        "action[competences_certifiees]": "replace",
        "action[cours_corequis]": "replace",
        "action[cours_prealables]": "replace",
        "action[objets_cibles]": "replace",
        "action[savoirs_etre]": "replace",
        "action[capacites]": "replace",
    }
    # Replace all simple text fields
    simple_fields = [
        "place_intro",
        "objectif_terminal",
        "structure_intro",
        "structure_activites_theoriques",
        "structure_activites_pratiques",
        "structure_activites_prevues",
        "eval_evaluation_sommative",
        "eval_nature_evaluations_sommatives",
        "eval_evaluation_de_la_langue",
        "eval_evaluation_sommatives_apprentissages",
    ]
    for key in simple_fields:
        # Signal acceptance for each field
        # Server expects 'accept_fields_keys' as a list of keys to apply
        pass
    # 'accept_fields_keys' must include all keys to replace
    form_data["accept_fields_keys"] = simple_fields

    r = sess.post_form(f"/plan_cadre/{args.plan_id}/apply_improvement", form_data)
    # The route redirects; success path uses flash + redirect; we can only infer by status code
    ok = 300 <= r.status_code < 400
    print(json.dumps({"redirected": ok, "status": r.status_code}))
    return 0 if ok else 1


def cmd_complete_profile(_: argparse.Namespace, sess: AppSession) -> int:
    ensure_logged(sess)
    ok = sess.complete_profile()
    print(json.dumps({"success": ok, "user_id": sess.user_id}))
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agent",
        description="EDxo in-process agent CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(HELP),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("login", help="Log in using DB username/password")
    sp.add_argument("--username", required=True)
    sp.add_argument("--password", required=True)
    sp.set_defaults(func=cmd_login)

    sp = sub.add_parser("version", help="Show app version")
    sp.set_defaults(func=cmd_version)

    sp = sub.add_parser("health", help="Show app health")
    sp.set_defaults(func=cmd_health)

    sp = sub.add_parser("pdc-generate-all", help="Generate all plan de cours sections (Celery)")
    sp.add_argument("--cours-id", type=int, required=True)
    sp.add_argument("--session", required=True, help="e.g., H25 or A24")
    sp.add_argument("--info", default=None, help="Additional info for the prompt")
    sp.add_argument("--model", default=None, help="Optional model override")
    sp.set_defaults(func=cmd_pdc_generate_all)

    sp = sub.add_parser("task-status", help="Get Celery task status")
    sp.add_argument("--task-id", required=True)
    sp.set_defaults(func=cmd_task_status)

    sp = sub.add_parser("pc-generate", help="Trigger plan-cadre generation (Celery)")
    sp.add_argument("--plan-id", type=int, required=True)
    sp.add_argument("--mode", default="wand", choices=["wand", "improve", "full"], help="Generation mode")
    sp.set_defaults(func=cmd_pc_generate)

    sp = sub.add_parser("pc-apply-replace-all", help="Apply proposed changes to plan-cadre (replace all)")
    sp.add_argument("--plan-id", type=int, required=True)
    sp.add_argument("--task-id", required=True, help="Task id returned by pc-generate")
    sp.set_defaults(func=cmd_pc_apply_replace_all)

    sp = sub.add_parser("complete-profile", help="Mark current user as profile-complete")
    sp.set_defaults(func=cmd_complete_profile)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    sess = AppSession.create(testing=False)
    try:
        return args.func(args, sess)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
