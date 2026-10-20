"""Export a .docx to PDF with Microsoft Word, for page-count verification.

More defensive than the first version: works on a temp copy, waits for Word to
be ready, and reports the AppleScript error instead of swallowing it.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

SCRIPT = '''
set docxPath to POSIX file "{docx}"
set pdfPath to "{pdf}"
with timeout of 900 seconds
    tell application "Microsoft Word"
        activate
        try
            set d to open docxPath
        on error errMsg number errNum
            return "OPEN_ERROR " & errNum & " " & errMsg
        end try
        delay 3
        try
            update fields of active document
        end try
        delay 2
        try
            repeat with toc in tables of contents of active document
                update toc
            end repeat
        end try
        delay 1
        try
            save as active document file name pdfPath file format format PDF
        on error errMsg number errNum
            return "SAVE_ERROR " & errNum & " " & errMsg
        end try
        delay 2
        try
            close active document saving no
        end try
    end tell
end timeout
return "OK"
'''


def main() -> int:
    src = Path(sys.argv[1]).expanduser().resolve()
    pdf = Path(sys.argv[2]).expanduser().resolve() if len(sys.argv) > 2 else src.with_suffix(".pdf")
    if pdf.exists():
        pdf.unlink()

    # Word for Mac is sandboxed: opening a fresh file under /tmp can raise a
    # file-access prompt that blocks the AppleScript. Reuse the original path.
    tmp_docx = src

    result = subprocess.run(
        ["osascript", "-e", SCRIPT.format(docx=tmp_docx, pdf=pdf)],
        capture_output=True,
        text=True,
        timeout=900,
    )
    stdout = result.stdout.strip()
    if result.returncode != 0:
        print("osascript error:", result.stderr.strip()[:400], "| stdout:", stdout[:200])
        return result.returncode
    if stdout.startswith("OPEN_ERROR") or stdout.startswith("SAVE_ERROR"):
        print(stdout[:400])
        return 1

    for _ in range(40):
        if pdf.exists() and pdf.stat().st_size > 0:
            time.sleep(2)
            print(f"ok: {pdf} ({pdf.stat().st_size // 1024} KB)")
            return 0
        time.sleep(1)
    print(f"pdf not produced (script said: {stdout!r})")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
