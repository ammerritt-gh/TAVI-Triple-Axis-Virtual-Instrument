# Record one TAVI Monte Carlo failure

> **Status:** live

1. Copy and extract the whole support ZIP to a writable folder on the affected
   computer (Desktop is fine). Keep the `.bat` and `.py` together.
2. Close any TAVI windows, then double-click **Record-TAVI.bat**.
3. In the TAVI window that opens, select the same instrument and settings that
   fail. Select **Monte Carlo**, run one point, and wait for the error. Do not
   change the save-folder name to make it work: we need the failing setup.
4. Close TAVI. The recording window finishes the report and waits for a key.
5. Copy the entire **Reports** folder beside the recorder back onto the USB.
   Return it even if TAVI never opened. It contains the startup log and, when
   Python could start, a ZIP with the detailed recording.

No internet, installation, administrator access, or command typing is needed.
The recorder uses the existing TAVI environment. It does not repair or patch
TAVI; the GUI still saves settings and simulation files as it normally does.
The report contains local paths, selected environment variables, scientific
settings, software versions, generated instrument code and execution logs.
It excludes the API configuration/token and large simulation/DFT data files.

If TAVI hangs, return to the recording window and press Ctrl+C. The supervisor
also stops its diagnostic process tree after 30 minutes and saves the logs.
Do not close the recording console with its X button before the report finishes.
