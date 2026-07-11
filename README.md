# Nexus Download Collection (NDC)

A Python CLI tool to automate downloading NexusMods collections for non-premium users. Instead of clicking the "slow download" button in your browser for 50+ mods individually, this script grabs the direct links using your browser session cookies and sends them straight to Vortex so it can download them in the background.

It features a clean, full-screen console UI (using the `rich` library) that tracks progress without cluttering your terminal.

---

## How to Run
Just double-click `Run NDC.bat`. It will automatically check if you have Python/pip, install the required packages (`curl_cffi`, `rich`, `browser_cookie3`), and start the application.

---

## How to Use (Cookie Mode)
1. Log into your NexusMods account in your web browser (Brave, Firefox, Chrome, etc.).
2. Run `Run NDC.bat` and choose option 1 to download a collection.
3. Paste the collection URL.
4. The script will auto-detect your browser session and check which mods are already downloaded to save time.
5. Select "Download MISSING only". The CLI will trigger Vortex to fetch each mod.
6. Once the list completes, the script will automatically open the collection installer inside Vortex so you can finish setting it up.

---

## Settings
Choose option 2 from the main menu to customize:
* **Download Mode**: Toggle between Cookie mode (free direct downloads) and API mode (requires a Premium account).
* **Vortex DL Folder**: Set manually if the script fails to auto-detect your Vortex download directory.
* **Download Speed & Pause**: Fine-tune the wait intervals between files so you don't overwhelm Vortex.
* **Cookie String**: If auto-detection fails (e.g. on Chrome 127+ due to App-Bound Encryption), you can paste your session cookie string here manually.
