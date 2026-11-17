"""Validate the Claude handoff artifact without executing its contents."""
import json
from hashlib import sha256
from pathlib import Path

EXPECTED = {'case_id': 'relay-proof-001', 'created_by': 'Claude',
            'message': 'local work succeeded', 'revision': 1}

def verify(folder):
    root = Path(folder).resolve(strict=True)
    path = root / 'relay-proof.json'
    if not path.exists():
        return {'status': 'waiting', 'reason': 'Claude artifact not present'}
    if path.is_symlink() or path.resolve().parent != root:
        raise ValueError('Artifact must be a regular file inside the selected folder')
    if not path.is_file() or path.stat().st_size > 4096:
        raise ValueError('Artifact must be a JSON file of at most 4096 bytes')
    raw = path.read_bytes()
    if len(raw) > 4096:
        raise ValueError('Artifact exceeds size limit')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    data = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique)
    if data != EXPECTED or type(data.get('revision')) is not int:
        raise ValueError('Artifact does not match the requested contract')
    return {'status': 'passed', 'sha256': sha256(raw).hexdigest(),
            'artifact': str(path), 'validated_by': 'ChatGPT',
            'note': 'Content verified; author identity requires the observed Claude session'}

if __name__ == '__main__':
    print(json.dumps(verify(Path(__file__).parent / 'work-test'), ensure_ascii=False, indent=2))
