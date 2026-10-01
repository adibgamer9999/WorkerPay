# WorkerPay — GitHub Windows Publishing Pipeline

The intended client release is:

`WorkerPay-Setup.exe` → double-click → Install → shortcut → WorkerPay opens

The portable build is separate:

`WorkerPay-Portable.zip` → extract → `WorkerPay.exe`

## 1. Repository

Repository: `adibgamer9999/WorkerPay`

The repository can start empty. Do not add another README, `.gitignore` or license during repository creation; this source package already contains the needed repository files.

## 2. Upload the source

Upload the contents of this package to the repository root. The repository should contain:

- `app.py`
- `requirements.txt`
- `VERSION.txt`
- `.gitignore`
- `README.md`
- `README.txt`
- `CI_RELEASE.md`
- `GITHUB_PUBLISH_PIPELINE.md`
- `.github/workflows/windows-build.yml`
- `installer/WorkerPay.iss`
- `installer/WorkerPay.ico`
- `scripts/build_windows.ps1`
- all test files

Commit directly to `main`.

## 3. Start the Windows build

Open the repository's **Actions** tab.

Select **WorkerPay Windows Build**.

Click **Run workflow**.

Set:

`release_tag = v4.5.0`

Then click **Run workflow**.

## 4. What GitHub does

The Windows runner:

1. Checks out WorkerPay.
2. Installs Python 3.13 and dependencies.
3. Runs source compilation checks.
4. Runs business-rule tests.
5. Runs legacy migration tests.
6. Runs SQLite database-health tests.
7. Runs geometry tests.
8. Runs attendance scrolling tests.
9. Runs feature regression tests, including the exact Day 1–6 / blank Day 7 / Day 7 / blank Day 8 attendance boundaries, Back-to-Employees navigation, Advance Money and Salary Payments.
10. Runs the 1,000,000-employee / 2,000,000-plot / 2,000,000-attendance stress benchmark.
11. Builds `WorkerPay.exe` with PyInstaller.
12. Smoke-tests the frozen executable.
13. Builds `WorkerPay-Setup.exe` with Inno Setup.
14. Installs the setup silently into `C:\Program Files\WorkerPay`, verifies the installed executable, then uninstalls it.
15. Generates SHA-256 checksums.
16. Uploads the build artifacts.
17. Creates a GitHub Release and attaches `WorkerPay-Setup.exe`, `WorkerPay-Portable.zip` and `SHA256SUMS.txt`.

## 5. Final client download

After the workflow succeeds, open the repository's **Releases** page.

The client-facing installer is:

`WorkerPay-Setup.exe`

The portable alternative is:

`WorkerPay-Portable.zip`

Do not give the client the source ZIP as the installation package.
