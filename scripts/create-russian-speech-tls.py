#!/usr/bin/env python3
"""Create a private CA and Russian speech leaf for loopback and cluster DNS."""
import argparse
import os
from pathlib import Path
import re
import secrets
import subprocess


def run(*args):
    subprocess.run(['openssl', *map(str, args)], check=True, capture_output=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--service', default='russian-speech')
    parser.add_argument('--namespace', default='igw-speech')
    args = parser.parse_args()
    for value in (args.service, args.namespace):
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', value):
            parser.error('Use Kubernetes DNS labels')
    os.umask(0o077)
    args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
    root = args.output
    ca = root / 'ca.cnf'
    ca.write_text('[req]\nprompt=no\ndistinguished_name=dn\nx509_extensions=ca\n'
                  '[dn]\nCN=Local Russian Speech CA\n[ca]\n'
                  'basicConstraints=critical,CA:TRUE,pathlen:0\n'
                  'keyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\n')
    run('req', '-x509', '-newkey', 'rsa:3072', '-nodes', '-sha256', '-days', '1825',
        '-keyout', root / 'ca.key', '-out', root / 'ca.crt', '-config', ca)
    leaf = root / 'server.cnf'
    dns = f'{args.service}.{args.namespace}.svc.cluster.local'
    leaf.write_text('basicConstraints=critical,CA:FALSE\n'
                    'keyUsage=critical,digitalSignature,keyEncipherment\n'
                    'extendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\n'
                    'authorityKeyIdentifier=keyid,issuer\n'
                    f'subjectAltName=IP:127.0.0.1,DNS:{dns}\n')
    run('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-sha256',
        '-keyout', root / 'server.key', '-out', root / 'server.csr',
        '-subj', '/CN=Local Russian Speech')
    run('x509', '-req', '-in', root / 'server.csr', '-CA', root / 'ca.crt',
        '-CAkey', root / 'ca.key', '-set_serial', str(secrets.randbits(159) or 1),
        '-days', '365', '-sha256', '-extfile', leaf, '-out', root / 'server.crt')
    run('verify', '-CAfile', root / 'ca.crt', root / 'server.crt')
    (root / 'token').write_text(secrets.token_urlsafe(48) + '\n')
    print('Created private CA, server leaf, and token. Never deploy ca.key.')


if __name__ == '__main__':
    main()
