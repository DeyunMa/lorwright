"""Verify this self-contained reference bundle using only Python's standard library."""
import hashlib
import json
from pathlib import Path
import struct


def main():
    root=Path(__file__).resolve().parent
    manifest=json.loads((root/'manifest.json').read_text())
    for item in manifest['files']:
        p=(root/item['path']).resolve()
        assert p.is_relative_to(root) and p.is_file(),item['path']
        raw=p.read_bytes()
        assert len(raw)==item['bytes'] and hashlib.sha256(raw).hexdigest()==item['sha256'],item['path']
        if p.suffix=='.png':
            assert raw[:8]==b'\x89PNG\r\n\x1a\n'
            width,height=struct.unpack_from('>II',raw,16)
            assert [width,height]==item['png_size'],item['path']
    starter=json.loads((root/'data/elise-starter.json').read_text())
    assert len(starter['cards'])==9 and sum(c['copies_in_starter_deck'] for c in starter['cards'])==18
    assert len(list((root/'images/cards').glob('*.png')))==9
    assert len(list((root/'images/keywords').glob('*.png')))==18
    progression=json.loads((root/'data/elise-progression-source.json').read_text())
    assert len(progression['objects'])==139 and progression['root_hash']=='36ad9250'
    weights=json.loads((root/'data/keyword-ai-weights.json').read_text())
    assert len(weights['keywords'])==34 and weights['formula_recovered'] is False
    assert manifest['full_ai_algorithm_included'] is False
    print(json.dumps(dict(status='passed',files=len(manifest['files']),starter_cards=9,starter_copies=18,
        keyword_icons=18,keyword_weight_records=34,full_ai_algorithm_included=False),ensure_ascii=False))


if __name__=='__main__':main()
