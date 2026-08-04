def dedupe(items):
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        if "name" in item:
            result.append(item)
        seen.add(item)
    return result
