# WorkerPay Windows CI release

WorkerPay is built on a real GitHub-hosted Windows runner (`windows-latest`). End users receive a native Windows installer and a portable package; Python is not required on the client PC.

## Release pipeline

WorkerPay source → Windows runner → source/tests + database tests → PyInstaller → WorkerPay.exe → Inno Setup → WorkerPay-Setup.exe + WorkerPay-Portable.zip

## Trigger

- `workflow_dispatch`: runs the Windows build/tests, uploads the build artifacts, and publishes a GitHub Release using the supplied release tag.
- Git tag matching `v*` (for example `v4.5.0`): runs the same pipeline and publishes a GitHub Release with both final packages.

## Required release checks

The workflow checks Python compilation, business-rule logic, legacy migration, database health, geometry, attendance scrolling, feature regressions (including exact day 1–8 attendance behavior, advance money and Salary Payments navigation), the 1,000,000-employee SQLite stress benchmark, PyInstaller output, the frozen executable, installer installation/uninstallation, and SHA-256 checksums.

## Client files

- `WorkerPay-Setup.exe`: normal Windows installation; installs to `C:\Program Files\WorkerPay` by default and creates Start Menu/Desktop shortcuts.
- `WorkerPay-Portable.zip`: portable build for users who prefer extraction instead of installation.

Application data is stored in Windows user Local AppData so the installed program can operate without writing databases into Program Files.
