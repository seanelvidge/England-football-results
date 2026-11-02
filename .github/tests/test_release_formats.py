"""Release snapshot identity, download integrity, publication and retention."""
from contextlib import redirect_stdout
import csv
import io
from itertools import islice
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".github/workflows"))
import export_formats as exports
import release_formats as releases


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.remote = self.root / "release-assets"
        self.remote.mkdir()
        self.quiet = redirect_stdout(io.StringIO())
        self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__, None, None, None)
        for name in exports.DATASETS:
            with (ROOT / f"{name}.csv").open(encoding="utf-8-sig", newline="") as handle:
                rows = list(islice(csv.reader(handle), 4))
            with (self.root / f"{name}.csv").open("w", encoding="utf-8", newline="") as handle:
                csv.writer(handle).writerows(rows)
        releases.run("git", "init", "-q", cwd=self.root)
        releases.run("git", "add", "--", *[f"{name}.csv" for name in exports.DATASETS], cwd=self.root)
        releases.run("git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                     "-c", "commit.gpgsign=false", "commit", "-qm", "CSV snapshot", cwd=self.root)
        exports.export_formats(self.root)
        self.commit = releases.prepare_release(self.root, self.remote)
        for name, path in releases.ASSETS.items():
            shutil.copyfile(self.root / path, self.remote / name)
        self.commands = []
        self.real_run = releases.run

    def info(self, draft=False):
        return {"tag_name": f"data-{self.commit}", "draft": draft,
                "assets": [{"name": name} for name in [*releases.ASSETS, releases.MANIFEST]]}

    def gh(self, *args, **kwargs):
        if args[0] != "gh":
            return self.real_run(*args, **kwargs)
        self.commands.append(args)
        if args[1] == "api":
            if args[2:4] == ("--method", "DELETE"):
                return ""
            if "/git/matching-refs/" in args[-1]:
                return json.dumps([[{"ref": f"refs/tags/data-{sha}"}
                                    for sha in (self.commit, "0" * 40)]])
            return json.dumps([[self.info()], [{"tag_name": "data-" + "0" * 40}]])
        operation = args[2]
        if operation == "download":
            target = Path(args[args.index("--dir") + 1])
            for name in [*releases.ASSETS, releases.MANIFEST]:
                shutil.copyfile(self.remote / name, target / name)
        elif operation == "upload":
            for filename in args[args.index("--clobber") + 1:]:
                shutil.copyfile(filename, self.remote / Path(filename).name)
        elif operation not in {"create", "edit", "delete"}:
            self.fail(f"Unexpected GitHub command: {args}")
        return ""

    def operations(self):
        return [args[2] if args[1] == "release" else
                "delete-tag" if args[2:4] == ("--method", "DELETE") else "list"
                for args in self.commands]

    def edit_manifest(self, transform):
        path = self.remote / releases.MANIFEST
        manifest = json.loads(path.read_text())
        transform(manifest)
        path.write_text(json.dumps(manifest))

    def test_manifest_identifies_committed_csvs_and_all_assets(self):
        manifest = json.loads((self.remote / releases.MANIFEST).read_text())
        self.assertEqual(manifest["commit"], self.commit)
        self.assertEqual(manifest["csv_sources"], releases.source_hashes(self.root))
        self.assertEqual(set(manifest["assets"]), set(releases.ASSETS))

    def test_uncommitted_and_staged_csv_changes_block_publication(self):
        path = self.root / "EnglishTeamLogos.csv"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaises(subprocess.CalledProcessError):
            releases.prepare_release(self.root, self.remote)
        releases.run("git", "add", path.name, cwd=self.root)
        with self.assertRaises(subprocess.CalledProcessError):
            releases.prepare_release(self.root, self.remote)

    def test_complete_download_is_checked_without_replacing_local_files(self):
        before = {path: (self.root / path).read_bytes() for path in exports.EXPORT_FILES}
        with patch.object(releases, "run", side_effect=self.gh):
            releases.check_release(self.root, "example/repo", self.info())
        self.assertEqual(before, {path: (self.root / path).read_bytes() for path in exports.EXPORT_FILES})

    def test_missing_asset_blocks_download(self):
        info = self.info()
        info["assets"].pop()
        with patch.object(releases, "run") as command, self.assertRaisesRegex(ValueError, "assets"):
            releases.check_release(self.root, "example/repo", info)
        command.assert_not_called()

    def test_wrong_csv_snapshot_and_commit_are_rejected(self):
        self.edit_manifest(lambda m: m["csv_sources"].update({"EnglandLeagueResults.csv": "wrong"}))
        with patch.object(releases, "run", side_effect=self.gh), self.assertRaisesRegex(ValueError, "CSV snapshot"):
            releases.check_release(self.root, "example/repo", self.info())
        self.edit_manifest(lambda m: m.update(commit="0" * 40))
        with patch.object(releases, "run", side_effect=self.gh), self.assertRaisesRegex(ValueError, "commit"):
            releases.check_release(self.root, "example/repo", self.info())

    def test_corrupt_download_is_rejected(self):
        path = self.remote / "EnglandFootball.sqlite"
        path.write_bytes(path.read_bytes() + b"corrupt")
        with patch.object(releases, "run", side_effect=self.gh), self.assertRaisesRegex(ValueError, "checksum"):
            releases.check_release(self.root, "example/repo", self.info())

    def test_checks_values_even_if_release_checksum_matches_corruption(self):
        path = self.remote / "EnglandFootball.sqlite"
        connection = sqlite3.connect(path)
        try:
            with connection:
                connection.execute("UPDATE EnglandLeagueResults SET Score = '9-9' WHERE rowid = 1")
        finally:
            connection.close()
        self.edit_manifest(lambda m: m["assets"][path.name].update(sha256=exports.sha256(path)))
        with patch.object(releases, "run", side_effect=self.gh), self.assertRaisesRegex(ValueError, "SQLite values"):
            releases.check_release(self.root, "example/repo", self.info())

    def test_new_release_is_checked_before_becoming_public(self):
        with patch.object(releases, "release_info", side_effect=[None, self.info(draft=True), self.info()]), patch.object(releases, "run", side_effect=self.gh):
            releases.publish_release(self.root, "example/repo")
        self.assertEqual(self.operations(), ["create", "upload", "download", "edit", "list", "list", "delete", "delete-tag"])
        self.assertIn("--draft", self.commands[0])
        self.assertIn("--draft=false", self.commands[3])
        self.assertIn(self.commit, self.commands[0])

    def test_interrupted_draft_can_be_retried(self):
        with patch.object(releases, "release_info", side_effect=[self.info(draft=True), self.info(draft=True), self.info()]), patch.object(releases, "run", side_effect=self.gh):
            releases.publish_release(self.root, "example/repo")
        self.assertEqual(self.operations(), ["upload", "download", "edit", "list", "list", "delete", "delete-tag"])

    def test_published_rerun_checks_and_retries_cleanup_without_overwriting(self):
        with patch.object(releases, "release_info", return_value=self.info()), patch.object(releases, "run", side_effect=self.gh):
            releases.publish_release(self.root, "example/repo")
        self.assertEqual(self.operations(), ["download", "list", "list", "delete", "delete-tag"])

    def test_failed_verification_keeps_release_unpublished(self):
        with patch.object(releases, "release_info", return_value=self.info(draft=True)), patch.object(releases, "run", side_effect=self.gh), patch.object(releases, "check_release", side_effect=ValueError("Failed verification")), self.assertRaisesRegex(ValueError, "Failed verification"):
            releases.publish_release(self.root, "example/repo")
        self.assertEqual(self.operations(), ["upload"])

    def test_failed_upload_or_publication_never_removes_previous_release(self):
        for failure in ("upload", "edit"):
            with self.subTest(failure=failure):
                self.commands.clear()

                def failing_gh(*args, **kwargs):
                    result = self.gh(*args, **kwargs)
                    if args[:3] == ("gh", "release", failure):
                        raise subprocess.CalledProcessError(1, args, stderr="HTTP 500")
                    return result

                with patch.object(releases, "release_info", return_value=self.info(draft=True)), patch.object(releases, "run", side_effect=failing_gh), self.assertRaises(subprocess.CalledProcessError):
                    releases.publish_release(self.root, "example/repo")
                self.assertNotIn("delete", self.operations())
                self.assertNotIn("delete-tag", self.operations())

    def test_failed_verification_of_published_rerun_never_removes_previous_release(self):
        path = self.remote / "EnglandFootball.sqlite"
        path.write_bytes(path.read_bytes() + b"corrupt")
        with patch.object(releases, "release_info", return_value=self.info()), patch.object(releases, "run", side_effect=self.gh), self.assertRaisesRegex(ValueError, "checksum"):
            releases.publish_release(self.root, "example/repo")
        self.assertEqual(self.operations(), ["download"])

    def test_api_errors_are_not_mistaken_for_a_missing_release(self):
        with patch.object(releases.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "HTTP 500")), self.assertRaises(RuntimeError):
            releases.release_info("example/repo")
        with patch.object(releases.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "HTTP 404")):
            self.assertIsNone(releases.release_info("example/repo"))

    def test_draft_is_found_in_release_list_when_tag_endpoint_returns_404(self):
        draft = self.info(draft=True)
        responses = [subprocess.CompletedProcess([], 1, "", "HTTP 404"),
                     subprocess.CompletedProcess([], 0, json.dumps([[], [draft]]), "")]
        with patch.object(releases.subprocess, "run", side_effect=responses):
            self.assertEqual(releases.release_info("example/repo", draft["tag_name"]), draft)

    def test_missing_tag_is_absent_from_published_and_draft_releases(self):
        responses = [subprocess.CompletedProcess([], 1, "", "HTTP 404"),
                     subprocess.CompletedProcess([], 0, json.dumps([[self.info(draft=True)]]), "")]
        with patch.object(releases.subprocess, "run", side_effect=responses):
            self.assertIsNone(releases.release_info("example/repo", "data-" + "0" * 40))


class ReleaseRetentionTests(unittest.TestCase):
    def setUp(self):
        self.keep = "data-" + "a" * 40
        self.old = "data-" + "b" * 40
        self.draft = "data-" + "c" * 40
        self.latest = {"tag_name": self.keep, "draft": False}
        self.quiet = redirect_stdout(io.StringIO())
        self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__, None, None, None)

    def test_removes_old_data_releases_and_drafts_across_all_pages(self):
        pages = [[self.latest, {"tag_name": "v1.0"}, {"tag_name": self.old, "draft": False}],
                 [{"tag_name": "data-example"}, {"tag_name": self.draft, "draft": True},
                  {"tag_name": self.keep + "-notes"}]]
        # The draft has no Git tag. Prefix matches that are not exact data tags
        # must be preserved even when GitHub returns them from matching-refs.
        refs = [[{"ref": f"refs/tags/{self.keep}"}],
                [{"ref": f"refs/tags/{self.old}"}, {"ref": "refs/tags/data-example"},
                 {"ref": f"refs/tags/{self.keep}-notes"}]]
        with patch.object(releases, "run", side_effect=[json.dumps(pages), json.dumps(refs), "", "", ""]) as command, patch.object(releases, "release_info", return_value=self.latest):
            releases.prune_old_releases("example/repo", self.keep)
        self.assertIn("--paginate", command.call_args_list[0].args)
        self.assertIn("--paginate", command.call_args_list[1].args)
        self.assertEqual([call.args for call in command.call_args_list[2:4]], [
            ("gh", "release", "delete", tag, "--repo", "example/repo", "--yes")
            for tag in (self.old, self.draft)
        ])
        self.assertEqual(command.call_args_list[-1].args, (
            "gh", "api", "--method", "DELETE", f"repos/example/repo/git/refs/tags/{self.old}"))

    def test_missing_draft_or_superseded_replacement_prevents_all_deletions(self):
        for latest in (None, {"tag_name": self.keep, "draft": True},
                       {"tag_name": self.old, "draft": False}):
            with self.subTest(latest=latest), patch.object(releases, "list_releases", return_value=[{"tag_name": self.old}]), patch.object(releases, "list_data_tags", return_value=[self.keep, self.old]), patch.object(releases, "release_info", return_value=latest), patch.object(releases, "run") as command, self.assertRaisesRegex(ValueError, "Refusing cleanup"):
                releases.prune_old_releases("example/repo", self.keep)
            command.assert_not_called()

    def test_unexpected_retained_tag_prevents_all_api_calls(self):
        with patch.object(releases, "run") as command, self.assertRaisesRegex(ValueError, "Unexpected"):
            releases.prune_old_releases("example/repo", "v1.0")
        command.assert_not_called()

    def test_cleanup_failure_fails_action_and_never_deletes_retained_release(self):
        pages = [[self.latest, {"tag_name": self.old}, {"tag_name": self.draft}]]
        failure = subprocess.CalledProcessError(1, ["gh", "release", "delete"], stderr="HTTP 500")
        with patch.object(releases, "run", side_effect=[json.dumps(pages), failure]) as command, patch.object(releases, "list_data_tags", return_value=[self.keep, self.old]), patch.object(releases, "release_info", return_value=self.latest), self.assertRaises(subprocess.CalledProcessError):
            releases.prune_old_releases("example/repo", self.keep)
        self.assertEqual(len(command.call_args_list), 2)
        self.assertEqual(command.call_args_list[-1].args[3], self.old)

    def test_latest_release_lookup_failure_prevents_all_deletions(self):
        with patch.object(releases, "list_releases", return_value=[{"tag_name": self.old}]), patch.object(releases, "list_data_tags", return_value=[self.keep, self.old]), patch.object(releases, "release_info", side_effect=RuntimeError("HTTP 500")), patch.object(releases, "run") as command, self.assertRaises(RuntimeError):
            releases.prune_old_releases("example/repo", self.keep)
        command.assert_not_called()

    def test_tag_deletion_failure_can_be_retried_after_release_was_removed(self):
        remote_releases = [self.latest, {"tag_name": self.old}]
        remote_tags = [self.keep, self.old]

        def delete(*args):
            if args[:3] == ("gh", "release", "delete"):
                remote_releases[:] = [release for release in remote_releases
                                      if release["tag_name"] != args[3]]
            else:
                raise subprocess.CalledProcessError(1, args, stderr="HTTP 500")

        with patch.object(releases, "list_releases", side_effect=lambda _: list(remote_releases)), patch.object(releases, "list_data_tags", return_value=remote_tags), patch.object(releases, "release_info", return_value=self.latest):
            with patch.object(releases, "run", side_effect=delete), self.assertRaises(subprocess.CalledProcessError):
                releases.prune_old_releases("example/repo", self.keep)
            self.assertEqual(remote_releases, [self.latest])
            with patch.object(releases, "run") as command:
                releases.prune_old_releases("example/repo", self.keep)
            command.assert_called_once_with("gh", "api", "--method", "DELETE",
                                            f"repos/example/repo/git/refs/tags/{self.old}")


if __name__ == "__main__":
    unittest.main()
