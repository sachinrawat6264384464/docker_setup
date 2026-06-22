import os

log_path = r"C:\Users\Dell 5490T\.gemini\antigravity-ide\brain\759c4fff-567d-43b5-a0c0-d51abddf8be7\.system_generated\logs\transcript.jsonl"
print(f"File exists: {os.path.exists(log_path)}")
if os.path.exists(log_path):
    print(f"Size: {os.path.getsize(log_path)} bytes")
    # print first 3 lines
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        for i in range(3):
            line = f.readline()
            print(f"Line {i}: {line[:200]}")
else:
    # list directory
    parent = os.path.dirname(log_path)
    print(f"Parent directory: {parent}")
    if os.path.exists(parent):
        print(f"Files in parent: {os.listdir(parent)}")
