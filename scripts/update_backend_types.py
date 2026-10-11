import os
import re
import glob

schemas_dir = "/home/nemro/RECRM/src/backend/app/schemas"
routers_dir = "/home/nemro/RECRM/src/backend/app/routers"

def update_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    original = content
    # Replace UUID in type hints
    content = re.sub(r':\s*Optional\[UUID\]', ': Optional[str]', content)
    content = re.sub(r':\s*List\[UUID\]', ': List[str]', content)
    content = re.sub(r':\s*UUID\b', ': str', content)
    content = re.sub(r'UUID\(', 'str(', content)
    
    # In function defs: func(arg: UUID, ...)
    content = re.sub(r'(\b[a-zA-Z0-9_]+_id)\s*:\s*UUID\b', r'\1: str', content)
    content = re.sub(r'(\b[a-zA-Z0-9_]+_id)\s*:\s*Optional\[UUID\]', r'\1: Optional[str]', content)

    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Updated {os.path.basename(filepath)}")

for path in glob.glob(f"{schemas_dir}/*.py"):
    update_file(path)

for path in glob.glob(f"{routers_dir}/*.py"):
    update_file(path)

print("Schema & router type annotations updated to str.")

