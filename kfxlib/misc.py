from __future__ import (unicode_literals, division, absolute_import, print_function)

import atexit
import collections
import glob
import gzip
import json
import locale
import posixpath
import os
import random
import re
import shutil
import string
import cStringIO
import sys
import time
import urllib
from urlparse import urlparse
import uuid
import zipfile

__license__   = "GPL v3"
__copyright__ = "2018, John Howell <jhowell@acm.org>"

MAX_TEMPDIR_REMOVAL_TRIES = 60

PLATFORM_NAME = sys.platform.lower()
IS_MACOS = "darwin" in PLATFORM_NAME
IS_WINDOWS = "win32" in PLATFORM_NAME or "win64" in PLATFORM_NAME
IS_LINUX = not (IS_MACOS or IS_WINDOWS)
LOCALE_ENCODING = locale.getdefaultlocale()[1] or "utf8"

ZIP_FILE_EXTENSIONS = [".zip", ".kfxu", ".kfxz", ".kfx-zip", ".apf", ".kpf"]

UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
UUID_MATCH_RE = r"^%s$" % UUID_RE

ZIP_SIGNATURE = b"\x50\x4B\x03\x04"

MIMETYPE_OF_EXT = {
    ".bin": "application/octet-stream",
    ".bmp": "image/bmp",
    ".css": "text/css",
    ".eot": "application/vnd.ms-fontobject",
    ".dfont": "application/x-dfont",
    ".epub": "application/epub+zip",
    ".gif": "image/gif",
    ".htm": "text/html",
    ".html": "text/html",
    ".ico": "image/x-icon",
    ".jpg": "image/jpeg",
    ".js": "text/javascript",
    ".jxr": "image/vnd.ms-photo",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".ncx": "application/x-dtbncx+xml",
    ".opf": "application/oebps-package+xml",
    ".otf": "application/x-font-otf",
    ".png": "image/png",
    ".pdf": "application/pdf",
    ".pobject": "application/azn-plugin-object",
    ".svg": "image/svg+xml",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".ttf": "application/x-font-truetype",
    ".txt": "text/plain",
    ".webp": "image/webp",
    ".woff": "application/font-woff",
    ".xhtml": "application/xhtml+xml",
    ".xml": "application/xml",
    }

RESOURCE_TYPE_OF_EXT = {
    ".bmp": "image",
    ".css": "styles",
    ".eot": "font",
    ".dfont": "font",
    ".gif": "image",
    ".htm": "text",
    ".html": "text",
    ".ico": "image",
    ".jpg": "image",
    ".js": "text",
    ".jxr": "image",
    ".mp3": "audio",
    ".mp4": "video",
    ".otf": "font",
    ".pdf": "image",
    ".png": "image",
    ".svg": "image",
    ".tif": "image",
    ".tiff": "image",
    ".ttf": "font",
    ".txt": "text",
    ".webp": "video",
    ".woff": "font",
    }

EXT_OF_MIMETYPE = {
    "application/azn-plugin-object": ".pobject",
    "application/epub+zip": ".epub",
    "application/font-sfnt": ".ttf",
    "application/font-woff": ".woff",
    "application/octet-stream": ".bin",
    "application/oebps-package+xml": ".opf",
    "application/pdf": ".pdf",
    "application/vnd.ms-fontobject": ".eot",
    "application/vnd.ms-opentype": ".otf",
    "application/x-dfont": ".dfont",
    "application/x-dtbncx+xml": ".ncx",
    "application/x-font-otf": ".otf",
    "application/x-font-truetype": ".ttf",
    "application/x-font-ttf": ".ttf",
    "application/x-font-woff": ".woff",
    "application/xhtml+xml": ".xhtml",
    "application/xml": ".xml",
    "audio/mp4": ".mp4",
    "audio/mpeg": ".mp3",
    "image/bmp": ".bmp",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/jxr": ".jxr",
    "image/png": ".png",
    "image/svg+xml": ".svg",
    "image/tiff": ".tif",
    "image/vnd.ms-photo": ".jxr",
    "image/webp": ".webp",
    "image/x-icon": ".ico",
    "text/css": ".css",
    "text/html": ".html",
    "text/javascript": ".js",
    "text/plain": ".txt",
    "video/mp4": ".mp4",
    "video/ogg": ".ogg",
    "video/webm": ".webm",
    }

try:
    from calibre.constants import numeric_version as calibre_numeric_version
except:
    calibre_numeric_version = None

tempdir_ = None
atexit_set_ = False

try:
    from calibre.ptempfile import PersistentTemporaryDirectory
    calibre_temp = True
except:
    import tempfile
    calibre_temp = False

def tempdir():
    global tempdir_
    global atexit_set_

    if tempdir_ is not None and not os.path.isdir(tempdir_):
        raise Exception("Temporary directory is missing: %s" % tempdir_)

    if tempdir_ is None:
        if calibre_temp:
            tempdir_ = PersistentTemporaryDirectory()
        else:
            tempdir_ = tempfile.mkdtemp()

            if not atexit_set_:
                atexit.register(temp_file_cleanup)
                atexit_set_ = True

    return tempdir_

def temp_file_cleanup():
    global tempdir_

    if tempdir_ is not None and not calibre_temp:
        tries = 0
        while (tempdir_ and tries < MAX_TEMPDIR_REMOVAL_TRIES):
            if tries > 0:
                time.sleep(1)

            try:
                shutil.rmtree(tempdir_)
                tempdir_ = None
            except:
                tries += 1

        if tempdir_:
            print("ERROR: Failed to remove temp directory: %s" % tempdir_)
            tempdir_ = None

def temp_filename(ext, data=None):
    if ext: ext = "." + ext

    unique = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(20))
    filename = os.path.join(tempdir(), unique + ext)

    if data is not None:
        file_write_binary(filename, data)

    return filename

def create_temp_dir():
    dirname = temp_filename("")
    os.mkdir(dirname)
    return dirname

def type_name(x):
    return type(x).__name__

def exception_string(e):
    return "%s: %s" % (type_name(e), unicode(e))

def natural_sort_key(s):
    return "".join(["00000000"[len(c):] + c if c.isdigit() else c for c in re.split(r"([0-9]+)", s.lower())])

def list_keys(a_dict):
    return list_symbols(a_dict.keys())

def list_symbols(a_iter):
    return ", ".join(sorted(unicode_list(a_iter)))

def list_truncated(a_iter, max_allowed=10):
    return ", ".join(truncate_list(sorted(unicode_list(a_iter)), max_allowed))

def unicode_list(l):
    return [unicode(s) for s in l]

def truncate_list(l, max_allowed=10):
    return l if len(l) <= max_allowed else l[:max_allowed] + ["... (%d total)" % len(l)]

def hex_string(string, sep=" "):
    return sep.join("%02x" % ord(b) for b in string)

def quote_name(s):
    return "\"%s\"" % s if ("," in s or " " in s) else s

def json_serialize(data, sort_keys=False):
    return json.dumps(data, indent=4, separators=(",", ": "), sort_keys=sort_keys)

def json_serialize_compact(data):
    return json.dumps(data, indent=None, separators=(",", ":"))

def json_deserialize(data):
    return json.loads(data, object_pairs_hook=collections.OrderedDict)

def gunzip(data):
    with gzip.GzipFile(fileobj=cStringIO.StringIO(data), mode="rb") as f:
        return f.read()

def file_write_binary(filename, data):
    with open(filename, "wb") as of:
        of.write(data)

def file_read_binary(filename):
    if not os.path.isfile(filename):
        raise Exception("File %s does not exist." % quote_name(filename))

    with open(filename, "rb") as of:
        return of.read()

def font_file_ext(data, default="bin"):
    if data[0:4] == b"\x00\x01\x00\x00":
        return "ttf"

    if data[0:4] == b"OTTO":
        return "otf"

    if data[0:4] == b"wOFF":
        return "woff"

    if data[34:35] == b"\x4c\x50":
        return "eot"

    if data[0:4] == b"\x00\x00\x01\x00":
        return "dfont"

    return default

def check_abs_path(path):
    if not path.startswith("/"):
        raise Exception("check_abs_path: '%s' is not rooted" % path)

    return path

def check_rel_path(path):
    if path.startswith("/"):
        raise Exception("check_rel_path: '%s' is rooted" % path)

    return path

def unroot_path(path):
    return check_abs_path(path)[1:]

def root_path(path):
    return "/" + check_rel_path(path)

def dirname(filename):
    return check_abs_path(posixpath.dirname(check_abs_path(filename)))

def urlabspath(url, ref_from=None, working_dir=None):
    if ref_from is not None:
        working_dir = dirname(ref_from)

    purl = urlparse(url, "file")
    if purl.scheme != "file" or purl.netloc != "":
        return url

    return abspath(purl.path, working_dir) + ("#" + purl.fragment if purl.fragment else "")

def abspath(rel_path, working_dir):
    return check_abs_path(posixpath.normpath(posixpath.join(check_abs_path(working_dir), check_rel_path(rel_path))))

def urlrelpath(url, ref_from=None, working_dir=None):
    if ref_from is not None:
        working_dir = dirname(ref_from)

    purl = urlparse(url, "file")
    if purl.scheme != "file" or purl.netloc != "":
        return url

    return relpath(purl.path, working_dir) + ("#" + purl.fragment if purl.fragment else "")

def relpath(abs_path, working_dir):
    return check_rel_path(posixpath.relpath(check_abs_path(abs_path), check_abs_path(working_dir)))

def get_url_filename(url):
    purl = urlparse(url, "file")
    if purl.scheme != "file" or purl.netloc != "":
        return None

    path = urllib.unquote(purl.path)

    if not path.startswith("/"):
        return None

    return path

def windows_user_dir(local_appdata=False, appdata=False):
    if not IS_WINDOWS:
        raise Exception("Windows API is not supported on this platform")

    import ctypes.wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.wintypes.DWORD),
            ("Data2", ctypes.wintypes.WORD),
            ("Data3", ctypes.wintypes.WORD),
            ("Data4", ctypes.wintypes.BYTE * 8)
        ]

        def __init__(self, uuid_):
            ctypes.Structure.__init__(self)
            self.Data1, self.Data2, self.Data3, self.Data4[0], self.Data4[1], rest = uuid.UUID(uuid_).fields
            for i in range(2, 8):
                self.Data4[i] = rest>>(8 - i - 1)*8 & 0xff

    SHGetKnownFolderPath = ctypes.WINFUNCTYPE(ctypes.wintypes.HANDLE,
            ctypes.POINTER(GUID), ctypes.wintypes.DWORD, ctypes.wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p))(
            ("SHGetKnownFolderPath", ctypes.windll.shell32))

    CoTaskMemFree = ctypes.WINFUNCTYPE(None, ctypes.c_wchar_p)(("CoTaskMemFree", ctypes.windll.ole32))

    FOLDERID_RoamingAppData = "{3EB685DB-65F9-4CF6-A03A-E3EF65729F3D}"
    FOLDERID_LocalAppData = "{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}"
    FOLDERID_Profile = "{5E6C858F-0E22-4760-9AFE-EA3317B67173}"
    fid = FOLDERID_LocalAppData if local_appdata else (FOLDERID_RoamingAppData if appdata else FOLDERID_Profile)

    ppath = ctypes.c_wchar_p()

    hresult = SHGetKnownFolderPath(
                ctypes.byref(GUID(fid)),
                0,
                None,
                ctypes.byref(ppath))

    if hresult:
        raise Exception("SHGetKnownFolderPath(%s) failed: %s" % (fid, windows_error(hresult)))

    path = ppath.value
    CoTaskMemFree(ppath)

    return path

def windows_error(hresult=None):
    if not IS_WINDOWS:
        raise Exception("Windows API is not supported on this platform")

    import ctypes

    if hresult is None:
        hresult = ctypes.GetLastError()

    return "%08x (%s)" % (hresult, ctypes.FormatError(hresult & 0xffff) if hresult & 0xffff0000 in [0x80070000, 0] else "?")

def wine_user_dir(local_appdata=False, appdata=False):

    raise Exception("Linux/Wine is not currently supported.")

def locale_encode(x):
    if isinstance(x, list):
        return [locale_encode(a) for a in x]

    if isinstance(x, dict):
        return dict([(locale_encode(a), locale_encode(b)) for a,b in x.items()])

    if isinstance(x, unicode):
        return x.encode(LOCALE_ENCODING, errors="replace")

    return x

def locale_decode(x):
    if isinstance(x, list):
        return [locale_decode(a) for a in x]

    if isinstance(x, dict):
        return dict([(locale_decode(a), locale_decode(b)) for a,b in x.items()])

    if isinstance(x, str):
        return x.decode(LOCALE_ENCODING, errors="replace")

    return x

def glob_u(arg):

    return locale_decode(glob.glob(locale_encode(arg)))

def user_home_dir():
    if IS_WINDOWS:

        return windows_user_dir()
    else:
        return locale_decode(os.path.expanduser("~"))

def make_unique_name(root_name, check_set, sep=""):
    unique_number = 0
    while True:
        unique_name = "%s%s%d" % (root_name, sep, unique_number)
        if unique_name not in check_set:
            return unique_name

        unique_number += 1

class KFXDRMError(ValueError):
    pass

class DataFile(object):
    def __init__(self, name_or_stream, data=None, parent=None):
        if isinstance(name_or_stream, str):
            name_or_stream = name_or_stream.decode("utf-8")

        if isinstance(name_or_stream, unicode):
            self.stream = None
            self.relname = name_or_stream
            self.is_real_file = data is None
        else:
            self.stream = name_or_stream
            self.relname = self.stream.name if hasattr(self.stream, "name") else "stream"
            self.is_real_file = False

        self.data = data
        self.parent = parent

        self.name = self.relname
        self.ext = os.path.splitext(self.relname)[1]

    def get_data(self):
        if self.data is None:
            if self.stream is not None:
                self.stream.seek(0)
                self.data = self.stream.read()
                self.stream.seek(0)
            else:
                self.data = file_read_binary(self.name)

        return self.data

    def is_zipfile(self):
        return self.ext in [".apf", ".kfx-zip", ".kpf", ".kfxz", ".zip"] or self.get_data().startswith(ZIP_SIGNATURE)

    def as_ZipFile(self):
        if self.is_real_file:
            return zipfile.ZipFile(self.name, "r")

        return zipfile.ZipFile(cStringIO.StringIO(self.get_data()), "r")

    def relative_datafile(self, relname):

        if self.is_real_file:
            dirname = os.path.dirname(self.name)
            if dirname:
                relname = os.path.join(dirname, relname)

            if IS_WINDOWS:
                relname = relname.replace("/", "\\")

            return DataFile(relname)

        elif self.parent is not None:
            relname = relname.replace("\\", "/")
            dirname = posixpath.dirname(self.relname)
            if dirname:
                relname = posixpath.join(dirname, relname)

            with self.parent.as_ZipFile() as zf:
                return DataFile(relname, zf.read(relname), self.parent)

        else:
            raise Exception("Cannot locate file relative to unknown parent: %s" % relname)

    def __cmp__(self, other):

        if not isinstance(other, DataFile):
            raise Exception("DataFile __cmp__: comparing with %s" % type_name(other))

        return cmp(self.name, other.name)

def convert_jxr_to_tiff(log, jxr_data):
    if calibre_numeric_version is not None and calibre_numeric_version >= (3, 9, 0):

        from calibre.utils.img import (load_jxr_data, image_to_data)
        img = load_jxr_data(jxr_data)
        tiff_data = image_to_data(img, fmt="TIFF")

    else:
        raise Exception("calibre version 3.9 or greater is required to convert JPEG-XR images")

    return tiff_data

def convert_pdf_to_jpeg(log, pdf_data, page_num):
    pdf_file = temp_filename("pdf", pdf_data)
    jpeg_dir = create_temp_dir()

    if True:

        from calibre.ebooks.metadata.pdf import page_images
        page_images(pdf_file, jpeg_dir, first=page_num, last=page_num)

    for dirpath, dirnames, filenames in os.walk(jpeg_dir):
        if len(filenames) != 1:
            raise Exception("pdftoppm created %d files" % len(filenames))

        if not (filenames[0].endswith(".jpg") or filenames[0].endswith(".jpeg")):
            raise Exception("pdftoppm created unexpected file: %s" % filenames[0])

        with open(os.path.join(dirpath, filenames[0]), "rb") as of:
            jpeg_data = of.read()

        break
    else:
        raise Exception("pdftoppm created no files")

    return jpeg_data

