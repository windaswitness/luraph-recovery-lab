# Maintaining and Publishing NARSIL

Use this guide when preparing updates to NARSIL or publishing changes through your own fork. The upstream project is [windaswitness/narsil](https://github.com/windaswitness/narsil). No NARSIL command creates a repository or publishes analysis results.

## Review the Contents

Work inside the `narsil` repository itself, not a parent workspace containing private research. The public package includes tools, documentation, tests, and authored educational examples.

Before committing:

- Make sure `private/`, `work/`, dumps, game source code, assets, and backups are not included in the proposed changes.
- Check for user-specific absolute paths, private asset identifiers, secrets, and logs containing any of this data.
- Read [LICENSE](../LICENSE) and [CONTRIBUTING.md](../CONTRIBUTING.md).
- Run the tests and the educational example; keep the `work/` output directory out of the commit.

```sh
python -m unittest discover -s tests -v
python -m narsil demo --out work/publishing-demo
```

Choose a new output directory when repeating the demo. `.gitignore` helps exclude working files, but it does not remove files already tracked by Git. Review the actual contents of the proposed commit.

## Start from the Existing History

If you already have a working clone, keep its history and remotes. Do not reinitialize it with `git init`.

For contributions through a fork, create your fork on GitHub, replace `YOUR_ACCOUNT` below with its owner, and clone it:

```sh
git clone https://github.com/YOUR_ACCOUNT/narsil.git
cd narsil
git remote add upstream https://github.com/windaswitness/narsil.git
git remote -v
```

Maintainers working directly in the upstream repository can instead clone `https://github.com/windaswitness/narsil.git`. In that case, `origin` already refers to upstream and a second remote is unnecessary.

## Prepare a Reviewed Commit

From an up-to-date working copy, create a branch for the change. Choose another branch name if `prepare-update` already exists.

```sh
git switch -c prepare-update
git add README.md LICENSE CONTRIBUTING.md pyproject.toml MANIFEST.in .gitignore .gitattributes .github docs examples narsil tests tools
git diff --cached --check
git diff --cached --stat
git diff --cached
```

The explicit `git add` list includes the public project files. Narrow it to the files you intend to change if your working copy contains unrelated edits. The last command shows exactly what is staged for the commit. After reviewing it:

```sh
git commit -m "Prepare NARSIL update"
git status --short
```

Use a more specific commit message when it helps explain the change.

## Push Your Branch and Review the Result

Confirm that `origin` points to the repository where you intend to publish, then push the branch:

```sh
git remote -v
git push -u origin prepare-update
```

This step actually uploads the commits. Run it after reviewing them. Authenticate using your configured GitHub sign-in method; do not put tokens or passwords in the remote URL, source files, or documentation. If you are publishing a separate repository from a source archive instead of using a fork, follow GitHub's [official instructions for adding local code](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github).

Open a pull request from your branch when contributing to upstream. Maintainers should use the project's review and release process for changes to the published project.

After pushing, check the rendered README, relative links, Mermaid diagrams, and the Actions result for the new revision. A successful check on an earlier revision does not establish that the current changes pass. Having a workflow file alone does not mean CI has run.

## GitHub Project Description

Suggested short description:

> NARSIL — experimental Luraph deobfuscator and Lua/Luau VM recovery toolkit. Recover the logic. Reforge the code.

Suggested GitHub topics: `luraph`, `luraph-deobfuscator`, `luraph-deobf`,
`deobfuscation`, `deobfuscator`, `lua`, `luau`, `reverse-engineering`, and
`devirtualization`. Keep these focused on the project's actual scope.

For releases, list the supported profile, input format, known rejection cases, and completed checks. Do not call NARSIL a universal Luraph decompiler or present an obfuscator version number as a compatibility guarantee.

For toolkit bug reports, prefer a small authored example and the expected behavior. A link to someone else's game, a complete private dump, or environment secrets are not needed.
