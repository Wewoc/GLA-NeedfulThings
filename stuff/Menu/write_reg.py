"""
write_reg.py -- needfull things / menu
Writes context menu entries directly via winreg (no regedit, no elevation needed).
Called by install.bat with the menu directory as argument.
"""

import sys
import winreg
from pathlib import Path


def set_key(base, subkey, values):
    """Create a registry key under HKCU and set its values."""
    full = f"Software\\Classes\\Directory\\shell\\{subkey}"
    if base:
        full = f"{full}\\{base}"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, full, 0, winreg.KEY_SET_VALUE) as k:
        for name, data in values.items():
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, data)


def main():
    if len(sys.argv) < 2:
        print("ERROR: menu directory argument missing")
        sys.exit(1)

    menu_dir = sys.argv[1].rstrip("\\")

    entries = [
        ("NeedfulMerge",      "Merge folder to MD",   "shell32.dll,72",  f'cmd /k "{menu_dir}\\run_merge.bat" "%V"'),
        ("NeedfulTree",       "Generate folder tree",  "shell32.dll,4",   f'cmd /k "{menu_dir}\\run_tree.bat" "%V"'),
        ("NeedfulCountProj",  "Count project stats",   "shell32.dll,13",  f'cmd /k "{menu_dir}\\run_count_proj.bat" "%V"'),
        ("NeedfulCountChats", "Count chat stats",      "shell32.dll,13",  f'cmd /k "{menu_dir}\\run_count_chats.bat" "%V"'),
        ("NeedfulAnon",       "Anonymize JSONs here",  "shell32.dll,167", f'cmd /k python "{menu_dir}\\run_anonymize.py" "%V"'),
    ]

    for key, label, icon, command in entries:
        set_key("",        key, {"": label, "Icon": icon})
        set_key("command", key, {"": command})
        print(f"  [+] {label}")

    print("\nRegistry import successful.")


if __name__ == "__main__":
    main()
