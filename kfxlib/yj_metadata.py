from __future__ import (unicode_literals, division, absolute_import, print_function)

from PIL import Image
import logging
import random
import string
import cStringIO

from .ion import (IS, IonBLOB, IonStruct, IonSymbol, ion_type, unannotated)
from .misc import (convert_pdf_to_jpeg, exception_string, list_symbols, quote_name)
from .yj_container import (YJFragment, YJFragmentKey)
from .yj_structure import (FORMAT_SYMBOLS, KFX_COVER_RESOURCE, METADATA_NAMES, METADATA_SYMBOLS, SYMBOL_FORMATS)
from .yj_versions import (is_known_feature, is_known_generator, is_known_metadata)

__license__   = "GPL v3"
__copyright__ = "2018, John Howell <jhowell@acm.org>"

cds = set()

class YJ_Metadata(object):
    def __init__(self, author_sort_fn=None, replace_existing_authors_with_sort=False):
        self.authors = []
        self.author_sort_fn = author_sort_name if author_sort_fn is None else author_sort_fn
        self.replace_existing_authors_with_sort = replace_existing_authors_with_sort
        self.title = self.cde_content_type = self.asin = self.cover_image_data = self.description = None
        self.issue_date = self.language = self.publisher = self.book_id = self.features = None

    def get_from_book(self, book):
        authors = []

        fragment = book.fragments.get("$490")
        if fragment is not None:
            for cm in fragment.value.get("$491", {}):
                if cm.get("$495", "") == "kindle_title_metadata":
                    for kv in cm.get("$258", []):
                        key = unicode(kv.get("$492", ""))
                        val = unicode(kv.get("$307", ""))

                        if key == "author":

                            authors.append(val)
                        elif key == "title":
                            self.title = val
                        elif key == "cde_content_type":
                            self.cde_content_type = val
                        elif key == "ASIN":
                            self.asin = val
                        elif key == "description":
                            self.description = val
                        elif key == "issue_date":
                            self.issue_date = val
                        elif key == "language":
                            self.language = val
                        elif key == "publisher":
                            self.publisher = val
                        elif key == "book_id":
                            self.book_id = val

        fragment = book.fragments.get("$258")
        if fragment is not None:
            for name,val in fragment.value.items():
                key = METADATA_NAMES.get(name, unicode(name))
                val = unicode(val)

                if key == "author" and not authors:

                    if " & " in val:
                        for author in val.split("&"):
                            authors.append(author.strip())
                    elif " and " in val:
                        auths = val.split(" and ")
                        if len(auths) == 2 and "," in auths[0] and "," not in auths[1]:
                            auths = auths[0].split(",") + [auths[1]]
                        for author in auths:
                            authors.append(author.strip())
                    elif val:
                        authors.append(val)

                elif key == "title" and not self.title:

                    self.title = val
                elif key == "cde_content_type" and not self.cde_content_type:
                    self.cde_content_type = val
                elif key == "ASIN" and not self.asin:
                    self.asin = val
                elif key == "description" and not self.description:
                    self.description = val
                elif key == "issue_date" and not self.issue_date:
                    self.issue_date = val
                elif key == "language" and not self.language:
                    self.language = val
                elif key == "publisher" and not self.publisher:
                    self.publisher = val

        self.authors = []
        for author in authors:
            author = unsort_author_name(author)
            if author and author not in self.authors:
                self.authors.append(author)

        cover_image_data = book.get_cover_image_data()
        if cover_image_data is not None:
            self.cover_image_data = cover_image_data

        self.features = book.get_features()

        return self

    def set_to_book(self, book):

        authors = [self.author_sort_fn(author) for author in self.authors] if self.authors is not None else None

        if self.asin is True:
            self.asin = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(32))

        book_metadata_fragment = book.fragments.get("$490")
        metadata_fragment = book.fragments.get("$258")

        if book_metadata_fragment is None and metadata_fragment is None:
            book.log.error("Cannot set metadata due to missing metadata fragments in book")

        if self.cover_image_data is not None and self.cover_image_data != book.get_cover_image_data():
            cover_image = book.set_cover_image_data(self.cover_image_data[0], self.cover_image_data[1])
        else:

            cover_image = None

        if book_metadata_fragment is not None:
            for cm in book_metadata_fragment.value.get("$491", {}):
                if cm.get("$495", "") == "kindle_title_metadata":
                    new_kv = []
                    for kv in cm.get("$258", []):
                        key = kv.get("$492", "")
                        val = kv.get("$307", "")

                        if key == "author" and self.replace_existing_authors_with_sort:

                            if authors is None:
                                authors = []

                            authors.append(self.author_sort_fn(val))

                        elif ((key == "author" and authors is not None) or
                                (key == "title" and self.title is not None) or
                                (key == "cde_content_type" and self.cde_content_type is not None) or
                                (key == "ASIN" and self.asin is not None) or
                                (key == "content_id" and self.asin is not None) or
                                (key == "cover_image" and cover_image is not None) or
                                (key == "description" and self.description is not None) or
                                (key == "issue_date" and self.issue_date is not None) or
                                (key == "language" and self.language is not None) or
                                (key == "publisher" and self.publisher is not None)):
                            pass

                        elif key:
                            new_kv.append((key, val))

                    if authors is not None:
                        for author in authors:
                            new_kv.append(("author", author))

                    if self.title is not None:
                        new_kv.append(("title", self.title))

                    if self.cde_content_type is not None:
                        new_kv.append(("cde_content_type", self.cde_content_type))

                    if self.asin is not None:
                        new_kv.append(("ASIN", self.asin))
                        new_kv.append(("content_id", self.asin))

                    if cover_image is not None:
                        new_kv.append(("cover_image", cover_image))

                    if self.description is not None:
                        new_kv.append(("description", self.description))

                    if self.issue_date is not None:
                        new_kv.append(("issue_date", self.issue_date))

                    if self.language is not None:
                        new_kv.append(("language", self.language))

                    if self.publisher is not None:
                        new_kv.append(("publisher", self.publisher))

                    cm[IS("$258")] = [IonStruct(IS("$492"), k, IS("$307"), v) for k,v in sorted(new_kv)]

        if metadata_fragment is not None:
            mdx = metadata_fragment.value

            if not (len(mdx) == 0 or (len(mdx) == 1 and "$169" in mdx)):
                if authors is not None:
                    mdx[IS("$222")] = " & ".join(authors)
                else:
                    mdx.pop("$222", None)

                if self.title is not None:
                    mdx[IS("$153")] = self.title
                else:
                    mdx.pop("$153", None)

                if self.cde_content_type is not None:
                    mdx[IS("$251")] = self.cde_content_type
                else:
                    mdx.pop("$251", None)

                if self.asin is not None:
                    mdx[IS("$224")] = self.asin
                else:
                    mdx.pop("$224", None)

                if cover_image is not None:
                    mdx[IS("$424")] = IS(cover_image)
                else:
                    mdx.pop("$424", None)

                if self.description is not None:
                    mdx[IS("$154")] = self.description
                else:
                    mdx.pop("$154", None)

                if self.issue_date is not None:
                    mdx[IS("$219")] = self.issue_date
                else:
                    mdx.pop("$219", None)

                if self.language is not None:
                    mdx[IS("$10")] = self.language
                else:
                    mdx.pop("$10", None)

                if self.publisher is not None:
                    mdx[IS("$232")] = self.publisher
                else:
                    mdx.pop("$232", None)

def author_sort_name(author):

    PERSON_SUFFIXES = {"phd", "md", "ba", "ma", "dds", "msts", "sr", "senior", "jr", "junior", "ii", "iii", "iv"}

    al = author.split()

    if len(al) < 2:
        return author

    if len(al) > 2 and al[-1].replace(".","").lower() in PERSON_SUFFIXES:
        if al[-2].endswith(","):
            al[-2] = al[-2][:-1]

        al = al[0:-2] + ["%s %s" % (al[-2], al[-1])]

    if "," in "".join(al):
        return author

    return al[-1] + ", " + " ".join(al[:-1])

def unsort_author_name(author):
    if ", " in author:
        last,sep,first = author.partition(", ")
        author = first + " " + last

    return author

class BookMetadata(object):
    def has_metadata(self):
        return (self.fragments.get(YJFragmentKey(ftype="$490")) is not None or
                self.fragments.get(YJFragmentKey(ftype="$258")) is not None)

    def has_cover_data(self):

        return self.get_cover_image_data() is not None

    def get_asset_id(self):
        return self.get_metadata_value("asset_id")

    @property
    def cde_type(self):

        if not hasattr(self, "_cached_cde_type"):
            self._cached_cde_type = self.get_metadata_value("cde_content_type")

        return self._cached_cde_type

    @property
    def is_magazine(self):
        return self.cde_type == "MAGZ"

    @property
    def is_sample(self):
        return self.cde_type == "EBSP"

    @property
    def is_textbook(self):

        if not hasattr(self, "_cached_is_textbook"):
            self._cached_is_textbook = self.get_metadata_value("yj_textbook", category="kindle_capability_metadata") is not None

        return self._cached_is_textbook

    @property
    def is_fixed_layout(self):

        if not hasattr(self, "_cached_is_fixed_layout"):
            self._cached_is_fixed_layout = self.get_metadata_value("yj_fixed_layout", "kindle_capability_metadata")

        return self._cached_is_fixed_layout

    @property
    def is_illustrated_layout(self):

        if not hasattr(self, "_cached_is_illustrated_layout"):
            self._cached_is_illustrated_layout = self.get_feature_value("yj.illustrated_layout") is not None

        return self._cached_is_illustrated_layout

    @property
    def is_kfx_v1(self):

        if not hasattr(self, "_cached_is_kfx_v1"):
            fragment = self.fragments.get("$270", first=True)
            self._cached_is_kfx_v1 = fragment.value.get("$5", 0) == 1 if fragment is not None else False

        return self._cached_is_kfx_v1

    def get_metadata_value(self, name, category="kindle_title_metadata", default=None):
        try:
            fragment = self.fragments.get("$490")
            if fragment is not None:
                for cm in fragment.value["$491"]:
                    if cm["$495"] == category:
                        for kv in cm["$258"]:
                            if kv["$492"] == name:
                                return kv["$307"]

            metadata_symbol = METADATA_SYMBOLS.get(name)
            if metadata_symbol is not None:
                fragment = self.fragments.get("$258")
                if fragment is not None and metadata_symbol in fragment.value:
                    return fragment.value[metadata_symbol]
        except:
            pass

        return default

    def get_feature_value(self, feature, namespace="com.amazon.yjconversion", default=None):
        if namespace == "format_capabilities":
            fragment = self.fragments.get("$593", first=True)
            if fragment is not None:
                for fc in fragment.value:
                    if fc.get("$492", "") == feature:
                        return fc.get("$5", "")
        else:
            fragment = self.fragments.get("$585", first=True)
            if fragment is not None:
                for cf in fragment.value.get("$590", []):
                    if cf.get("$586", "") == namespace and cf.get("$492", "") == feature:
                        vi = cf.get("$589", {}).get("$5", {})
                        major_version = vi.get("$587", "")
                        minor_version = vi.get("$588", "")
                        return major_version if not minor_version else "%d.%d" % (major_version, minor_version)

        return default

    def get_generators(self):
        generators = set()

        for fragment in self.fragments.get_all("$270"):
            if "$5" in fragment.value:
                max_id = self.symtab.local_min_id - 1
                local_yj_count = [sym.startswith("yj.") for sym in self.symtab.symbols[max_id:]].count(True)
                max_id_str = "%d.%d" % (max_id, local_yj_count) if local_yj_count else "%d" % max_id
                generators.add((fragment.value.get("$587", ""), fragment.value.get("$588", ""), max_id_str))

        return generators

    def get_features(self):
        features = set()

        for fragment in self.fragments.get_all("$593"):
            for fc in fragment.value:
                features.add(("format_capabilities", fc.get("$492", ""), fc.get("$5", "")))

        fragment = self.fragments.get("$585", first=True)
        if fragment is not None:
                for cf in fragment.value.get("$590", []):
                    vi = cf.get("$589", {}).get("$5", {})
                    major_version = vi.get("$587", "")
                    minor_version = vi.get("$588", "")
                    features.add((cf.get("$586", ""), cf.get("$492", ""),
                            major_version if not minor_version else "%d.%d" % (major_version, minor_version)))

        return features

    def report_features_and_metadata(self, unknown_only=False):
        report_generators = set()
        for generator in sorted(self.get_generators()):
            generator_version = "%s/%s/%s" % generator
            if not is_known_generator(generator):
                self.log.warning("Unknown kfxgen: %s" % generator_version)
            elif not unknown_only:
                report_generators.add(generator_version)

        if report_generators:
            self.log.info("kfxgen version: %s" % list_symbols(report_generators))

        report_features = set()
        for feature in sorted(self.get_features()):
            if is_known_feature(feature[0], feature[1], feature[2]):
                if not unknown_only:
                    report_features.add("%s-%s" % (feature[1], quote_name(unicode(feature[2]))))
            else:
                self.log.warning("Unknown %s feature: %s-%s" % (feature[0], feature[1], unicode(feature[2])))

        if report_features:
            self.log.info("Features: %s" % list_symbols(report_features))

        metadata = []
        fragment = self.fragments.get("$490", first=True)
        if fragment is not None:
            for cm in fragment.value.get("$491", {}):
                category = cm.get("$495", "")
                for kv in cm.get("$258", []):
                    metadata.append((category, kv.get("$492", ""), kv.get("$307", "")))

        fragment = self.fragments.get("$258", first=True)
        if fragment is not None:
            for name,val in fragment.value.items():
                name = METADATA_NAMES.get(name, unicode(name))
                if name == "reading_orders":
                    val = len(val)
                metadata.append(("metadata", name, val))

        report_metadata = set()
        for cat,key,val in sorted(metadata):
            if not is_known_metadata(cat, key, val):
                self.log.warning("Unknown %s: %s=%s" % (cat, key, unicode(val)))
            elif not unknown_only:
                if key == "cover_image":
                    try:

                        cover_resource = self.fragments[YJFragmentKey(ftype="$164", fid=val)].value
                        val = "%dx%d" % (cover_resource.get("$422", 0), cover_resource.get("$423", 0))
                        cover_format = SYMBOL_FORMATS[cover_resource["$161"]]
                        if cover_format != "jpg":
                            val += "-" + cover_format
                    except:
                        val = "..."

                elif key == "dictionary_lookup":
                    val = "%s-to-%s" % (val.get("$474", "?"), val.get("$163", "?"))

                elif key == "description" and len(val) > 20:
                    val = "..."

                report_metadata.add("%s=%s" % (key, quote_name(unicode(val))))

        if report_metadata:
            self.log.info("Metadata: %s" % list_symbols(report_metadata))

    def get_cover_image_data(self):

        cover_image_resource = self.get_metadata_value("cover_image")
        if not cover_image_resource:
            return None

        cover_resource = self.fragments.get(ftype="$164", fid=cover_image_resource)
        if cover_resource is None:
            return None

        cover_fmt = cover_resource.value["$161"]
        if ion_type(cover_fmt) is IonSymbol:
            cover_fmt = SYMBOL_FORMATS[cover_fmt]

        cover_raw_media = self.fragments.get(ftype="$417", fid=cover_resource.value["$165"])
        if cover_raw_media is None:
            return None

        return ("jpeg" if cover_fmt == "jpg" else cover_fmt, str(cover_raw_media.value))

    def set_cover_image_data(self, fmt, data, update_cover_section=True):
        fmt = fmt.lower()
        if fmt == "jpeg":
            fmt = "jpg"

        if fmt not in ["jpg", "png"]:
            raise Exception("Cannot set KFX cover image format to %s, must be JPEG or PNG" % fmt.upper())

        cover_image = self.get_metadata_value("cover_image")
        if cover_image is None:
            cover_image = KFX_COVER_RESOURCE
            cover_image_symbol = self.create_local_symbol(cover_image)
            self.fragments.append(YJFragment(ftype="$164", fid=cover_image_symbol,
                                    value=IonStruct(IS("$175"), cover_image_symbol)))

        cover_resource = self.update_image_resource_and_media(cover_image, data, fmt, update_cover_section)

        if "$214" in cover_resource:
            logging.disable(logging.DEBUG)
            cover_thumbnail = Image.open(cStringIO.StringIO(data))
            cover_thumbnail.thumbnail((512, 512), Image.ANTIALIAS)
            outfile = cStringIO.StringIO()
            cover_thumbnail.save(outfile, "jpeg" if fmt == "jpg" else fmt, quality=90)
            logging.disable(logging.NOTSET)
            thumbnail_data = outfile.getvalue()

            thumbnail_resource = unannotated(cover_resource["$214"])
            self.update_image_resource_and_media(unicode(thumbnail_resource), thumbnail_data, fmt)

        return cover_image

    def update_image_resource_and_media(self, resource_name, data, fmt, update_cover_section=False):
        cover_resource = self.fragments.get(ftype="$164", fid=resource_name).value

        cover_resource[IS("$161")] = IS(FORMAT_SYMBOLS[fmt])
        cover_resource[IS("$162")] = "image/" + fmt

        cover_resource.pop("$56", None)
        cover_resource.pop("$57", None)
        cover_resource.pop("$66", None)
        cover_resource.pop("$67", None)

        cover = Image.open(cStringIO.StringIO(data))
        width,height = cover.size

        orig_width = cover_resource.get("$422", 0)
        orig_height = cover_resource.get("$423", 0)

        cover_resource[IS("$422")] = width
        cover_resource[IS("$423")] = height

        if "$165" in cover_resource:
            self.fragments[YJFragmentKey(ftype="$417", fid=cover_resource["$165"])].value = IonBLOB(data)
        else:
            location = "%s.%s" % (resource_name, fmt)
            cover_resource[IS("$165")] = location
            self.fragments.append(YJFragment(ftype="$417", fid=self.create_local_symbol(location), value=IonBLOB(data)))

        if update_cover_section and (width != orig_width or height != orig_height):
            section_updated = False
            if self.locate_cover_image_resource_from_content() == resource_name:

                section_names = self.get_default_reading_order()[1]
                if len(section_names) > 0:
                    cover_section = self.fragments.get(ftype="$260", fid=section_names[0]).value
                    page_templates = cover_section["$141"]
                    page_template = page_templates[0] if len(page_templates) == 1 else {}
                    if (page_template.get("$159") == "$270" and
                            page_template.get("$156") == "$326" and
                            page_template.get("$140") == "$320" and
                            page_template.get("$66", -1) == orig_width and
                            page_template.get("$67", -1) == orig_height):

                        page_template[IS("$66")] = width
                        page_template[IS("$67")] = height
                        section_updated = True

            if not section_updated:
                self.log.info("First page image dimensions were not updated")

        return cover_resource

    def locate_cover_image_resource_from_content(self, replace_pdf=False):

        section_names = self.get_default_reading_order()[1]
        if not section_names:
            return None

        cover_section = self.fragments.get(ftype="$260", fid=section_names[0]).value
        for page_template in cover_section["$141"]:
            story_name = page_template.get("$176")
            if story_name:
                break
        else:
            return None

        cover_story = self.fragments.get(ftype="$259", fid=story_name).value

        def scan_content_for_image(content):
            if content.get("$159") == "$271" and "$175" in content:
                return content["$175"]

            for subcontent in content.get("$146", {}):
                img = scan_content_for_image(subcontent)
                if img is not None:
                    return img

            return None

        resource_name = scan_content_for_image(cover_story)
        if resource_name is None:
            return None

        cover_resource = self.fragments.get(ftype="$164", fid=resource_name).value
        if cover_resource[IS("$161")] != "$565" or not replace_pdf:
            return cover_resource

        location = cover_resource["$165"]
        raw_media = self.fragments[YJFragmentKey(ftype="$417", fid=location)].value
        page_num = cover_resource.get("$564", 0) + 1

        try:
            jpeg_data = convert_pdf_to_jpeg(self.log, raw_media, page_num)
        except Exception as e:
            self.log.error("Exception during conversion of PDF '%s' page %d to JPEG: %s" % (location, page_num, exception_string(e)))
            return None

        return self.set_cover_image_data("jpeg", jpeg_data, update_cover_section=False)

