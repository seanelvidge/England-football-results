# Repository history cleanup

## Preview results

On 2 November 2026, the repository had one branch (`main`) and no tags. The initial analysis used commit `00b04bf87a518d6fdc18eacb840a03aa836a90b8`. Both cleanup options were tested in separate copies. This change implements the third option below, incorporating the subsequent nightly update at `8584a45d550d129ad85455cb63e8f28eeb7dcc78` before filtering.

| History retained | Packed Git objects | Current CSV data |
| --- | ---: | --- |
| Existing `main` history | 450.11 MiB | Unchanged |
| Remove SQLite, Parquet and old rankings caches | 366.88 MiB | Unchanged |
| Also remove historical match-result CSV versions, then restore today's CSVs | 10.44 MiB | Unchanged |

These are local measurements after packing, including the proposed workflow and documentation changes in the cleanup copies. Actual network transfer sizes depend on GitHub's packing. The current checked-out files add about 50 MiB to disk usage after generated files are removed from Git.

All seven current CSV files were compared byte for byte with the originals. Git's repository integrity check also passed for both cleanup copies. Historical football results remain in the current CSVs, including the matches dating back to 1888.

## Recommended scope

Use [git-filter-repo](https://github.com/newren/git-filter-repo) to remove these paths from earlier commits:

- `sqlite/*.sqlite` and `parquet/*.parquet`
- `.github/rankings.csv` and `.github/rankings.csv.meta.json`
- `.github/rankings.p` and `.github/workflows/rankings.p`
- `EnglandLeagueResults.csv` and `EnglandLeagueResults_wRanks.csv`
- `experimental/EnglandLeagueResults_wRanks.csv`

Restore the current results CSVs in a final commit alongside the workflow changes. Keep the smaller reference CSV histories, code, documentation, authorship and commit messages. Commits made empty by filtering can disappear, and retained commits receive new IDs when their content or ancestors change. Earlier commits will no longer contain the removed datasets, so they cannot reproduce historical database snapshots by themselves.

Local `.github/audit/` and `.github/validation/` directories are excluded from Git and from the cleanup's published history. They are not release assets.

The seven public CSVs continue to be versioned after the cleanup. This removes existing bulk and prevents future generated binaries and rankings caches from accumulating in Git; it does not impose a permanent size limit on future CSV history.

## Applying the cleanup

Publishing the rewritten history is a separate maintenance operation:

1. Pause scheduled updates for the maintenance window and confirm the current remote `main` commit. Repeat the preview if the remote has changed.
2. Make a permanent mirror or Git bundle backup outside this repository. Keep any local work and untracked files separately as well. Do not publish the old history as another branch or tag in the same repository, because ordinary clones could fetch it again.
3. Filter a fresh, separate copy, restore the exact current CSVs, and include the reviewed workflow and documentation changes.
4. Verify every current CSV checksum, run the tests, and check a normal clone of the cleaned copy. Keep the original backup intact.
5. Replace only remote `main`, using `--force-with-lease` against the previously recorded commit. If branch protection prevents this, its settings must be handled explicitly.
6. Resume the workflows and run **Nightly BBC Football Results Update** to publish the first data release.

Perform this cleanup before the first data release where possible. Release tags retain the history reachable from their commits; tags created before a cleanup would need separate consideration.

Existing clones keep their old objects and branches. After the rewrite, collaborators should save local work and clone the repository again. Merging an old branch into the rewritten branch can reintroduce the removed history. GitHub may retain cached old commit pages or pull-request references; those are separate from the ordinary clone of `main`.

## Future updates

The nightly workflow builds and verifies CSV, SQLite and Parquet together, commits the CSVs and small model snapshot, then publishes the exports in a release tagged `data-<commit SHA>`. The release stays private as a draft until every uploaded file has been downloaded and verified. Its `data-manifest.json` records the commit and checksums. A failed upload or validation fails the action, and a rerun can resume an unpublished draft.

The internal rankings state and manifest use an optional Actions cache. A missing, expired or invalid cache triggers a rebuild from the CSVs. Generated exports and cache files remain available locally when built, but are ignored by Git.

The release uploader runs only on the default branch. The overnight consistency workflow checks football-data.co.uk and downloads the latest published data release to verify it against the CSVs. This also detects a failed or missing publication after a CSV update.

For readers who only need current data, the main README documents `git clone --depth 1`. Release downloads are separate from both shallow and full clones.
