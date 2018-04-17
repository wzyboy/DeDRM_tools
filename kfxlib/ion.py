from __future__ import (unicode_literals, division, absolute_import, print_function)

import collections
import datetime
import decimal
import math
import re

from .yj_symbol_catalog import (
            SYSTEM_SYMBOL_TABLE, IonSymbolTable)

from .misc import (list_symbols, quote_name, type_name)

__license__   = "GPL v3"
__copyright__ = "2018, John Howell <jhowell@acm.org>"

DEBUG = False
REPORT_ALL_USED_SYMBOLS = False

LARGE_DATA_SIZE = 256
MAX_ASCII_DATA_SIZE = 10000

shared_symbol_tables = {}

IonBool = bool

IonDecimal = decimal.Decimal
IonFloat = float
IonInt = int
IonList = list
IonNull = type(None)

IonString = unicode

def ion_type(value):
    t = type(value)
    if t in ION_TYPES:
        return t

    if isinstance(value, IonAnnotation):
        return IonAnnotation

    if isinstance(value, IonList) and not isinstance(value, IonSExp):
        return IonList

    if isinstance(value, long):
        return IonInt

    raise Exception("Data has non-Ion type %s: %s" % (type_name(value), repr(value)))

def isunicode(value):

    return isinstance(value, unicode) and not isinstance(value, IonSymbol)

def raw_value(iondata, expect=None):
    t = ion_type(iondata)
    if expect is not None and t is not expect:
        raise Exception("Ion data type is %s, expected %s: %s" % (type_name(iondata), repr(expect), repr(iondata)))

    if t is IonAnnotation:
        raise Exception("No python equivalent for %s: %s" % (type_name(iondata), repr(iondata)))

    if t is IonBLOB or t is IonCLOB:
        return str(t)

    if t is IonSExp:
        return list(t)

    if t is IonStruct:
        return collections.OrderedDict(t)

    if t is IonSymbol:
        return unicode(t)

    return iondata

class IonAnnotation(object):
    def __init__(self, annotations, value):
        self.annotations = annotations if isinstance(annotations, IonAnnots) else IonAnnots(annotations)

        if isinstance(value, IonAnnotation):
            raise Exception("IonAnnotation cannot be annotated")

        self.value = value

    def __repr__(self):
        return b"%s %s" % (repr(self.annotations), repr(self.value))

    def __unicode__(self):
        return unicode(repr(self.annotations))

    def is_single(self):
        return len(self.annotations) == 1

    def has_annotation(self, annotation):
        return annotation in self.annotations

    def verify_annotation(self, annotation):
        if not self.has_annotation(annotation):
            raise Exception("Expected annotation %s, found %s" % (repr(annotation), repr(self.annotations)))

        return self

class IonAnnots(tuple):

    def __new__(cls, annotations):
        annots = tuple.__new__(cls, annotations)

        if len(annots) == 0:
            raise Exception("IonAnnotation cannot be empty")

        for a in annots:
            if not isinstance(a, IonSymbol):
                raise Exception("IonAnnotation must be IonSymbol: %s" % repr(a))

        return annots

    def __repr__(self):
        return b" ".join([b"%s::" % repr(a) for a in self])

    def __unicode__(self):
        return unicode(repr(self))

class IonBLOB(str):

    def __eq__(self, other):
        if not isinstance(other, (IonBLOB, str)):
            raise Exception("IonBLOB __eq__: comparing with %s" % type_name(other))

        return str(self) == str(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return b"*** %d byte BLOB ***" % len(self)

    def __unicode__(self):
        return unicode(self.__repr__())

    def ascii_data(self):
        if len(self) <= MAX_ASCII_DATA_SIZE:
            try:
                return self.decode("ascii")
            except:
                pass

        return None

    def is_large(self):
        return len(self) >= LARGE_DATA_SIZE and self.ascii_data() is None

class IonCLOB(str):

    pass

class IonNop(object):

    pass

class IonSExp(list):
    def __repr__(self):
        return b"(%s)" % (b", ".join([repr(v) for v in self]))

    def __unicode__(self):
        return unicode(self.__repr__())

class IonStruct(collections.OrderedDict):

    def __init__(self, *args):
        if len(args) == 1:
            collections.OrderedDict.__init__(self, args[0])
            return

        collections.OrderedDict.__init__(self)
        if len(args) % 2 != 0:
            raise Exception("IonStruct created with %d arguments" % len(args))

        for i in range(0, len(args), 2):
            self[args[i]] = args[i+1]

    def __repr__(self):
        return b"{%s}" % (b", ".join(["%s: %s" % (repr(k), repr(v)) for k,v in self.items()]))

class IonSymbol(unicode):

    def __repr__(self):
        if re.match(r"^[a-zA-Z$_][a-zA-Z0-9$_]*$", self):
            return str(self)

        return b"'%s'" % unicode.__repr__(self)[2:-1]

IS = IonSymbol

class IonTimestamp(datetime.datetime):
    def __repr__(self):
        value = self

        if isinstance(value.tzinfo, IonTimestampTZ):
            format = value.tzinfo.format()
            format = format.replace("%f", ("%06d" % value.microsecond)[:value.tzinfo.fraction_len()])

            if value.year < 1900:

                format = format.replace("%Y", "%04d" % value.year)
                value = value.replace(year=1900)

            return value.strftime(str(format)) + (str(value.tzname()) if value.tzinfo.present() else b"")

        return value.isoformat()

ION_TIMESTAMP_Y = "%YT"
ION_TIMESTAMP_YM = "%Y-%mT"
ION_TIMESTAMP_YMD = "%Y-%m-%d"
ION_TIMESTAMP_YMDHM = "%Y-%m-%dT%H:%M"
ION_TIMESTAMP_YMDHMS = "%Y-%m-%dT%H:%M:%S"
ION_TIMESTAMP_YMDHMSF = "%Y-%m-%dT%H:%M:%S.%f"

class IonTimestampTZ(datetime.tzinfo):

    def __init__(self, offset, format, fraction_len):
        self.__offset = offset
        self.__format = format
        self.__fraction_len = fraction_len
        self.__present = format in {ION_TIMESTAMP_YMDHM, ION_TIMESTAMP_YMDHMS, ION_TIMESTAMP_YMDHMSF}

        if offset and not self.__present:
            raise Exception("IonTimestampTZ has offset '%s' with non-present format" % unicode(offset))

        if offset and (offset < -1439 or offset > 1439):
            raise Exception("IonTimestampTZ has invalid offset %s" % unicode(offset))

        if fraction_len < 0 or fraction_len > 6:
            raise Exception("IonTimestampTZ has invalid fraction len %d" % fraction_len)

        if fraction_len and format != ION_TIMESTAMP_YMDHMSF:
            raise Exception("IonTimestampTZ has fraction len %d without fraction in format" % fraction_len)

    def utcoffset(self, dt):
        return datetime.timedelta(minutes=(self.__offset or 0))

    def tzname(self, dt):
        if self.__offset is None:
            return b"-00:00"

        if self.__offset == 0:
            return b"Z"

        return b"%s%02d:%02d" % (b"+" if self.__offset >= 0 else b"-", abs(self.__offset) // 60, abs(self.__offset) % 60)

    def dst(self, dt):
        return datetime.timedelta(0)

    def offset_minutes(self):
        return self.__offset

    def format(self):
        return self.__format

    def present(self):
        return self.__present

    def fraction_len(self):
        return self.__fraction_len

    def __eq__(self, other):
        '''
        if other is None:
            return False
        '''
        if not isinstance(other, IonTimestampTZ):
            raise Exception("IonTimestampTZ __eq__: comparing with %s" % type_name(other))

        return (self.__offset, self.__format, self.__fraction_len) == (other.__offset, other.__format, other.__fraction_len)

    def __ne__(self, other):
        return not self.__eq__(other)

ION_TYPES = {IonAnnotation, IonBool, IonBLOB, IonCLOB, IonDecimal, IonFloat, IonInt, IonList, IonNull, IonSExp,
            IonString, IonStruct, IonSymbol, IonTimestamp}

class IonFormat(object):

    major_version = 1
    minor_version = 0

    def __init__(self, log, symtab=None, import_symbols=False):
        self.log = log
        self.symtab = symtab
        self.import_symbols = import_symbols

    def deserialize_annotated_value(self, data, expect_annotation=None):
        value = self.deserialize_single_value(data)

        if not isinstance(value, IonAnnotation):
            raise Exception("deserialize_annotated_value returned %s" % type_name(value))

        if expect_annotation is not None:
            value.verify_annotation(expect_annotation)

        return value

    def deserialize_single_value(self, data):
        values = self.deserialize_multiple_values(data)
        if len(values) != 1:
            raise Exception("Expected single Ion value found %d: %s" % (len(values), repr(values)))

        return values[0]

    def serialize_single_value(self, value):
        return self.serialize_multiple_values([value])

def unannotated(value):
    return value.value if isinstance(value, IonAnnotation) else value

def ion_data_eq(f1, f2, msg="Ion data mismatch", log=None):
    def ion_data_eq_(f1, f2, ctx):
        data_type = ion_type(f1)

        if ion_type(f2) is not data_type:
            ctx.append("type mismatch: %s != %s" % (type_name(f1), type_name(f2)))
            return False

        if data_type is IonAnnotation:
            if not ion_data_eq_(IonList(f1.annotations), IonList(f2.annotations), ctx):
                ctx.append("IonAnnotation")
                return False

            if not ion_data_eq_(f1.value, f2.value, ctx):
                ctx.append("in IonAnnotation %s" % unicode(f1))
                return False

            return True

        if data_type in [IonList, IonSExp]:
            if len(f1) != len(f2):
                ctx.append("%s length %d != %d" % (type_name(f1), len(f1), len(f2)))
                return False

            for i,(d1,d2) in enumerate(zip(f1, f2)):
                if not ion_data_eq_(d1, d2, ctx):
                    ctx.append("at %s index %d" % (type_name(f1), i))
                    return False

            return True

        if data_type is IonStruct:
            if len(f1) != len(f2):
                ctx.append("IonStruct length %d != %d" % (len(f1), len(f2)))
                return False

            for f1k,f1v in f1.items():
                if f1k not in f2:
                    ctx.append("IonStruct key %s missing" % f1k)
                    return False

                if not ion_data_eq_(f1v, f2[f1k], ctx):
                    ctx.append("at IonStruct key %s" % f1k)
                    return False

            return True

        if data_type is IonFloat and math.isnan(f1) and math.isnan(f2):
            return True

        if f1 != f2 or repr(f1) != repr(f2):
            ctx.append("value %s != %s" % (repr(f1), repr(f2)))
            return False

        return True

    ctx = []
    success = ion_data_eq_(f1, f2, ctx)

    if (not success) and log is not None:
        log.error("%s: %s" % (msg, ", ".join(ctx[::-1])))

    return success

def filtered_IonList(ion_list, omit_large_blobs=False):

    if not omit_large_blobs:
        return ion_list

    filtered = []
    for val in ion_list[:]:
        if ion_type(val) is IonAnnotation and ion_type(val.value) is IonBLOB and val.value.is_large():
            val = IonAnnotation(val.annotations, "*** %d byte BLOB omitted ***" % len(val.value))

        filtered.append(val)

    return filtered

local_symbol_tables = []

class SymbolTableImport(object):
    def __init__(self, name, version, max_id):
        self.name = name
        self.version = version
        self.max_id = max_id

class LocalSymbolTable(object):
    def __init__(self, log, initial_import=None, context="", ignore_undef=False):
        local_symbol_tables.append(self)
        self.log = log
        self.context = context
        self.ignore_undef = ignore_undef

        self.undefined_ids = set()
        self.undefined_symbols = set()
        self.unexpected_used_symbols = set()
        self.reported = False
        self.clear()

        if initial_import:
            self.import_shared_symbol_table(initial_import)

    def clear(self):
        self.table_imports = []
        self.symbols = []
        self.id_of_symbol = {}
        self.symbol_of_id = {}
        self.unexpected_ids = set()
        self.creating_local_symbols = False
        self.creating_yj_local_symbols = False

        self.import_symbols(SYSTEM_SYMBOL_TABLE.symbols)
        self.local_min_id = len(self.symbols) + 1

    def create_symbol_table(self, type_, symbol_table_data, yj_local_symbols=False):
        if type_ == "$9":

            raise Exception("Creating shared symbol tables not implemented")

        if "$6" in symbol_table_data:
            imports = symbol_table_data["$6"]
            if ion_type(imports) is IonSymbol:

                if imports != "$3":
                    raise Exception("Unexpected imports value: %s" % imports)
            else:
                self.clear()

                for sym_import in imports:
                    self.import_shared_symbol_table(sym_import["$4"],
                            sym_import.get("$5") or 1,
                            sym_import.get("$8"))
        else:
            self.clear()

        symbol_list = symbol_table_data["$7"] if "$7" in symbol_table_data else []

        self.creating_local_symbols = True
        self.import_symbols(symbol_list)

        expected_max_id = symbol_table_data["$8"] if "$8" in symbol_table_data else None

        if (expected_max_id is not None) and (expected_max_id != len(self.symbols)):
            self.log.error("Symbol table max_id after import expected %d, found %d" % (expected_max_id, len(self.symbols)))

    def import_shared_symbol_table(self, name, version=None, max_id=None):
        if DEBUG: self.log.debug("Importing ion symbol table %s version %s max_id %s" % (
                                quote_name(name), version, max_id))

        if self.creating_local_symbols:
            raise Exception("Importing shared symbols after local symbols have been created")

        if name == SYSTEM_SYMBOL_TABLE.name:
            return

        symbol_table = shared_symbol_tables.get((name, version)) or shared_symbol_tables.get((name, None))

        if symbol_table is None:
            self.log.error("Imported shared symbol table %s is unknown" % name)
            symbol_table = IonSymbolTable(name=name, version=version)

        if version is None:
            version = symbol_table.version
        elif symbol_table.version != version:
            if max_id is None:
                self.log.error("Import version %d of shared symbol table %s without max_id, but have version %d" % (
                        version, name, symbol_table.version))
            else:
                self.log.warning("Import version %d of shared symbol table %s, but have version %d" % (
                        version, name, symbol_table.version))

        table_len = len(symbol_table.symbols)

        if max_id is None:
            max_id = table_len

        if max_id < 0:
            raise Exception("Import symbol table %s version %d max_id %d is invalid" % (name, version, max_id))

        self.table_imports.append(SymbolTableImport(name, version, max_id))

        if max_id < table_len:
            import_symbols = symbol_table.symbols[:max_id]
        elif max_id > table_len:
            if table_len > 0:
                self.log.warning("Import symbol table %s version %d max_id %d exceeds known table size %d" % (
                        name, version, max_id, table_len))

            import_symbols = symbol_table.symbols + ([None] * (max_id - table_len))
        else:
            import_symbols = symbol_table.symbols

        self.import_symbols(import_symbols)
        self.local_min_id = len(self.symbols) + 1

    def import_symbols(self, symbols):
        for symbol in symbols:
            if symbol is not None:
                if isunicode(symbol):
                    symbol = unicode(symbol)
                else:
                    self.log.error("imported symbol %s is type %s, treating as null" % (symbol, type_name(symbol)))
                    symbol = None

            self.add_symbol(symbol)

    def create_local_symbol(self, symbol):

        self.creating_local_symbols = True

        if symbol not in self.id_of_symbol:
            self.add_symbol(symbol)

        return IonSymbol(symbol)

    def add_symbol(self, symbol):
        if symbol is None:
            self.symbols.append(None)
            return -1

        if not isunicode(symbol):
            raise Exception("symbol %s is type %s, not unicode" % (symbol, type_name(symbol)))

        if len(symbol) == 0:
            raise Exception("symbol has zero length")

        expected = True

        if not self.creating_local_symbols:
            if symbol.endswith("?"):
                symbol = symbol[:-1]
                expected = False
            elif REPORT_ALL_USED_SYMBOLS:
                expected = False

        self.symbols.append(symbol)

        if symbol not in self.id_of_symbol:
            symbol_id = len(self.symbols)
            self.id_of_symbol[symbol] = symbol_id
            self.symbol_of_id[symbol_id] = symbol
        else:

            symbol_id = self.id_of_symbol[symbol]
            self.log.error("Symbol %s already exists with id %d" % (symbol, symbol_id))

        if not expected:
            self.unexpected_ids.add(symbol_id)

        return symbol_id

    def get_symbol(self, symbol_id):
        if not isinstance(symbol_id, int):
            raise Exception("get_symbol: symbol id must be integer not %s: %s" % (type_name(symbol_id), repr(symbol_id)))

        symbol = self.symbol_of_id.get(symbol_id)

        if symbol is None:
            symbol = "$%d" % symbol_id
            self.undefined_ids.add(symbol_id)

        if symbol_id in self.unexpected_ids:
            self.unexpected_used_symbols.add(symbol)

        return IonSymbol(symbol)

    def get_id(self, ion_symbol, used=True):
        if not isinstance(ion_symbol, IonSymbol):
            raise Exception("get_id: symbol must be IonSymbol not %s: %s" % (type_name(ion_symbol), repr(ion_symbol)))

        symbol = unicode(ion_symbol)

        if symbol.startswith("$") and re.match(r"^\$[0-9]+$", symbol):
            symbol_id = int(symbol[1:])

            if symbol_id not in self.symbol_of_id:
                self.undefined_ids.add(symbol_id)
        else:
            symbol_id = self.id_of_symbol.get(symbol)

            if symbol_id is None:
                if used:
                    self.undefined_symbols.add(symbol)

                symbol_id = 0

        if used and symbol_id in self.unexpected_ids:
            self.unexpected_used_symbols.add(symbol)

        return symbol_id

    def is_shared_symbol(self, ion_symbol):
        symbol_id = self.get_id(ion_symbol, used=False)
        return symbol_id > 0 and symbol_id < self.local_min_id

    def is_local_symbol(self, ion_symbol):
        return self.get_id(ion_symbol, used=False) >= self.local_min_id

    def replace_local_symbols(self, new_symbols):
        self.discard_local_symbols()
        self.import_symbols(new_symbols)

    def get_local_symbols(self):
        return self.symbols[self.local_min_id-1:]

    def discard_local_symbols(self):
        symbol_id = self.local_min_id
        for symbol in self.symbols[self.local_min_id-1:]:
            self.id_of_symbol.pop(symbol)
            self.symbol_of_id.pop(symbol_id)
            symbol_id += 1

        self.symbols = self.symbols[:self.local_min_id-1]

    def create_import(self):
        if not self.symbols:
            return None

        symbol_table_data = IonStruct(
            IS("$8"), len(self.symbols),
            IS("$6"), [IonStruct(
                IS("$4"), table_import.name,
                IS("$5"), table_import.version,
                IS("$8"), table_import.max_id) for table_import in self.table_imports],
            IS("$7"), self.symbols[self.local_min_id-1:])

        return IonAnnotation([IS("$3")], symbol_table_data)

    def report(self):
        if self.reported:
            return

        context = ("%s: " % self.context) if self.context else ""

        if self.unexpected_used_symbols:
            self.log.warning("%sUnexpected Ion symbols used: %s" % (context, list_symbols(self.unexpected_used_symbols)))

        if self.undefined_symbols and not self.ignore_undef:
            self.log.error("%sUndefined Ion symbols found: %s" % (context,
                    ", ".join([quote_name(s) for s in sorted(self.undefined_symbols)])))

        if self.undefined_ids:
            self.log.error("%sUndefined Ion symbol IDs found: %s" % (context, list_symbols(self.undefined_ids)))

        self.reported = True

def add_shared_symbol_table(symbol_table):
    shared_symbol_tables[(symbol_table.name, symbol_table.version)] = symbol_table

    if (symbol_table.name not in shared_symbol_tables or
            symbol_table.version > shared_symbol_tables[(symbol_table.name, None)].version):
        shared_symbol_tables[(symbol_table.name, None)] = symbol_table

def report_local_symbol_tables():
    for symtab in local_symbol_tables:
        symtab.report()

