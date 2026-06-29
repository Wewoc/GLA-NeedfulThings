# anchor_delivery — needfull things / menu
# Adds sys.argv[1] path support to merge_to_md.py, count_project.py, count_chats.py
# Original behaviour (double-click) is preserved in all three cases.

---

## FILE: stuff/merge_to_md.py

### ALT
```python
import os

SOURCE_DIR  = "."
OUTPUT_FILE = "summary.md"
EXCLUDE     = {OUTPUT_FILE, "merge_to_md.py", "struktur.md"}
```

### NEU
```python
import os
import sys

SOURCE_DIR  = sys.argv[1] if len(sys.argv) > 1 else "."
OUTPUT_FILE = os.path.join(SOURCE_DIR, "summary.md")
EXCLUDE     = {"summary.md", "merge_to_md.py", "struktur.md"}
```

---

## FILE: stuff/count_project.py

### ALT
```python
ROOT   = "."
OUTPUT = "project_stats.md"
```

### NEU
```python
import sys as _sys
ROOT   = _sys.argv[1] if len(_sys.argv) > 1 else "."
OUTPUT = os.path.join(ROOT, "project_stats.md")
```

---

## FILE: stuff/count_chats.py

### ALT
```python
ROOT   = "."
OUTPUT = "chat_stats.md"
```

### NEU
```python
import sys as _sys
ROOT   = _sys.argv[1] if len(_sys.argv) > 1 else "."
OUTPUT = os.path.join(ROOT, "chat_stats.md")
```
