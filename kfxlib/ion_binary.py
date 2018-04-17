from __future__ import (unicode_literals, division, absolute_import, print_function)

import decimal
import hashlib
import struct

from .ion import (
            ion_type, IonAnnotation, IonBLOB, IonBool, IonCLOB, IonDecimal, IonFloat, IonInt,
            IonList, IonNop, IonNull, IonSExp, IonString, IonStruct, IonSymbol, IonTimestamp, IonTimestampTZ,
            IonFormat, ION_TIMESTAMP_Y, ION_TIMESTAMP_YM, ION_TIMESTAMP_YMD, ION_TIMESTAMP_YMDHM,
            ION_TIMESTAMP_YMDHMS, ION_TIMESTAMP_YMDHMSF)
from .misc import (
            gunzip, hex_string, type_name)

__license__   = "GPL v3"
__copyright__ = "2018, John Howell <jhowell@acm.org>"

DEBUG = False

class IonBinary(IonFormat):
    version_marker = 0xe0

    signature = chr(version_marker) + chr(IonFormat.major_version) + chr(IonFormat.minor_version) + chr(0xea)

    gzip_signature = b"\x1f\x8b\x08"
    drmion_signature = b"\xeaDRMION\xee"

    def deserialize_multiple_values(self, data, unzip=False):
        if unzip:
            data = gunzip(data)

        values = IonBinaryValue(self).deserialize_multiple_values(data)

        return values

    def serialize_multiple_values(self, values):
        return IonBinaryValue(self).serialize_multiple_values(values)

class IonBinaryValue(object):

    SORTED_STRUCT_FLAG = 1
    VARIABLE_LEN_FLAG = 14
    NULL_FLAG = 15

    def __init__(self, context):
        self.log = context.log
        self.symtab = context.symtab
        self.import_symbols = context.import_symbols

    def serialize_multiple_values(self, values):
        serial = Serializer()
        serial.append(IonBinary.signature)

        for value in values:
            serial.append(IonBinaryValue(self).serialize_value_by_type(value))

        return serial.serialize()

    def deserialize_multiple_values(self, data):
        if DEBUG: self.log.debug("decoding: %s" % hex_string(data[:1000]))

        ion_signature = data[:4]
        if ion_signature != IonBinary.signature:
            raise Exception("Ion signature is incorrect (%s)" % hex_string(ion_signature))

        serial = Deserializer(data[4:])
        result = []
        while len(serial):
            if serial.extract(1, advance=False) == IonBinary.version_marker:

                ion_signature = serial.unpack("4s")
                if ion_signature != IonBinary.signature:
                    raise Exception("Embedded Ion signature is incorrect (%s)" % hex_string(ion_signature))
            else:
                value = IonBinaryValue(self).deserialize(serial)

                if (self.import_symbols and isinstance(value, IonAnnotation) and
                        value.annotations[0] in ["$3", "$9"]):
                    self.symtab.create_symbol_table(value.annotations[0], value.value)

                if not isinstance(value, IonNop):
                    result.append(value)

        return result

    def serialize_value_by_type(self, value):
        handler = ION_TYPE_HANDLERS[ion_type(value)]
        return handler(self).serialize_by_type(value)

    def serialize_by_type(self, value):

        return self.add_descriptor(self.serialize_value(value))

    def descriptor(self, flag):
        if flag < 0 or flag > 0x0f: raise Exception("Serialize bad descriptor flag: %d" % flag)
        return chr((self.value_signature << 4) + flag)

    def add_descriptor(self, data):
        length = len(data)

        if length < IonBinaryValue.VARIABLE_LEN_FLAG:
            return self.descriptor(length) + data

        return self.descriptor(IonBinaryValue.VARIABLE_LEN_FLAG) + BinaryIonVLUInt(self).serialize_value(length) + data

    def deserialize(self, serial):

        descriptor = serial.unpack("B")
        if descriptor == IonBinary.version_marker:
            raise Exception("Unexpected Ion version marker within data stream")

        signature = descriptor >> 4
        flag = descriptor & 0x0f
        if DEBUG: self.log.debug("IonBinary 0x%02x: signature=%d (%s) flag=%d data=%s" % (
                    descriptor, signature, ION_SIGNATURE_HANDLERS[signature].__name__, flag, hex_string(serial.extract(advance=False)[:16])))

        return ION_SIGNATURE_HANDLERS[signature](self).deserialize_value(flag, serial)

    def deserialize_value(self, flag, serial):
        if flag == IonBinaryValue.NULL_FLAG:
            self.log.error("IonBinaryValue: Deserialized null of type %s" % type_name(self))
            return None

        return self.deserialize_data(self.deserialize_get_data(flag, serial))

    def deserialize_get_data(self, flag, serial):
        if flag == IonBinaryValue.NULL_FLAG:
            raise Exception("deserialize_get_data unexpected null value of type %s" % type_name(self))

        if flag == IonBinaryValue.VARIABLE_LEN_FLAG:
            length = BinaryIonVLUInt(self).deserialize(serial)
        else:
            length = flag

        return serial.extract(length)

class BinaryIonNull(IonBinaryValue):

    value_signature = 0

    def serialize_by_type(self, value):
        return self.descriptor(IonBinaryValue.NULL_FLAG)

    def deserialize_value(self, flag, serial):
        if flag == IonBinaryValue.NULL_FLAG:
            return None

        self.deserialize_get_data(flag, serial)
        return IonNop()

class BinaryIonBool(IonBinaryValue):

    value_signature = 1

    def serialize_by_type(self, value):
        return self.descriptor(1 if value else 0)

    def deserialize_value(self, flag, serial):
        if flag == IonBinaryValue.NULL_FLAG:
            self.log.error("Deserialized null of type %s" % type_name(self))
            return None

        if flag > 1:
            raise Exception("BinaryIonBool: Unknown IonBool flag value: %d" % flag)

        return flag != 0

class BinaryIonInt(IonBinaryValue):

    def serialize_by_type(self, value):
        return BinaryIonPosInt(self).serialize_by_type(value) if value >= 0 else BinaryIonNegInt(self).serialize_by_type(value)

class BinaryIonPosInt(IonBinaryValue):

    value_signature = 2

    def serialize_value(self, value):
        if value < 0: raise Exception("Cannot serialize negative value as BinaryIonPosInt: %d" % value)

        return ltrim0(struct.pack(b">Q", value))

    def deserialize_data(self, data):
        if len(data) > 0 and ord(data[0]) == 0:
            self.log.warning("BinaryIonPosInt data padded with 0x00")

        return struct.unpack_from(b">Q", lpad0(data, 8))[0]

class BinaryIonNegInt(IonBinaryValue):

    value_signature = 3

    def serialize_value(self, value):
        if value >= 0: raise Exception("Cannot serialize non-negative value as BinaryIonNegInt: %d" % value)

        return ltrim0(struct.pack(b">Q", -value))

    def deserialize_data(self, data):
        if len(data) == 0:
            self.log.error("BinaryIonNegInt has no data")

        if ord(data[0]) == 0:
            self.log.error("BinaryIonNegInt data starts with 0x00: %s" % hex_string(data))

        return -(struct.unpack_from(b">Q", lpad0(data, 8))[0])

class BinaryIonFloat(IonBinaryValue):

    value_signature = 4

    def serialize_value(self, value):
        if value == 0.0:
            return b""

        return struct.pack(b">d", value)

    def deserialize_data(self, data):
        if len(data) == 0:
            return float(0.0)

        if len(data) == 4:
            return struct.unpack_from(b">f", data)[0]

        if len(data) == 8:
            return struct.unpack_from(b">d", data)[0]

        raise Exception("IonFloat unexpected data length: %s" % hex_string(data))

class BinaryIonDecimal(IonBinaryValue):

    value_signature = 5

    def serialize_value(self, value):
        if value.is_zero(): return b""

        vt = value.as_tuple()
        return (BinaryIonVLSInt(self).serialize_value(vt.exponent) +
                BinaryIonSInt(self).serialize_value(combine_decimal_digits(vt.digits, vt.sign)))

    def deserialize_data(self, data):
        if len(data) == 0: return decimal.Decimal(0)

        serial = Deserializer(data)
        exponent = BinaryIonVLSInt(self).deserialize(serial)
        magnitude = BinaryIonSInt(self).deserialize_data(serial.extract())
        return decimal.Decimal(magnitude) * (decimal.Decimal(10) ** exponent)

class BinaryIonTimestamp(IonBinaryValue):

    value_signature = 6

    def serialize_value(self, value):
        serial = Serializer()

        if isinstance(value.tzinfo, IonTimestampTZ):
            offset_minutes = value.tzinfo.offset_minutes()
            format_len = len(value.tzinfo.format())
            fraction_exponent = -value.tzinfo.fraction_len()
        else:
            offset_minutes = int(value.utcoffset().total_seconds()) // 60 if value.utcoffset() is not None else None
            format_len = len(ION_TIMESTAMP_YMDHMSF)
            fraction_exponent = -3

        serial.append(BinaryIonVLSInt(self).serialize_value(offset_minutes))
        serial.append(BinaryIonVLUInt(self).serialize_value(value.year))

        if format_len >= len(ION_TIMESTAMP_YM):
            serial.append(BinaryIonVLUInt(self).serialize_value(value.month))

            if format_len >= len(ION_TIMESTAMP_YMD):
                serial.append(BinaryIonVLUInt(self).serialize_value(value.day))

                if format_len >= len(ION_TIMESTAMP_YMDHM):
                    serial.append(BinaryIonVLUInt(self).serialize_value(value.hour))
                    serial.append(BinaryIonVLUInt(self).serialize_value(value.minute))

                    if format_len >= len(ION_TIMESTAMP_YMDHMS):
                        serial.append(BinaryIonVLUInt(self).serialize_value(value.second))

                        if format_len >= len(ION_TIMESTAMP_YMDHMSF):
                            serial.append(BinaryIonVLSInt(self).serialize_value(fraction_exponent))
                            serial.append(BinaryIonSInt(self).serialize_value(
                                    (value.microsecond * int(10 ** -fraction_exponent)) // 1000000))

        return serial.serialize()

    def deserialize_data(self, data):
        serial = Deserializer(data)

        offset_minutes = BinaryIonVLSInt(self).deserialize(serial, allow_minus_zero=True)
        year = BinaryIonVLUInt(self).deserialize(serial)
        month = BinaryIonVLUInt(self).deserialize(serial) if len(serial) > 0 else None
        day = BinaryIonVLUInt(self).deserialize(serial) if len(serial) > 0 else None
        hour = BinaryIonVLUInt(self).deserialize(serial) if len(serial) > 0 else None
        minute = BinaryIonVLUInt(self).deserialize(serial) if len(serial) > 0 else None
        second = BinaryIonVLUInt(self).deserialize(serial) if len(serial) > 0 else None

        if len(serial) > 0:
            fraction_exponent = BinaryIonVLSInt(self).deserialize(serial)

            fraction_coefficient = BinaryIonSInt(self).deserialize_data(serial.extract()) if len(serial) > 0 else 0

            if fraction_coefficient == 0 and fraction_exponent > -1:
                microsecond = None
            else:
                if fraction_exponent < -6 or fraction_exponent > -1:
                    self.log.error("Unexpected IonTimestamp fraction exponent %d coefficient %d: %s" % (
                            fraction_exponent, fraction_coefficient, hex_string(data)))

                microsecond = (fraction_coefficient * 1000000) // int(10 ** -fraction_exponent)

                if microsecond < 0 or microsecond > 999999:
                    self.log.error("Incorrect IonTimestamp fraction %d usec: %s" % (microsecond, hex_string(data)))
                    microsecond = None
                    fraction_exponent = 0
        else:
            microsecond = None
            fraction_exponent = 0

        if month is None:
            format = ION_TIMESTAMP_Y
            offset_minutes = None
        elif day is None:
            format = ION_TIMESTAMP_YM
            offset_minutes = None
        elif hour is None:
            format = ION_TIMESTAMP_YMD
            offset_minutes = None
        elif second is None:
            format = ION_TIMESTAMP_YMDHM
        elif microsecond is None:
            format = ION_TIMESTAMP_YMDHMS
        else:
            format = ION_TIMESTAMP_YMDHMSF

        return IonTimestamp(year,
                    month if month is not None else 1,
                    day if day is not None else 1,
                    hour if hour is not None else 0,
                    minute if hour is not None else 0,
                    second if second is not None else 0,
                    microsecond if microsecond is not None else 0,
                    IonTimestampTZ(offset_minutes, format, -fraction_exponent))

class BinaryIonSymbol(IonBinaryValue):

    value_signature = 7

    def serialize_value(self, value):
        symbol_id = self.symtab.get_id(value)
        if not symbol_id: raise Exception("attempt to serialize undefined symbol %s" % repr(value))

        return BinaryIonPosInt(self).serialize_value(symbol_id)

    def deserialize_data(self, data):
        return self.symtab.get_symbol(BinaryIonPosInt(self).deserialize_data(data))

class BinaryIonString(IonBinaryValue):

    value_signature = 8

    def serialize_value(self, value):
        return value.encode("utf-8")

    def deserialize_data(self, data):
        return data.decode("utf-8")

class BinaryIonCLOB(IonBinaryValue):

    value_signature = 9

    def serialize_value(self, value):
        self.log.error("Serialize CLOB")
        return str(value)

    def deserialize_data(self, data):
        self.log.error("Deserialize CLOB")
        return IonCLOB(data)

class BinaryIonBLOB(IonBinaryValue):

    value_signature = 10

    def serialize_value(self, value):
        return str(value)

    def deserialize_data(self, data):
        return IonBLOB(data)

class BinaryIonList(IonBinaryValue):

    value_signature = 11

    def serialize_value(self, value):
        serial = Serializer()
        for val in value:
            serial.append(IonBinaryValue(self).serialize_value_by_type(val))

        return serial.serialize()

    def deserialize_data(self, data, top_level=False):
        serial = Deserializer(data)
        result = []
        while len(serial):
            value = IonBinaryValue(self).deserialize(serial)

            if not isinstance(value, IonNop):
                result.append(value)

        return result

class BinaryIonSExp(IonBinaryValue):

    value_signature = 12

    def serialize_value(self, value):
        return BinaryIonList(self).serialize_value(list(value))

    def deserialize_data(self, data):
        return IonSExp(BinaryIonList(self).deserialize_data(data))

class BinaryIonStruct(IonBinaryValue):

    value_signature = 13

    def serialize_value(self, value):
        serial = Serializer()

        for key,val in value.items():
            serial.append(BinaryIonVLUInt(self).serialize_value(self.symtab.get_id(key)))
            serial.append(IonBinaryValue(self).serialize_value_by_type(val))

        return serial.serialize()

    def deserialize_value(self, flag, serial):
        if flag == IonBinaryValue.NULL_FLAG:
            self.log.error("Deserialized null of type %s" % type_name(self))
            return None

        if flag == IonBinaryValue.SORTED_STRUCT_FLAG:

            self.log.error("BinaryIonStruct: Sorted IonStruct encountered")
            flag = IonBinaryValue.VARIABLE_LEN_FLAG

        serial2 = Deserializer(self.deserialize_get_data(flag, serial))
        result = IonStruct()

        while len(serial2):
            id_symbol = self.symtab.get_symbol(BinaryIonVLUInt(self).deserialize(serial2))

            value = IonBinaryValue(self).deserialize(serial2)
            if DEBUG: self.log.debug("IonStruct: %s = %s" % (repr(id_symbol), repr(value)))

            if not isinstance(value, IonNop):
                if id_symbol in result:

                    self.log.error("BinaryIonStruct: Duplicate field name %s" % id_symbol)

                result[id_symbol] = value

        return result

class BinaryIonAnnotation(IonBinaryValue):

    value_signature = 14

    def serialize_value(self, value):
        if not value.annotations: raise Exception("Serializing IonAnnotation without annotations")

        serial = Serializer()

        annotation_data = Serializer()
        for annotation in value.annotations:
            annotation_data.append(BinaryIonVLUInt(self).serialize_value(self.symtab.get_id(annotation)))

        serial.append(BinaryIonVLUInt(self).serialize_value(len(annotation_data)))
        serial.append(annotation_data.serialize())

        serial.append(IonBinaryValue(self).serialize_value_by_type(value.value))

        return serial.serialize()

    def deserialize_data(self, data):
        serial = Deserializer(data)

        annotation_length = BinaryIonVLUInt(self).deserialize(serial)
        annotation_data = Deserializer(serial.extract(annotation_length))

        ion_value = IonBinaryValue(self).deserialize(serial)
        if len(serial): raise Exception("IonAnnotation has excess data: %s" % hex_string(serial.extract()))

        annotations = []
        while len(annotation_data):
            annotations.append(self.symtab.get_symbol(BinaryIonVLUInt(self).deserialize(annotation_data)))

        if len(annotations) == 0:
            raise Exception("IonAnnotation has no annotations")

        if len(annotations) != 1:
            self.log.error("IonAnnotation has %d annotations" % len(annotations))

        return IonAnnotation(annotations, ion_value)

class BinaryIonReserved(IonBinaryValue):

    value_signature = 15

    def deserialize_data(self, data):
        raise Exception("Deserialize reserved ion value signature %d" % self.value_signature)

class BinaryIonSInt(IonBinaryValue):

    value_signature = None

    def serialize_value(self, value):
        data = ltrim0x(struct.pack(b">Q", abs(value)))

        if value < 0:
            data = or_first_byte(data, 0x80)

        return data

    def deserialize_data(self, data):
        if len(data) == 0: return 0

        if (ord(data[0]) & 0x80) != 0:
            return -(struct.unpack_from(b">Q", lpad0(and_first_byte(data, 0x7f), 8))[0])

        return struct.unpack_from(b">Q", lpad0(data, 8))[0]

class BinaryIonVLUInt(IonBinaryValue):

    value_signature = None

    def serialize_value(self, value):
        if value < 0: raise Exception("Cannot serialize negative value as IonVLUInt: %d" % value)

        data = chr((value & 0x7f) + 0x80)
        while True:
            value = value >> 7
            if value == 0:
                return data

            data = chr(value & 0x7f) + data

    def deserialize(self, serial):
        value = 0
        while True:
            i = serial.unpack("B")
            value = (value << 7) | (i & 0x7f)

            if i >= 0x80:
                return value

            if value == 0:
                self.log.warning("IonVLUInt padded with 0x00")

            if value > 0x7fffffffffffff:
                raise Exception("IonVLUInt data value is too large, missing terminator")

class BinaryIonVLSInt(IonBinaryValue):

    value_signature = None

    def serialize_value(self, value):
        if value is None:
            return chr(0xc0)

        data = BinaryIonVLUInt(self).serialize_value(abs(value))

        if ord(data[0]) & 0x40:
            data = chr(0) + data

        if value < 0:
            data = or_first_byte(data, 0x40)

        return data

    def deserialize(self, serial, allow_minus_zero=False):
        first = serial.unpack("B")
        byte = first & 0xbf
        data = chr(byte) if byte != 0 else b""

        while (byte & 0x80) == 0:
            byte = serial.unpack("B")
            data += chr(byte)

        value = BinaryIonVLUInt(self).deserialize(Deserializer(data))

        if first & 0x40:
            if value:
                value = -value
            elif allow_minus_zero:
                value = None
            else:
                self.log.error("BinaryIonVLSInt deserialized unexpected -0 value")

        return value

ION_SIGNATURE_HANDLERS = {
    BinaryIonNull.value_signature: BinaryIonNull,
    BinaryIonBool.value_signature: BinaryIonBool,
    BinaryIonPosInt.value_signature: BinaryIonPosInt,
    BinaryIonNegInt.value_signature: BinaryIonNegInt,
    BinaryIonFloat.value_signature: BinaryIonFloat,
    BinaryIonDecimal.value_signature: BinaryIonDecimal,
    BinaryIonTimestamp.value_signature: BinaryIonTimestamp,
    BinaryIonSymbol.value_signature: BinaryIonSymbol,
    BinaryIonString.value_signature: BinaryIonString,
    BinaryIonCLOB.value_signature: BinaryIonCLOB,
    BinaryIonBLOB.value_signature: BinaryIonBLOB,
    BinaryIonList.value_signature: BinaryIonList,
    BinaryIonSExp.value_signature: BinaryIonSExp,
    BinaryIonStruct.value_signature: BinaryIonStruct,
    BinaryIonAnnotation.value_signature: BinaryIonAnnotation,
    BinaryIonReserved.value_signature: BinaryIonReserved,
    }

ION_TYPE_HANDLERS = {
    IonAnnotation: BinaryIonAnnotation,
    IonBLOB: BinaryIonBLOB,
    IonBool: BinaryIonBool,
    IonCLOB: BinaryIonCLOB,
    IonDecimal: BinaryIonDecimal,
    IonFloat: BinaryIonFloat,
    IonInt: BinaryIonInt,
    IonList: BinaryIonList,
    IonNull: BinaryIonNull,
    IonSExp: BinaryIonSExp,
    IonString: BinaryIonString,
    IonStruct: BinaryIonStruct,
    IonSymbol: BinaryIonSymbol,
    IonTimestamp: BinaryIonTimestamp,
    }

def lpad0(data, size):

    if len(data) > size:

        extra = len(data) - size
        if data[:size] != chr(0) * extra:
            raise Exception("lpad0, length (%d) > max (%d): %s" % (len(data), size, hex_string(data)))

        return data[:size]

    return (chr(0) * (size - len(data)) + data)

def ltrim0(data):

    while len(data) and ord(data[0]) == 0:
        data = data[1:]

    return data

def ltrim0x(data):

    while len(data) and ord(data[0]) == 0:
        if len(data) > 1 and (ord(data[1]) & 0x80):
            break

        data = data[1:]

    return data

def combine_decimal_digits(digits, sign_negative):
    val = 0

    for digit in digits:
        val = (val * 10) + digit

    if sign_negative:
        val = -val

    return val

def and_first_byte(data, mask):
    return chr(ord(data[0]) & mask) + data[1:]

def or_first_byte(data, mask):
    return chr(ord(data[0]) | mask) + data[1:]

class Serializer(object):
    def __init__(self):
        self.buffers = []
        self.length = 0

    def pack(self, fmt, *values):
        fmt = fmt.encode("ascii")
        fmt_pos = (fmt, len(self.buffers))
        self.append(struct.pack(fmt, *values))
        return fmt_pos

    def repack(self, fmt_pos, *values):
        fmt, position = fmt_pos
        self.buffers[position] = struct.pack(fmt, *values)

    def append(self, buf):
        if buf:
            self.buffers.append(buf)
            self.length += len(buf)

    def extend(self, serializer):
        self.buffers.extend(serializer.buffers)
        self.length += serializer.length

    def __len__(self):
        return self.length

    def serialize(self):
        return b"".join(self.buffers)

    def sha1(self):
        sha1 = hashlib.sha1()
        for buf in self.buffers: sha1.update(buf)
        return sha1.digest()

class Deserializer(object):
    def __init__(self, data):
        self.buffer = data
        self.offset = 0

    def unpack(self, fmt, advance=True):
        fmt = fmt.encode("ascii")
        result = struct.unpack_from(fmt, self.buffer, self.offset)[0]

        if advance: self.offset += struct.calcsize(fmt)
        return result

    def extract(self, size=None, upto=None, advance=True):
        if size is None:
            size = len(self) if upto is None else (upto - self.offset)

        data = self.buffer[self.offset:self.offset + size]

        if len(data) < size or size < 0:
            raise Exception("Deserializer: Insufficient data (need %d bytes, have %d bytes)" % (size, len(data)))

        if advance: self.offset += size
        return data

    def __len__(self):
        return len(self.buffer) - self.offset

