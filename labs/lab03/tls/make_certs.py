"""Create a local Certificate Authority and a server certificate for PostgreSQL.

Run once: python labs/lab03/tls/make_certs.py
Writes into labs/lab03/tls/certs/ (git-ignored: every student generates their own keys).

  ca.crt / ca.key          the CA: our own "authority" that signs certificates
  server.crt / server.key  PostgreSQL's certificate (signed by the CA) and its private key
  wrong-ca.crt             an unrelated CA, used by check_tls.py to show verification failing
"""
import datetime as dt
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

OUT = Path(__file__).parent / "certs"
NOW = dt.datetime.now(dt.timezone.utc)


def name(common_name):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def make_ca(common_name):
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(name(common_name))
        .issuer_name(name(common_name))  # self-signed: the CA vouches for itself
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW)
        .not_valid_after(NOW + dt.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                     content_commitment=False, key_encipherment=False,
                                     data_encipherment=False, key_agreement=False,
                                     encipher_only=False, decipher_only=False), critical=True)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def make_server_cert(ca_key, ca_cert):
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(name("localhost"))
        .issuer_name(ca_cert.subject)  # signed by our CA
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW)
        .not_valid_after(NOW + dt.timedelta(days=365))
        # the names this server may be reached by; verify-full checks the host against these
        .add_extension(x509.SubjectAlternativeName([
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        ]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


def write_key(path, key):
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                       serialization.PrivateFormat.TraditionalOpenSSL,
                                       serialization.NoEncryption()))


def write_cert(path, cert):
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    ca_key, ca_cert = make_ca("CSAI302 Lab03 Local CA")
    server_key, server_cert = make_server_cert(ca_key, ca_cert)
    _, wrong_ca_cert = make_ca("Some Other CA")

    write_key(OUT / "ca.key", ca_key)
    write_cert(OUT / "ca.crt", ca_cert)
    write_key(OUT / "server.key", server_key)
    write_cert(OUT / "server.crt", server_cert)
    write_cert(OUT / "wrong-ca.crt", wrong_ca_cert)
    for f in sorted(OUT.iterdir()):
        print(" ", f.relative_to(OUT.parents[2]))
