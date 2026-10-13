#!/usr/bin/env python3
"""Create a dedicated offline CA and separate IP-SAN speech server certificates."""
import argparse
import ipaddress
import os
from pathlib import Path
import secrets
import subprocess


def run(*args):
    subprocess.run(['openssl', *map(str, args)], check=True, capture_output=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--primary-address', required=True)
    parser.add_argument('--secondary-address', required=True)
    args = parser.parse_args()
    addresses = {}
    for role in ('primary', 'secondary'):
        address = ipaddress.ip_address(getattr(args, role + '_address'))
        if address.version != 4 or not address.is_private or address.is_unspecified or address.is_multicast:
            parser.error('Use private IPv4 addresses actually used in the HTTPS endpoints')
        addresses[role] = str(address)
    os.umask(0o077)
    args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
    root = args.output
    ca_config = root / 'ca.cnf'
    ca_config.write_text('[req]\nprompt=no\ndistinguished_name=dn\nx509_extensions=ca\n'
                         '[dn]\nCN=IGW Speech Private CA\n[ca]\n'
                         'basicConstraints=critical,CA:TRUE,pathlen:0\n'
                         'keyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\n')
    run('req', '-x509', '-newkey', 'rsa:3072', '-nodes', '-sha256', '-days', '1825',
        '-keyout', root / 'ca.key', '-out', root / 'ca.crt', '-config', ca_config)
    for role, address in addresses.items():
        extensions = root / (role + '.cnf')
        extensions.write_text('basicConstraints=critical,CA:FALSE\n'
                              'keyUsage=critical,digitalSignature,keyEncipherment\n'
                              'extendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\n'
                              'authorityKeyIdentifier=keyid,issuer\nsubjectAltName=IP:' + address + '\n')
        run('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-sha256',
            '-keyout', root / (role + '.key'), '-out', root / (role + '.csr'),
            '-subj', '/CN=IGW Speech ' + role)
        run('x509', '-req', '-in', root / (role + '.csr'), '-CA', root / 'ca.crt',
            '-CAkey', root / 'ca.key', '-set_serial', str(secrets.randbits(159) or 1),
            '-days', '365', '-sha256', '-extfile', extensions, '-out', root / (role + '.crt'))
        run('verify', '-CAfile', root / 'ca.crt', root / (role + '.crt'))
    print('Created private TLS material. Keep ca.key offline; deploy only each server\'s own leaf key.')


if __name__ == '__main__':
    main()
