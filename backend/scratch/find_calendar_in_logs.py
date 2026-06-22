import json

log_path = r"C:\Users\Dell 5490T\.gemini\antigravity-ide\brain\759c4fff-567d-43b5-a0c0-d51abddf8be7\.system_generated\logs\transcript.jsonl"

with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        try:
            data = json.loads(line)
            content = data.get('content', '')
            if 'CalendarView.js' in content or 'CalendarView' in content:
                # print first 200 chars and length
                print(f"Step {data.get('step_index')}, Type: {data.get('type')}, Len: {len(content)}")
                if 'export default function CalendarView' in content and 'eventsByDate' in content:
                    print("Found candidate code in content!")
                    # Save it to a file
                    with open(f"scratch/candidate_{data.get('step_index')}.txt", 'w', encoding='utf-8') as out:
                        out.write(content)
            
            # Also check tool_calls
            tool_calls = data.get('tool_calls', [])
            for call in tool_calls:
                args = str(call.get('arguments', ''))
                if 'CalendarView' in args:
                    print(f"Tool call in Step {data.get('step_index')}: {call.get('name')}")
                    if 'ReplacementContent' in args or 'CodeContent' in args:
                        with open(f"scratch/tool_args_{data.get('step_index')}.txt", 'w', encoding='utf-8') as out:
                            out.write(args)
        except Exception as e:
            pass
