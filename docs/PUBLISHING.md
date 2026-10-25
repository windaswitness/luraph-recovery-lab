# Preparing and Publishing on GitHub

The repository is prepared for publication, but its owner must create the GitHub repository and upload the files separately. No Luraph Recovery Lab command creates a repository or publishes analysis results.

## Review the Contents

Publish the `luraph-recovery-lab` directory itself, not the parent workspace containing private research. The public package includes tools, documentation, tests, and authored educational examples.

Before the first commit:

- Make sure `private/`, `work/`, dumps, game source code, assets, and backups are not included in the prepared files.
- Check for user-specific absolute paths, private asset identifiers, secrets, and logs containing any of this data.
- Read [LICENSE](../LICENSE) and [CONTRIBUTING.md](../CONTRIBUTING.md).
- Run the tests and the educational example; keep the `work/` output directory out of the commit.

```sh
python -m unittest discover -s tests -v
python -m luraph_lab demo --out work/publishing-demo
```

`.gitignore` helps exclude working files, but it does not remove files already added to Git. Review the actual contents of the proposed commit.

## Create a Local Commit

Open a terminal inside the project directory. The following block is intended for a fresh copy that does not yet have its own Git repository:

```sh
git init -b main
git add README.md LICENSE CONTRIBUTING.md pyproject.toml MANIFEST.in .gitignore .gitattributes .github docs examples luraph_lab tests tools
git diff --cached --check
git diff --cached --stat
git diff --cached
```

The last command shows exactly what is staged for the commit. After reviewing it:

```sh
git commit -m "Initial release of Luraph Recovery Lab"
git status --short
```

Do not blindly reinitialize an existing project or rename its branches. If you already have Git history, follow your usual publication workflow.

## Push to the Repository You Created

Create an empty GitHub repository named `luraph-recovery-lab` with your chosen visibility. Do not add another README, `.gitignore`, or license through the web form: those files already exist locally. Then copy the HTTPS URL from the new repository's page and replace `YOUR_ACCOUNT` below:

```sh
git remote add origin https://github.com/YOUR_ACCOUNT/luraph-recovery-lab.git
git remote -v
git push -u origin main
```

This step actually uploads the files. Run it after reviewing the commit. Authenticate using your configured GitHub sign-in method; do not put tokens or passwords in the remote URL, source files, or documentation. GitHub's [official instructions](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github) describe how to create and push a local project.

After pushing, open the README, check relative links and Mermaid diagrams, and review the Actions result. Publication can only be considered verified after this step has actually been completed; having a workflow file does not mean CI has passed.

## GitHub Project Description

Suggested short description:

> Experimental Lua/Luau VM recovery toolkit: static inspection, exact-source capture planning, structured recovery from one observed VM layout, and authored examples.

For the first release, list the supported profile, input format, known rejection cases, and completed checks. Do not call it a universal Luraph decompiler or present an obfuscator version number as a compatibility guarantee.

For toolkit bug reports, prefer a small authored example and the expected behavior. A link to someone else's game, a complete private dump, or environment secrets are not needed.
