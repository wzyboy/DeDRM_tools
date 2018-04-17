from __future__ import (unicode_literals, division, absolute_import, print_function)

from . import misc
from . import yj_book

__license__   = "GPL v3"
__copyright__ = "2018, John Howell <jhowell@acm.org>"

YJ_Book = yj_book.YJ_Book
YJ_Metadata = yj_book.YJ_Metadata
KFXDRMError = misc.KFXDRMError

exception_string = misc.exception_string

file_read_binary = misc.file_read_binary
file_write_binary = misc.file_write_binary
json_deserialize = misc.json_deserialize
json_serialize = misc.json_serialize

IS_MACOS = misc.IS_MACOS
IS_WINDOWS = misc.IS_WINDOWS

user_home_dir = misc.user_home_dir
windows_user_dir = misc.windows_user_dir

locale_encode = misc.locale_encode
locale_decode = misc.locale_decode
glob_u = misc.glob_u

