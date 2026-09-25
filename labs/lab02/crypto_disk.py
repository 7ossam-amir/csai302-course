"""Disk manager that encrypts every page with AES-GCM before it reaches the file.

Same interface as DiskManager, so the buffer pool does not change at all.
On-disk slot layout: nonce (12) | ciphertext (PAGE_SIZE) | tag (16)

Run: python crypto_disk.py  -> small demo (round trip + tamper detection)
"""
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from disk_manager import PAGE_SIZE

NONCE = 12
TAG = 16
SLOT = NONCE + PAGE_SIZE + TAG


class EncryptedDiskManager:
    def __init__(self, path, key):
        mode = "r+b" if os.path.exists(path) else "w+b"
        self.f = open(path, mode)
        self.aes = AESGCM(key)
        self.reads = 0
        self.writes = 0

    def write_page(self, page_id, data):
        assert len(data) == PAGE_SIZE
        self.writes += 1
        nonce = os.urandom(NONCE)  # fresh nonce on every write
        aad = page_id.to_bytes(8, "little")  # binds the ciphertext to this page id
        ct = self.aes.encrypt(nonce, bytes(data), aad)  # ciphertext + tag
        self.f.seek(page_id * SLOT)
        self.f.write(nonce + ct)

    def read_page(self, page_id):
        self.reads += 1
        self.f.seek(page_id * SLOT)
        blob = self.f.read(SLOT)
        if len(blob) < SLOT or blob == bytes(SLOT):  # never-written page
            return bytes(PAGE_SIZE)
        aad = page_id.to_bytes(8, "little")
        return self.aes.decrypt(blob[:NONCE], blob[NONCE:], aad)  # raises InvalidTag if tampered

    def close(self):
        self.f.close()


if __name__ == "__main__":
    key = AESGCM.generate_key(bit_length=256)
    if os.path.exists("secret.db"):
        os.remove("secret.db")
    d = EncryptedDiskManager("secret.db", key)
    d.write_page(0, b"my secret diary".ljust(PAGE_SIZE, b"\0"))
    d.write_page(1, b"another page".ljust(PAGE_SIZE, b"\0"))
    print("decrypted:", d.read_page(0)[:15])

    d.f.flush()
    with open("secret.db", "rb") as raw:
        print("on disk:  ", raw.read(40))

    # swap attack: copy page 1's bytes into page 0's slot
    d.f.seek(SLOT)
    page1 = d.f.read(SLOT)
    d.f.seek(0)
    d.f.write(page1)
    try:
        d.read_page(0)
    except Exception as e:
        print("page swap detected:", type(e).__name__)

    # tamper attack: flip one byte
    d.f.seek(SLOT + 20)
    d.f.write(b"X")
    try:
        d.read_page(1)
    except Exception as e:
        print("tampering detected:", type(e).__name__)

    d.close()
    os.remove("secret.db")
