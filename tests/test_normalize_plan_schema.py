from __future__ import annotations

def normalize_plan_schema_py(node):
    if not isinstance(node, dict):
        return node
    # allow further processing even if 'type' is present; only skip if already normalized
    if isinstance(node, dict) and ('properties' in node or ('items' in node and isinstance(node['items'], dict) and 'type' in node['items'])):
        return node
    keys = list(node.keys())
    if not any(k in node for k in ('fields', 'parts', 'champs', 'element', 'type')) and len(keys) == 1 and keys[0] not in ('title', 'description'):
        key = keys[0]
        inner = normalize_plan_schema_py(node[key])
        if isinstance(inner, dict) and 'title' not in inner:
            inner['title'] = key
        return inner
    if 'parts' in node:
        props = {k: normalize_plan_schema_py(v) for k, v in node['parts'].items()}
        out = {'type': 'object', 'properties': props}
        if 'title' in node:
            out['title'] = node['title']
        if 'description' in node:
            out['description'] = node['description']
        return out
    if 'fields' in node:
        props = {k: normalize_plan_schema_py(v) for k, v in node['fields'].items()}
        out = {'type': 'object', 'properties': props}
        if 'title' in node:
            out['title'] = node['title']
        if 'description' in node:
            out['description'] = node['description']
        return out
    if node.get('type') == 'array':
        items = node.get('items')
        if isinstance(items, dict) and not any(k in items for k in ('type', 'properties', 'items')):
            item_props = {ik: {'type': iv if isinstance(iv, str) else 'string'} for ik, iv in items.items()}
            items = {'type': 'object', 'properties': item_props}
        else:
            items = normalize_plan_schema_py(items) if items else {}
        out = {'type': 'array', 'items': items}
        if 'title' in node:
            out['title'] = node['title']
        if 'description' in node:
            out['description'] = node['description']
        return out
    out = {'type': node.get('type', 'string')}
    if 'title' in node:
        out['title'] = node['title']
    if 'description' in node:
        out['description'] = node['description']
    return out


def test_normalize_plan_schema_handles_parts_and_fields():
    raw = {
        "plan_cadre": {
            "title": "Plan-cadre",
            "parts": {
                "partie_1": {
                    "title": "Partie 1",
                    "fields": {
                        "programme": {"title": "Programme"},
                        "competences": {
                            "title": "Compétences",
                            "type": "array",
                            "items": {
                                "code": "string",
                                "enonce": "string"
                            }
                        }
                    }
                }
            }
        }
    }
    norm = normalize_plan_schema_py(raw)
    assert norm["type"] == "object"
    assert "partie_1" in norm["properties"]
    p1 = norm["properties"]["partie_1"]
    assert p1["type"] == "object"
    assert "programme" in p1["properties"]
    assert p1["properties"]["programme"]["type"] == "string"
    comp = p1["properties"]["competences"]
    assert comp["type"] == "array"
    assert comp["items"]["type"] == "object"
    assert "code" in comp["items"]["properties"]
