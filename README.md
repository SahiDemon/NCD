# Nexus Download Collection (NDC) — Python CLI

An automated downloader for NexusMods collections. This tool provides a workaround for **non-Premium users** to download entire collections without clicking "slow download" for every single mod.

---

## 🚀 How to Run

Simply double-click **`Run NDC.bat`** (or run `python ndc.py` in your terminal).

---

## ⚙️ Download Modes

On first run (or if `ndc_config.json` is deleted), the tool will guide you through a quick setup to set your **API Key**, **Cookie String**, and **Mode**:

### 1. Cookie Mode (Recommended for Non-Premium)
* **How it works:** Uses your browser session cookies to fetch direct CDN download links, bypassing the "Premium Required" prompt.
* **Flow:** Opens download links directly in Chrome. Chrome downloads the files one-by-one.
* **Automatic Vortex Import:** If you point Chrome's download directory to your Vortex game folder (see below), Vortex will automatically detect the files and queue them up for installation.

### 2. API Mode
* **How it works:** Generates standard `nxm://` collection download links using your Nexus API key.
* **Flow:** Sends links straight to your Vortex mod manager.
* **Note:** Non-Premium users will see the "Premium Required" slow download webpage inside Vortex for every mod in this mode.

---

## 🛠️ Step-by-Step Guide for Cookie Mode

To make downloads fully automatic and feed them directly into Vortex:

### Step 1: Configure Chrome
1. Open **Google Chrome** and go to `Settings` (three dots `⋮` → `Settings`).
2. Search for **Downloads** in the settings search bar.
3. Click **Change** next to the download location and set it to your Vortex game folder:
   * **Stellar Blade:** `L:\Vortex Data\stellarblade`
   * **Cyberpunk 2077:** `L:\Vortex Data\cyberpunk2077`
4. **Turn OFF** the option *"Ask where to save each file before downloading"*.

### Step 2: Cancel Ongoing Vortex Installs
If Vortex is currently prompting you with download dialogs, click **Cancel** on the install process inside Vortex.

### Step 3: Run the Script
1. Run **`Run NDC.bat`**.
2. Select **Option 1 (Download a collection)**.
3. Paste the NexusMods Collection URL.
4. Select which mods to download (All, Mandatory, or Optional).
5. The script will automatically trigger Chrome to download the files one-by-one into your Vortex folder.

### Step 4: Install in Vortex
1. Once Chrome finishes downloading all files, open Vortex.
2. Go to the **Downloads** tab on the left sidebar.
3. Vortex will have automatically detected the downloaded files. Click **Install All**!

---

## ⚙️ Modifying Settings
Run the script, select **Option 2 (Settings)** to:
* Switch between **Cookie** and **API** modes.
* Re-paste or update your API key / Cookie string.
* Adjust the pause time between downloads (default: 5 seconds).
* Adjust download speed limits.
