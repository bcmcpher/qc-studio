#!/usr/bin/env python
"""Check a multi-user QC-Studio setup and print a summary for the admin.

Examples:
    python check_users_setup.py /data/qc-datasets/qc-raters/users.json --session_list ses-BL
    python check_users_setup.py users.json --session_list ses-BL --create-output-dirs

Exit codes:
    0  at least one rater is ready, and no general errors
       (with --strict: every rater is ready)
    1  some raters are not ready and --strict was given
    2  general error: unreadable config, unsafe identity settings, or no rater ready
"""

import sys
from argparse import ArgumentParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils.user_setup import create_output_dirs, format_report, validate_users_setup  # noqa: E402


def main(argv=None) -> int:
    parser = ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("users_config", help="Path to users.json")
    parser.add_argument("--session_list", default=None, help="The --session_list QC-Studio will be launched with")
    parser.add_argument("--create-output-dirs", action="store_true", help="Create missing output folders for ready raters")
    parser.add_argument("--strict", action="store_true", help="Fail (exit 1) if any rater is not ready")
    parser.add_argument("--quiet", action="store_true", help="Print the summary only on general errors")
    parser.add_argument(
        "--env-file",
        default=str(Path(__file__).resolve().parent.parent / ".env"),
        help="The .env QC-Studio loads (default: repo .env); real environment variables take precedence",
    )
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv(args.env_file)
    except ImportError:
        pass

    report = validate_users_setup(args.users_config, session_list=args.session_list)
    if not args.quiet or report.fatal:
        print(format_report(report))

    if report.fatal:
        if args.create_output_dirs:
            print("\n❌ No output folders were created because of the general error(s) above.")
        return 2
    if args.create_output_dirs:
        created = create_output_dirs(report)
        for d in created:
            print(f"📁 created {d}")
        if not created:
            print("ℹ️  No output folders to create: every ready rater already has one (not-ready raters are skipped).")
    if args.strict and len(report.ready_users) < len(report.users):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
