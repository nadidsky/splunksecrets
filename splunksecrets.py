"""Command line tool for encrypting/decrypting Splunk passwords"""
from __future__ import print_function

import argparse
import base64
import getpass
import itertools
import os

import six
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import algorithms, Cipher, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def decrypt(secret, ciphertext, nosalt=False):
    """Given the first 16 bytes of splunk.secret, decrypt a Splunk password"""
    plaintext = None
    if ciphertext.startswith("$1$"):
        ciphertext = base64.b64decode(ciphertext[3:])
        key = secret[:16]

        algorithm = algorithms.ARC4(key)
        cipher = Cipher(algorithm, mode=None, backend=default_backend())
        decryptor = cipher.decryptor()
        plaintext = decryptor.update(ciphertext)

        chars = []
        if nosalt is False:
            for char1, char2 in zip(plaintext[:-1], itertools.cycle("DEFAULTSA")):
                chars.append(six.byte2int([char1]) ^ ord(char2))
        else:
            chars = [six.byte2int([char]) for char in plaintext[:-1]]

        plaintext = "".join([six.unichr(c) for c in chars])
    elif ciphertext.startswith("$7$"):
        ciphertext = base64.b64decode(ciphertext[3:])

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"disk-encryption",
            iterations=1,
            backend=default_backend()
        )
        key = kdf.derive(secret)

        iv = ciphertext[:16]  # pylint: disable=invalid-name
        tag = ciphertext[-16:]
        ciphertext = ciphertext[16:-16]

        algorithm = algorithms.AES(key)
        cipher = Cipher(algorithm, mode=modes.GCM(iv, tag), backend=default_backend())
        decryptor = cipher.decryptor()
        plaintext = decryptor.update(ciphertext).decode()

    return plaintext


def encrypt(secret, plaintext, nosalt=False):
    """Given the first 16 bytes of splunk.secret, encrypt a Splunk password"""
    key = secret[:16]

    chars = []
    if nosalt is False:
        for char1, char2 in zip(plaintext, itertools.cycle("DEFAULTSA")):
            chars.append(ord(char1) ^ ord(char2))
    else:
        chars = [ord(x) for x in plaintext]

    chars.append(0)

    plaintext = b"".join([six.int2byte(c) for c in chars])

    algorithm = algorithms.ARC4(key)
    cipher = Cipher(algorithm, mode=None, backend=default_backend())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(plaintext)

    return "$1$%s" % base64.b64encode(ciphertext).decode()


def encrypt_new(secret, plaintext, iv=None):  # pylint: disable=invalid-name
    """Use the new AES 256 GCM encryption in Splunk 7.2"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"disk-encryption",
        iterations=1,
        backend=default_backend()
    )
    key = kdf.derive(secret)

    if iv is None:
        iv = os.urandom(16)

    algorithm = algorithms.AES(key)
    cipher = Cipher(algorithm, mode=modes.GCM(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(plaintext.encode()) + encryptor.finalize()

    return "$7$%s" % base64.b64encode(b"%s%s%s" % (iv, ciphertext, encryptor.tag)).decode()


def main():  # pragma: no cover
    """Command line interface"""
    cliargs = argparse.ArgumentParser()
    cliargs.add_argument("--splunk-secret", required=True)
    cliargs.add_argument("-D", "--decrypt", action="store_const", dest="mode", const="decrypt")
    cliargs.add_argument("--new", action="store_const", dest="mode", const="encrypt_new")
    cliargs.add_argument("--nosalt", action="store_true", dest="nosalt")
    args = cliargs.parse_args()

    with open(args.splunk_secret, "rb") as splunk_secret_file:
        key = splunk_secret_file.read().strip()

    if args.mode == "decrypt":
        try:
            ciphertext = six.moves.input("Encrypted password: ")
        except KeyboardInterrupt:
            pass
        else:
            print(decrypt(key, ciphertext, args.nosalt))
    else:
        try:
            plaintext = getpass.getpass("Plaintext password: ")
        except KeyboardInterrupt:
            pass
        else:
            if args.mode == "encrypt_new":
                print(encrypt_new(key, plaintext))
            else:
                print(encrypt(key, plaintext, args.nosalt))
