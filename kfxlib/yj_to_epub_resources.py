from __future__ import (unicode_literals, division, absolute_import, print_function)

import logging
from PIL import Image
import posixpath
import re
import cStringIO
import urllib

from .misc import (EXT_OF_MIMETYPE, MIMETYPE_OF_EXT, RESOURCE_TYPE_OF_EXT, UUID_MATCH_RE,
            convert_jxr_to_tiff, convert_pdf_to_jpeg, exception_string, font_file_ext, urlrelpath)
from .yj_structure import SYMBOL_FORMATS

__license__   = "GPL v3"
__copyright__ = "2018, John Howell <jhowell@acm.org>"

USE_HIGHEST_RESOLUTION_IMAGE_VARIANT = True

FIX_JPEG_XR = True

FIX_PDF = True

IMAGE_QUALITY = 90

class ManifestEntry(object):
    def __init__(self, filename, opf_properties=set(), linear=None):
        self.filename = filename
        self.opf_properties = set(opf_properties)
        self.linear = linear

class OutputFile(object):
    def __init__(self, binary_data, mimetype, height=None, width=None):
        self.binary_data = binary_data
        self.mimetype = mimetype
        self.height = height
        self.width = width

class EPUBResources(object):

    def process_external_resource(self, resource_name, referred=False, save=True, is_variant=False, plugin=False):
        if referred and resource_name in self.used_external_resources:
            return None

        self.used_external_resources.add(resource_name)

        resource = self.get_fragment(ftype="$164", fid=resource_name, delete=False).copy()

        if resource.pop("$175", "") != resource_name:
            raise Exception("Name of resource %s is incorrect" % resource_name)

        format = resource.pop("$161")

        if format in SYMBOL_FORMATS:
            format_ext = "." + SYMBOL_FORMATS[format]
        else:
            self.log.error("Unexpected resource format: %s" % format)
            format_ext = ".bin"

        if plugin and format != "$287":
            self.log.error("Unexpected plugin resource format: %s" % format)

        resource_height = resource.pop("$423", None)
        resource_width = resource.pop("$422", None)

        if "$636" in resource:

            tile_height = resource.pop("$638")
            tile_width = resource.pop("$637")

            logging.disable(logging.DEBUG)

            full_image = Image.new("RGBA", (resource_width, resource_height))

            for y,row in enumerate(resource.pop("$636")):
                for x,location in enumerate(row):
                    tile_raw_media = self.locate_raw_media(location)
                    tile = Image.open(cStringIO.StringIO(tile_raw_media))
                    full_image.paste(tile, (x * tile_width, y * tile_height))

            if full_image.size != (resource_width, resource_height):
                self.log.error("Combined tiled image size is %s but should be (%d, %d)" % (
                        unicode(full_image.size), resource_width, resource_height))

            outfile = cStringIO.StringIO()
            full_image.save(outfile, "jpeg" if format_ext == ".jpg" else format_ext[1:], quality=IMAGE_QUALITY)
            raw_media = outfile.getvalue()

            logging.disable(logging.NOTSET)

            location = location.partition("-tile")[0]

        else:
            location = resource.pop("$165")
            search_path = resource.pop("$166", location)
            if search_path != location:
                self.log.error("Image resource %s has location %s != search_path %s" % (resource_name, location, search_path))

            raw_media = self.locate_raw_media(location)

        if format == "$287" and (not plugin) and "." in location:
            format_ext = "." + location.rpartition(".")[2]

        extension = EXT_OF_MIMETYPE.get(resource.pop("$162", None), format_ext)
        if not location.endswith(extension): location = location.partition(".")[0] + extension

        resource.pop("$597", None)
        resource.pop("$67", None)
        resource.pop("$66", None)
        resource.pop("$57", None)
        resource.pop("$56", None)

        for rr in resource.pop("$167", []):
            self.process_external_resource(rr, referred=True, save=False) # ignore

        if "$214" in resource:
            self.process_external_resource(resource.pop("$214"), referred=True, save=False)

        if FIX_JPEG_XR and (format == "$548"):
            try:
                tiff_data = convert_jxr_to_tiff(self.log, raw_media)
            except Exception as e:
                self.log.error("Exception during conversion of JPEG-XR '%s' to TIFF: %s" % (location, exception_string(e)))
            else:
                logging.disable(logging.DEBUG)
                img = Image.open(cStringIO.StringIO(tiff_data))
                ofmt,oext = ("PNG", ".png") if img.mode == "RGBA" else ("JPEG", ".jpg")
                outfile = cStringIO.StringIO()
                img.save(outfile, ofmt, quality=IMAGE_QUALITY)
                logging.disable(logging.NOTSET)
                raw_media = outfile.getvalue()
                location = location.rpartition(".")[0] + oext

        if FIX_PDF and (format == "$565") and "$564" in resource:
            page_num = resource["$564"] + 1
            try:
                jpeg_data = convert_pdf_to_jpeg(self.log, raw_media, page_num)
            except Exception as e:
                self.log.error("Exception during conversion of PDF '%s' page %d to JPEG: %s" % (location, page_num, exception_string(e)))
            else:
                raw_media = jpeg_data
                location = "%s-page%d.jpg" % (location.rpartition(".")[0], page_num)
                resource.pop("$564")

        filename = self.resource_location_filename(location, self.IMAGE_FILEPATH)

        if is_variant:
            self.check_empty(resource, "resource %s" % resource_name)
            return (filename, raw_media, resource_width, resource_height)

        for rr in resource.pop("$635", []):
            if USE_HIGHEST_RESOLUTION_IMAGE_VARIANT and save:
                variant = self.process_external_resource(rr, referred=True, is_variant=True)
                if variant is not None:
                    v_filename, v_raw_media, v_width, v_height = variant
                    if v_width > resource_width and v_height > resource_height:
                        if self.DEBUG: self.log.info("Replacing image %s (%dx%d) with HD variant %s (%dx%d)" % (
                            filename, resource_width, resource_height, v_filename, v_width, v_height))
                        filename, raw_media, resource_width, resource_height = variant
            else:
                self.process_external_resource(rr, referred=True, save=False)

        if save and (filename not in self.oebps_files):
            self.oebps_files[filename] = OutputFile(raw_media, self.mimetype_of_filename(filename),
                            height=resource_height, width=resource_width)
            self.manifest.append(ManifestEntry(filename))

        if "$564" in resource:
            filename += "#page=%d" % (resource.pop("$564") + 1)

        self.check_empty(resource, "resource %s" % resource_name)

        return filename if save else raw_media

    def locate_raw_media(self, location, report_missing=True):
        try:
            raw_media = self.book_data["$417"][location]
            self.used_raw_media.add(location)
        except:
            if report_missing:
                self.log.error("Missing bcRawMedia %s" % location)

            raw_media = b""

        return raw_media

    def resource_location_filename(self, location, filepath_template):

        if location in self.location_filenames:
            return self.location_filenames[location]

        if location.startswith("/"):
            location = "_" + location[1:]

        safe_location = re.sub(r"[^A-Za-z0-9_/\.\-]", "_", location)
        safe_location = safe_location.replace("//", "/x/")

        path,sep,name = safe_location.rpartition("/")
        path += sep

        root,sep,ext = name.rpartition(".")
        ext = sep + ext
        resource_type = RESOURCE_TYPE_OF_EXT.get(ext, "resource")

        if self.new_book_symbol_format:

            root = resource_type + root[22:]
        else:
            root = re.sub(r"^(res|resource)_[0-9]_[0-9]_[0-9a-f]{14,16}_[0-9a-f]{1,4}_", "", root, count=1)
            root = re.sub(UUID_MATCH_RE, "", root, count=1)
            if (not root) or re.match(r"^[0-9]+$", root):
                root = resource_type + root

        for prefix in ["resource/", filepath_template[1:].partition("/")[0] + "/"]:
            if path.startswith(prefix):
                path = path[len(prefix):]

        safe_filename = filepath_template % ("%s%s%s" % (path, root, ext))

        unique_count = 0
        oebps_files_lower = set([n.lower() for n in self.oebps_files.keys()])

        while safe_filename.lower() in oebps_files_lower:
            safe_filename = filepath_template % ("%s%s-%d%s" % (path, root, unique_count, ext))
            unique_count += 1

        self.location_filenames[location] = safe_filename
        return safe_filename

    def process_fonts(self):

        fonts = self.book_data.pop("$262", {})
        raw_fonts = self.book_data.pop("$418", {})
        used_fonts = {}

        for font in fonts.values():
            location = font.pop("$165")

            if location in used_fonts:
                font["src"] = "url(\"%s\")" % urllib.quote(urlrelpath(used_fonts[location], ref_from=self.STYLES_CSS_FILEPATH))
            elif location in raw_fonts:
                raw_font = raw_fonts.pop(location)

                filename = location
                if "." not in filename:

                    ext = font_file_ext(raw_font, default="bin")
                    if ext == "bin":
                        self.log.error("Font %s has unknown type (possibly obfuscated)" % filename)

                    filename = "%s.%s" % (filename, ext)

                filename = self.resource_location_filename(filename, self.FONT_FILEPATH)

                if filename not in self.oebps_files:
                    self.oebps_files[filename] = OutputFile(raw_font, self.mimetype_of_filename(filename))
                    self.manifest.append(ManifestEntry(filename))

                font["src"] = "url(\"%s\")" % urlrelpath(urllib.quote(filename), ref_from=self.STYLES_CSS_FILEPATH)
                used_fonts[location] = filename
            else:
                self.log.error("Missing bcRawFont %s" % location)

            for prop in ["$15", "$12", "$13"]:
                if prop in font and font[prop] == "$350":
                    font.pop(prop)

            self.fix_font_name(font["$11"], add=True)
            self.font_faces.append(self.convert_yj_properties(font))

        for location in raw_fonts:
            self.log.warning("Unused font file: %s" % location)
            filename = self.resource_location_filename(location, self.FONT_FILEPATH)
            self.oebps_files[filename] = OutputFile(raw_fonts[location], self.mimetype_of_filename(filename))
            self.manifest.append(ManifestEntry(filename))

    def mimetype_of_filename(self, filename, default="application/octet-stream"):
        ext = posixpath.splitext("x" + filename)[1].lower()

        if ext == ".otf" or ext == ".ttf":
            if self.generate_epub31:
                return "application/font-sfnt"

            if self.generate_epub3:
                return "application/vnd.ms-opentype"

        return MIMETYPE_OF_EXT.get(ext, default)

