#!/usr/bin/env python3
"""Download only reviewed speech assets; verify every byte before installation."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from igw_google_voice.russian_voices import BACKENDS, VOICES, asset_bundles


def download(root, bundle, specification, item):
    target = root / bundle / item['path']
    def valid(path):
        if not path.is_file() or path.stat().st_size != item['size']:
            return False
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        return digest.hexdigest() == item['sha256']
    if valid(target):
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.partial')
    url = ('https://huggingface.co/' + specification['repository'] + '/resolve/'
           + specification['revision'] + '/' + item['path'])
    try:
        with urllib.request.urlopen(url, timeout=60) as source, temporary.open('wb') as output:
            total = 0
            while block := source.read(1024 * 1024):
                total += len(block)
                if total > item['size']:
                    raise ValueError('Downloaded asset exceeds its reviewed size')
                output.write(block)
        if not valid(temporary):
            raise ValueError('Downloaded asset checksum mismatch')
        temporary.replace(target)
        print('Verified', bundle + '/' + item['path'], flush=True)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--backend', choices=BACKENDS, required=True)
    parser.add_argument('--voice', choices=VOICES, help='Defaults to Denis for Piper, Russian for KittenTTS 2')
    args = parser.parse_args()
    manifest = json.loads((Path(__file__).resolve().parents[1] / 'igw_google_voice/russian-speech-models.json').read_text())
    try:
        selected = asset_bundles(args.backend, args.voice)
    except ValueError as error:
        parser.error(str(error))
    jobs = [(name, manifest['bundles'][name], item) for name in selected
            for item in manifest['bundles'][name]['files']]
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(download, args.output.resolve(), *job) for job in jobs]
        for future in futures:
            future.result()


if __name__ == '__main__':
    main()
