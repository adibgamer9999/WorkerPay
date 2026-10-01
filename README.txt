WorkerPay 4.5.0 - Windows Release Candidate

CORE BUSINESS RULES
- Employee IDs use EMP + digits: EMP001, EMP010, EMP1000.
- Plot / Place is separate text and is never converted into an Employee ID.
- Daily Salary is per full P-day and can differ by plot.
- P = Full Day (1P)
- P/2 = Half Day (0.5P)
- P+P/2 = Full Day + Half Night (1.5P)
- 2P = Full Day + Full Night (2P)
- A = Absent (0P)

ARCHITECTURE
- SQLite with WAL, foreign keys, indexes and transactions.
- Historical plot salary, rule and payment records.
- Attendance is exactly one value per employee/plot/calendar day; legacy duplicate cells are quarantined during migration so blank days never add salary/P units.
- Advance Money records include DD.MM.YY date, amount and mandatory reason, and are deducted exactly once from net salary due.
- Validated online backups and legacy migration.
- Paged/virtualized UI: filters search the full database; paging is only a rendering optimization.
- Background work and batching are used where practical to keep the UI responsive.

WINDOWS DISTRIBUTION
The GitHub Actions workflow builds a native Windows application on a Windows-hosted runner.
End users do not need Python.

Outputs:
- WorkerPay-Setup.exe
- WorkerPay-Portable.zip

See CI_RELEASE.md for the release workflow.

LOCAL WINDOWS BUILD (DEVELOPER ONLY)
- Double-click BUILD_WINDOWS_LOCAL.bat.
- The builder finds a supported Python automatically; it can also create a private runtime without changing PATH.
- It produces dist\\WorkerPay\\WorkerPay.exe and release\\WorkerPay-Portable.zip.
- End users do NOT need Python.

CLIENT INSTALLATION
- Recommended: use WorkerPay-Setup.exe produced by the Windows CI release workflow.
- Portable: extract WorkerPay-Portable.zip and run WorkerPay.exe.
- The installer creates the Start Menu and Desktop shortcuts and launches WorkerPay after installation.

INSTALL LOCATION
- WorkerPay-Setup.exe installs the program into the Windows Program Files location (normally C:\Program Files\WorkerPay).
- User data/database/logs are kept under the Windows user Local AppData folder on C:, with one-time migration from the older Roaming location.
