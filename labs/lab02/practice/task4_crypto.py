"""Task 4 - working with encrypted pages: integrity scan and key rotation.

Uses EncryptedDiskManager from ../crypto_disk.py (AES-256-GCM, one nonce + tag per page).
Reading a page that was changed on disk, or reading with the wrong key, raises
cryptography.exceptions.InvalidTag.

Check: python check.py 4
"""
import common  # noqa: F401  (makes the lab code importable)
from cryptography.exceptions import InvalidTag  # noqa: F401
from crypto_disk import EncryptedDiskManager  # noqa: F401


def find_corrupted_pages(disk, num_pages):
    """Return the list of page ids (0 .. num_pages-1) that fail the integrity check.

    `disk` is an open EncryptedDiskManager.
    """
    # TODO: try to read every page; a page that raises InvalidTag is corrupted.
    raise NotImplementedError("Task 4: find_corrupted_pages")


def rotate_key(path, old_key, new_key, num_pages):
    """Re-encrypt pages 0 .. num_pages-1 of the file `path` with new_key.

    Afterwards the file must be readable with new_key and NOT with old_key.
    """
    # TODO: decrypt every page with the old key, then write every page with the new key.
    # Close every disk manager you open.
    raise NotImplementedError("Task 4: rotate_key")
