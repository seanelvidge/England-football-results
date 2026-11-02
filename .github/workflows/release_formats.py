"""Publish verified exports as a release, or check the latest published exports."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from export_formats import DATASETS, EXPORT_FILES, sha256, verify_exports


MANIFEST = "data-manifest.json"
ASSETS = {Path(filename).name: filename for filename in EXPORT_FILES}


def run(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def release_info(repository, tag=None):
    endpoint = f"repos/{repository}/releases/" + (f"tags/{tag}" if tag else "latest")
    result = subprocess.run(["gh", "api", endpoint], capture_output=True, text=True)
    if result.returncode:
        if "HTTP 404" in result.stderr:
            if tag:
                # GitHub's tag endpoint returns published releases only. Drafts
                # are visible to the workflow token through the release list.
                pages = json.loads(run("gh", "api", "--paginate", "--slurp",
                                       f"repos/{repository}/releases?per_page=100"))
                return next((release for page in pages for release in page
                             if release["tag_name"] == tag), None)
            return None
        raise RuntimeError(f"Could not read GitHub release: {result.stderr.strip()}")
    return json.loads(result.stdout)


def source_hashes(root):
    return {f"{name}.csv": sha256(Path(root) / f"{name}.csv") for name in DATASETS}


def prepare_release(root, directory):
    """Validate the local build and describe the exact committed CSV snapshot."""
    root, directory = Path(root), Path(directory)
    commit = run("git", "rev-parse", "HEAD", cwd=root)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Expected a full Git commit SHA")
    files = [f"{name}.csv" for name in DATASETS]
    run("git", "ls-files", "--error-unmatch", "--", *files, cwd=root)
    # Includes staged changes, so the published files cannot silently differ
    # from the commit recorded in the tag and manifest.
    run("git", "diff", "--exit-code", "HEAD", "--", *files, cwd=root)
    verify_exports(root)
    manifest = {
        "format_version": 1,
        "commit": commit,
        "csv_sources": source_hashes(root),
        "assets": {name: {"sha256": sha256(root / path), "bytes": (root / path).stat().st_size}
                   for name, path in ASSETS.items()},
    }
    (directory / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (directory / "notes.md").write_text(
        f"SQLite and Parquet exports of all seven CSV datasets at commit `{commit}`.\n\n"
        "Every exported value and source checksum was checked against that CSV snapshot. "
        "See `data-manifest.json` for the source commit and SHA-256 checksums.\n",
        encoding="utf-8",
    )
    return commit


def check_release(root, repository, info, expected_commit=None):
    """Download one release and compare its checksums and every value to the CSVs."""
    if info is None:
        raise ValueError("No data release exists; run the Nightly BBC Football Results Update first")
    tag = info["tag_name"]
    if not re.fullmatch(r"data-[0-9a-f]{40}", tag):
        raise ValueError(f"Unexpected data release tag: {tag}")
    asset_names = [asset["name"] for asset in info["assets"]]
    expected_assets = set(ASSETS) | {MANIFEST}
    if len(asset_names) != len(expected_assets) or set(asset_names) != expected_assets:
        raise ValueError("Release assets are incomplete or unexpected")
    with tempfile.TemporaryDirectory(prefix="football-release-check-") as temporary:
        stage = Path(temporary)
        run("gh", "release", "download", tag, "--repo", repository, "--dir", str(stage))
        manifest = json.loads((stage / MANIFEST).read_text(encoding="utf-8"))
        if (manifest.get("format_version") != 1 or manifest.get("commit") != tag[5:]
                or (expected_commit is not None and manifest["commit"] != expected_commit)):
            raise ValueError("Release manifest does not identify the expected commit")
        if manifest.get("csv_sources") != source_hashes(root):
            raise ValueError("Published release does not match the current CSV snapshot")
        if set(manifest.get("assets", {})) != set(ASSETS):
            raise ValueError("Release manifest has an incorrect asset list")
        for name, destination in ASSETS.items():
            downloaded = stage / name
            expected = manifest["assets"][name]
            if expected != {"sha256": sha256(downloaded), "bytes": downloaded.stat().st_size}:
                raise ValueError(f"Release checksum or size differs: {name}")
            (stage / destination).parent.mkdir(exist_ok=True)
            downloaded.rename(stage / destination)
        for name in DATASETS:
            shutil.copyfile(Path(root) / f"{name}.csv", stage / f"{name}.csv")
        verify_exports(stage)
    print(f"Verified {tag}: all SQLite and Parquet values match the CSVs.")


def publish_release(root, repository):
    with tempfile.TemporaryDirectory(prefix="football-release-") as temporary:
        directory = Path(temporary)
        commit = prepare_release(root, directory)
        tag = f"data-{commit}"
        info = release_info(repository, tag)
        if info is not None and not info["draft"]:
            # A rerun checks the existing publication instead of overwriting it.
            check_release(root, repository, info, expected_commit=commit)
            print("This commit's data release is already published.")
            return
        if info is None:
            run("gh", "release", "create", tag, "--repo", repository,
                "--target", commit, "--title", f"Football data ({commit[:12]})",
                "--notes-file", str(directory / "notes.md"), "--draft")
        # Retrying an interrupted upload is safe while the release is a draft.
        run("gh", "release", "upload", tag, "--repo", repository, "--clobber",
            *[str(Path(root).resolve() / filename) for filename in EXPORT_FILES],
            str(directory / MANIFEST))
        check_release(root, repository, release_info(repository, tag), expected_commit=commit)
        run("gh", "release", "edit", tag, "--repo", repository, "--draft=false", "--latest")
        print(f"Published https://github.com/{repository}/releases/tag/{tag}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["publish", "check"])
    parser.add_argument("--root-dir", default=".")
    parser.add_argument("--repository", default=os.environ.get("GH_REPO", "seanelvidge/England-football-results"))
    args = parser.parse_args()
    if args.command == "publish":
        publish_release(args.root_dir, args.repository)
    else:
        check_release(args.root_dir, args.repository, release_info(args.repository))


if __name__ == "__main__":
    main()
