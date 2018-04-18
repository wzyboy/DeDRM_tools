#!/usr/bin/env python2

from __future__ import print_function

import sys
# An ugly hack. But it works.
if sys.platform == 'win32':  # NOQA
    reload(sys)  # NOQA
    sys.setdefaultencoding('utf8')  # NOQA

import os
import re
import zipfile
import logging
import argparse

sys.path.append(os.path.dirname(os.path.abspath(__file__)))  # NOQA

from dedrm.k4mobidedrm import decryptBook
from kfxlib import YJ_Book


log = logging.getLogger()


def is_kfx_file(path_to_ebook):

    with open(path_to_ebook, "rb") as of:
        data = of.read(16)

    return (data.startswith(b"\xeaDRMION\xee") or data.startswith(b"CONT\x02\x00") or data.startswith(b"SQLite format 3\0"))


def pack_enc_kfxzip(path_to_ebook, output_dir):
    '''Try to pack encrypted kfx and voucher into a single kfx-zip file'''

    # Be idempotent: if input file is already a kfx-zip, return as is.
    if path_to_ebook.endswith('.kfx-zip'):
        print('Input is already a kfx-zip file, doing nothing.')
        return path_to_ebook

    original_path_to_file = os.path.abspath(path_to_ebook)

    # Most of the code below are inspired from gather_filetype.py in
    # "KFX Input" plugin by John Howell
    # https://www.mobileread.com/forums/showthread.php?t=291290

    files = [path_to_ebook]

    orig_path, orig_fn = os.path.split(original_path_to_file)
    orig_root, orig_ext = os.path.splitext(orig_fn)
    orig_dir = os.path.basename(orig_path)
    sdr_path = os.path.join(orig_path, orig_root + ".sdr")

    # log.info("orig_path: %s" % orig_path)
    # log.info("orig_fn: %s" % orig_fn)
    # log.info("orig_root: %s" % orig_root)
    # log.info("orig_ext: %s" % orig_ext)
    # log.info("orig_dir: %s" % orig_dir)
    # log.info("sdr_path: %s" % sdr_path)

    if orig_ext == ".kfx" and os.path.isdir(sdr_path):
        # e-ink Kindle
        for dirpath, dns, fns in os.walk(sdr_path):
            for fn in fns:
                if fn.endswith(".kfx") or fn == "voucher":
                    files.append(os.path.join(dirpath, fn))

    elif orig_ext == ".azw" and re.match("^B[A-Z0-9]{9}_(EBOK|EBSP)$", orig_dir):
        # Kindle for PC/Mac
        for dirpath, dns, fns in os.walk(orig_path):
            for fn in fns:
                if os.path.splitext(fn)[1] in [".md", ".res", ".voucher"]:
                    files.append(os.path.join(dirpath, fn))

    elif orig_ext == ".kfx" and re.match("^B[A-Z0-9]{9}(_sample)?$", orig_dir):
        # Kindle for Android and Fire
        for dirpath, dns, fns in os.walk(orig_path):
            for fn in fns:
                if os.path.splitext(fn)[1] in [".ast", ".kfx"] and fn != orig_fn:
                    files.append(os.path.join(dirpath, fn))

    elif orig_ext == ".azw8" and re.match("^{0-9A-F-}{36}$", orig_dir):
        # Kindle for iOS
        for dirpath, dns, fns in os.walk(orig_path):
            for fn in fns:
                if os.path.splitext(fn)[1] in [".azw9", ".md", ".res", ".voucher"] and fn != orig_fn:
                    files.append(os.path.join(dirpath, fn))

    else:
        print("KFX Input: Ignoring file not in a recognized directory structure")
        return path_to_ebook

    output_fn = '{}.kfx-zip'.format(orig_root)
    zfile = os.path.join(output_dir, output_fn)

    with zipfile.ZipFile(zfile, "w", compression=zipfile.ZIP_STORED) as zf:
        for filepath in files:
            zf.write(filepath, os.path.basename(filepath))

    print("KFX Input: Gathered %d files as %s" % (len(files), zfile))
    return zfile


def main():
    argp = argparse.ArgumentParser()
    argp.add_argument('input_file')
    argp.add_argument('output_dir')
    argp.add_argument('-k', '--k4i', action='append', default=[])
    argp.add_argument('-a', '--ab', action='append', default=[])
    argp.add_argument('-s', '--serials', action='append', default=[])
    argp.add_argument('-p', '--pids', action='append', default=[])
    args = argp.parse_args()

    if not any((args.k4i, args.ab, args.serials, args.pids)):
        raise SystemExit('At least one key is needed.')

    # Pre-process kfx files
    if is_kfx_file(args.input_file):
        is_kfx = True
        input_file = pack_enc_kfxzip(args.input_file, args.output_dir)
    else:
        is_kfx = False
        input_file = args.input_file

    # Decrypt books
    decrypted_file = decryptBook(input_file, args.output_dir, args.k4i, args.ab, args.serials, args.pids)
    # XXX: an ugly hack...
    if isinstance(decrypted_file, int):
        sys.exit(decrypted_file)
    else:
        print('Decrypted:', decrypted_file)

    # Post-process kfx files
    if is_kfx:
        # decrypted_file is a decrypted kfx-zip
        kfx_data = YJ_Book(decrypted_file, log).convert_to_single_kfx()
        kfx_fn = os.path.splitext(decrypted_file)[0] + '.kfx'
        with open(kfx_fn, 'wb') as kfx_fd:
            kfx_fd.write(kfx_data)
        print('Monolithic KFX:', kfx_fn)


if __name__ == '__main__':
    main()
