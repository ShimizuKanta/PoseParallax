"""Local CA and renewable server certificates for LAN HTTPS.

Only the public CA certificate is distributed. Never rotate the CA silently: phones
trust that identity, so missing/expired CA files require an explicit operator fix.
"""
from dataclasses import dataclass
import hashlib
import ipaddress
import os
from pathlib import Path
import secrets
import shutil
import ssl
import subprocess
import tempfile


def openssl(*args, check=True):
    command = shutil.which("openssl")
    if not command:
        raise RuntimeError("OpenSSLが必要です。opensslをインストールしてから起動してください。")
    result = subprocess.run([command, *map(str, args)], capture_output=True, text=True, timeout=30)
    if check and result.returncode:
        raise RuntimeError("証明書の処理に失敗しました: " + result.stderr.strip())
    return result


@dataclass(frozen=True)
class LocalTLS:
    cert: Path
    key: Path
    ca: Path

    @property
    def ca_der(self):
        return ssl.PEM_cert_to_DER_cert(self.ca.read_text())

    @property
    def fingerprint(self):
        digest = hashlib.sha256(self.ca_der).hexdigest().upper()
        return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def ensure_local_tls(directory: Path, lan_ip: str | None, hostname: str | None = None):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    ca, ca_key = directory / "root-ca.pem", directory / "root-ca-key.pem"
    cert, key = directory / "server.pem", directory / "server-key.pem"
    addresses = {"127.0.0.1", "::1"}
    if lan_ip:
        addresses.add(str(ipaddress.ip_address(lan_ip)))
    names = {"localhost"}
    if hostname:
        try:
            addresses.add(str(ipaddress.ip_address(hostname)))
        except ValueError:
            # Validate before putting a hostname in an OpenSSL config file.
            hostname = hostname.encode("idna").decode("ascii")
            if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
                   or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-" for c in label)
                   for label in hostname.split(".")):
                raise ValueError("HTTPSホスト名が不正です。")
            names.add(hostname)

    if ca.exists() != ca_key.exists():
        raise RuntimeError("CA証明書と秘密鍵の片方がありません。data/tlsをバックアップから復元してください。")
    if not ca.exists():
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            temp = Path(temporary)
            openssl("req", "-x509", "-newkey", "rsa:3072", "-nodes", "-sha256", "-days", "1825",
                    "-subj", "/CN=Pose Parallax Local CA " + secrets.token_hex(4),
                    "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
                    "-addext", "keyUsage=critical,keyCertSign,cRLSign",
                    "-keyout", temp / "key.pem", "-out", temp / "ca.pem")
            (temp / "key.pem").chmod(0o600)
            os.replace(temp / "key.pem", ca_key)
            os.replace(temp / "ca.pem", ca)
    ca_key.chmod(0o600)
    if openssl("x509", "-in", ca, "-checkend", "7776000", "-noout", check=False).returncode:
        raise RuntimeError("会場CAの有効期限が90日未満です。CAを更新し、各端末へ再登録してください。")
    if openssl("x509", "-in", ca, "-pubkey", "-noout").stdout != openssl("pkey", "-in", ca_key, "-pubout").stdout:
        raise RuntimeError("会場CAと秘密鍵が一致しません。バックアップを確認してください。")

    valid = cert.exists() and key.exists()
    if valid:
        valid = openssl("verify", "-CAfile", ca, "-purpose", "sslserver", cert, check=False).returncode == 0
        valid = valid and openssl("x509", "-in", cert, "-checkend", "604800", "-noout", check=False).returncode == 0
        valid = valid and all(openssl("verify", "-CAfile", ca, "-verify_ip", ip, cert, check=False).returncode == 0 for ip in addresses)
        valid = valid and all(openssl("verify", "-CAfile", ca, "-verify_hostname", name, cert, check=False).returncode == 0 for name in names)
        if valid:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            try:
                context.load_cert_chain(cert, key)
            except ssl.SSLError:
                valid = False
    if not valid:
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            temp = Path(temporary)
            sans = ",".join([*("IP:" + ip for ip in sorted(addresses)), *("DNS:" + name for name in sorted(names))])
            (temp / "extensions.cnf").write_text("basicConstraints=critical,CA:FALSE\n"
                "keyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n"
                "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\nsubjectAltName=" + sans + "\n")
            openssl("req", "-new", "-newkey", "rsa:2048", "-nodes", "-sha256", "-subj", "/CN=Pose Parallax",
                    "-keyout", temp / "key.pem", "-out", temp / "request.pem")
            openssl("x509", "-req", "-in", temp / "request.pem", "-CA", ca, "-CAkey", ca_key,
                    "-set_serial", "0x" + secrets.token_hex(16), "-days", "90", "-sha256",
                    "-extfile", temp / "extensions.cnf", "-out", temp / "cert.pem")
            (temp / "key.pem").chmod(0o600)
            os.replace(temp / "key.pem", key)
            os.replace(temp / "cert.pem", cert)
    key.chmod(0o600)
    return LocalTLS(cert=cert, key=key, ca=ca)
