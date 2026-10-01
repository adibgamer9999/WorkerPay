# WorkerPay 4.5.0

WorkerPay is a Windows desktop worker attendance, plot salary, advance-money and salary-payment manager.

## Core rules

- Employee IDs: `EMP001`, `EMP010`, `EMP1000`, etc.
- Plot / Place is independent of the Employee ID.
- Daily salary is per plot and can differ by plot.
- `P` = 1P
- `P/2` = 0.5P
- `P+P/2` = 1.5P
- `2P` = 2P
- `A` = 0P
- A blank attendance cell is not attendance and contributes `0P`.
- One employee + one plot + one calendar date has exactly one attendance value.
- Advance money is employee-wide, has a `DD.MM.YY` date, amount and required reason, and is deducted exactly once from net salary due.

## Windows release

GitHub Actions builds WorkerPay on `windows-latest`, bundles Python with PyInstaller, creates `WorkerPay.exe`, packages it with Inno Setup, smoke-tests the installer, and publishes:

- `WorkerPay-Setup.exe`
- `WorkerPay-Portable.zip`
- `SHA256SUMS.txt`

Clients do not need Python.

See [`GITHUB_PUBLISH_PIPELINE.md`](GITHUB_PUBLISH_PIPELINE.md) for the exact publishing steps.
