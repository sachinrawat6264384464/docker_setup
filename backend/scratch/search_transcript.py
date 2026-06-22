import json

log_file = r"C:\Users\Dell 5490T\.gemini\antigravity-ide\brain\759c4fff-567d-43b5-a0c0-d51abddf8be7\.system_generated\logs\transcript.jsonl"

queries = ["login", "role", "resident", "masteradmin", "sahi karo"]

with open(log_file, "r", encoding="utf-8") as f:
    for line in f:
        try:
            data = json.loads(line)
            content = data.get("content", "")
            if not content:
                continue
            # Check if any query matches
            if any(q in content.lower() for q in queries) and data.get("source") == "USER_EXPLICIT":
                print(f"Step {data.get('step_index')} (USER): {content.strip()}")
                print("-" * 40)
        except Exception as e:
            pass
