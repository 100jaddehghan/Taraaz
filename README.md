# Taraaz
English freelance finance desktop app built with PyQt6 and SQLite.

Run in this directory with Python 3.10 or newer:

    python -m pip install -r requirements.txt
    python app.py

Use `python app.py --demo` for a temporary sample workspace.

Choose a project currency when creating a contract. IRR uses whole rials. USD and EUR support cents. IRT preserves existing toman projects. Reports and CSV exports cover the selected currency only.

For hourly projects, enter a fixed rate, select the project and click Log time. Enter hours and minutes for each addition. Billable value is the cumulative minutes multiplied by the rate divided by 60, rounded to the nearest minor currency unit. The rate locks after time is logged. Payments and expenses are separate transactions. Estimated profit is billable value minus expenses. Net cash is payments minus expenses.

The normal database is taraaz.sqlite3 in the local Taraaz application data directory. Close the app before copying the database for backup.
Use Settings to choose English or Persian and a light or dark theme. Preferences apply immediately and persist between sessions. In Transactions, search for a project by name or client, choose Payment or Expense, then enter the amount and date.
Neon is also available in Settings. Transaction dates use the Solar Hijri calendar in both languages. SQLite stores the underlying date in ISO Gregorian format for compatibility and chronological sorting.
Financial report → Client statement previews the selected customer and reporting currency, including project balances and payments. Save PDF or confirm Send via Telegram. In Settings enter a BotFather token and destination chat ID; the recipient must start the bot or add it to the destination group. Token is held in memory (or supplied via TARAAZ_BOT_TOKEN). Projects → CRM stores dated private notes. Waiting status triggers one local reminder per day while Taraaz is open, including on the next launch.
