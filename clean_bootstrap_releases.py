#!/usr/bin/env python3
"""
Clean up old Atlas Bootstrap release tags.
Keeps only the latest 3 releases and deletes all older tags.
"""

import subprocess
import sys
import re
import argparse
from typing import List, Tuple


def run_cmd(cmd: List[str], check: bool = True) -> Tuple[str, int]:
    """Run a command and return stdout and exit code."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=check
        )
        return result.stdout.strip(), result.returncode
    except subprocess.CalledProcessError as e:
        return e.stdout.strip() + "\n" + e.stderr.strip(), e.returncode


def get_all_tags() -> List[str]:
    """Get all version tags from the repository."""
    stdout, _ = run_cmd(["git", "tag", "--sort=-version:refname"], check=False)
    tags = [tag.strip() for tag in stdout.split("\n") if tag.strip()]
    # Filter to only version tags (vX.Y.Z format)
    version_tags = [tag for tag in tags if re.match(r"^v\d+\.\d+\.\d+$", tag)]
    return version_tags


def parse_version(tag: str) -> Tuple[int, int, int]:
    """Parse version tag into tuple for comparison."""
    match = re.match(r"^v(\d+)\.(\d+)\.(\d+)$", tag)
    if not match:
        raise ValueError(f"Invalid version tag: {tag}")
    return tuple(map(int, match.groups()))


def delete_tag_local(tag: str) -> bool:
    """Delete tag locally."""
    print(f"  Deleting local tag: {tag}")
    _, exit_code = run_cmd(["git", "tag", "-d", tag], check=False)
    return exit_code == 0


def delete_tag_remote(tag: str) -> bool:
    """Delete tag from remote."""
    print(f"  Deleting remote tag: {tag}")
    _, exit_code = run_cmd(
        ["git", "push", "origin", ":refs/tags/" + tag], check=False
    )
    return exit_code == 0


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Clean up old Atlas Bootstrap release tags"
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt and delete automatically",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Atlas Bootstrap Release Tag Cleanup")
    print("=" * 60)
    print()

    # Get all version tags
    print("Fetching all version tags...")
    all_tags = get_all_tags()
    print(f"Found {len(all_tags)} version tags: {', '.join(all_tags)}")
    print()

    if len(all_tags) <= 3:
        print(f"Only {len(all_tags)} tags found. Keeping all (minimum 3 to keep).")
        return 0

    # Sort by version (already sorted by git, but ensure it)
    all_tags.sort(key=parse_version, reverse=True)

    # Keep latest 3
    tags_to_keep = all_tags[:3]
    tags_to_delete = all_tags[3:]

    print(f"Keeping latest 3 releases: {', '.join(tags_to_keep)}")
    print(f"Deleting {len(tags_to_delete)} old releases: {', '.join(tags_to_delete)}")
    print()

    if not tags_to_delete:
        print("No tags to delete.")
        return 0

    # Confirm deletion
    if not args.yes:
        print("=" * 60)
        print("WARNING: This will delete tags from both local and remote!")
        print("=" * 60)
        try:
            response = input("Continue? (yes/no): ").strip().lower()
            if response != "yes":
                print("Aborted.")
                return 1
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return 1
    else:
        print("=" * 60)
        print("WARNING: Deleting tags from both local and remote (--yes flag set)")
        print("=" * 60)

    print()
    print("Deleting tags...")
    print("-" * 60)

    deleted_count = 0
    failed_count = 0

    for tag in tags_to_delete:
        print(f"\nProcessing: {tag}")
        local_ok = delete_tag_local(tag)
        remote_ok = delete_tag_remote(tag)

        if local_ok and remote_ok:
            print(f"  ✅ Successfully deleted {tag}")
            deleted_count += 1
        else:
            print(f"  ❌ Failed to delete {tag} (local: {local_ok}, remote: {remote_ok})")
            failed_count += 1

    print()
    print("=" * 60)
    print("Cleanup Summary")
    print("=" * 60)
    print(f"Tags kept: {len(tags_to_keep)}")
    print(f"Tags deleted: {deleted_count}")
    print(f"Tags failed: {failed_count}")
    print()
    print(f"Remaining tags: {', '.join(tags_to_keep)}")
    print("=" * 60)

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

