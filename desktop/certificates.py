"""Local certificates without an external OpenSSL executable."""
from datetime import datetime, timedelta, timezone
import ipaddress
import os
from pathlib import Path
import secrets
import ssl
import tempfile

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from server.tls import LocalTLS


def atomic_write(path, content):
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def key_bytes(key):
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


def ensure_tls(directory: Path, address: str):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    ca, ca_key = directory / 'root-ca.pem', directory / 'root-ca-key.pem'
    cert, key = directory / 'server.pem', directory / 'server-key.pem'
    now = datetime.now(timezone.utc)
    if ca.exists() != ca_key.exists():
        raise RuntimeError('CA証明書と秘密鍵の片方がありません。バックアップから復元してください。')
    if ca.exists():
        authority = x509.load_pem_x509_certificate(ca.read_bytes())
        authority_key = serialization.load_pem_private_key(ca_key.read_bytes(), password=None)
        if authority.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo) != authority_key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo):
            raise RuntimeError('CA証明書と秘密鍵が一致しません。')
        if authority.not_valid_after_utc < now + timedelta(days=90):
            raise RuntimeError('会場CAの期限が90日未満です。更新して端末に再登録してください。')
        if authority.not_valid_before_utc > now:
            raise RuntimeError('会場CAの有効期間外です。PCの日時を確認してください。')
    else:
        authority_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Pose Parallax Local CA ' + secrets.token_hex(4))])
        authority = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(authority_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=1825))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(authority_key.public_key()), critical=False)
            .sign(authority_key, hashes.SHA256()))
        atomic_write(ca_key, key_bytes(authority_key))
        atomic_write(ca, authority.public_bytes(serialization.Encoding.PEM))
    names = [x509.IPAddress(ipaddress.ip_address(ip)) for ip in sorted({address, '127.0.0.1', '::1'})]
    names.append(x509.DNSName('localhost'))
    valid = False
    if cert.exists() and key.exists():
        try:
            existing = x509.load_pem_x509_certificate(cert.read_bytes())
            existing.verify_directly_issued_by(authority)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            valid = (existing.not_valid_before_utc <= now and existing.not_valid_after_utc > now + timedelta(days=7)
                     and set(names) <= set(existing.extensions.get_extension_for_class(x509.SubjectAlternativeName).value))
        except (ValueError, TypeError, InvalidSignature, ssl.SSLError, x509.ExtensionNotFound):
            pass
    if not valid:
        server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        certificate = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Pose Parallax')]))
            .issuer_name(authority.subject).public_key(server_key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=90))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(True, False, True, False, False, False, False, False, False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectAlternativeName(names), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(authority_key.public_key()), critical=False)
            .sign(authority_key, hashes.SHA256()))
        atomic_write(key, key_bytes(server_key))
        atomic_write(cert, certificate.public_bytes(serialization.Encoding.PEM))
    return LocalTLS(cert, key, ca)
