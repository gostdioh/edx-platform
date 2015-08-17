"""Tests for contents"""

import os
import unittest
import ddt
from path import path
from xmodule.contentstore.content import StaticContent, StaticContentStream
from xmodule.contentstore.content import ContentStore
from opaque_keys.edx.locations import SlashSeparatedCourseKey, AssetLocation
from xmodule.static_content import _write_js, _list_descriptors

SAMPLE_STRING = """
This is a sample string with more than 1024 bytes, the default STREAM_DATA_CHUNK_SIZE

Lorem Ipsum is simply dummy text of the printing and typesetting industry.
Lorem Ipsum has been the industry's standard dummy text ever since the 1500s,
when an unknown printer took a galley of type and scrambled it to make a type
specimen book. It has survived not only five centuries, but also the leap into
electronic typesetting, remaining essentially unchanged. It was popularised in
the 1960s with the release of Letraset sheets containing Lorem Ipsum passages,
nd more recently with desktop publishing software like Aldus PageMaker including
versions of Lorem Ipsum.

It is a long established fact that a reader will be distracted by the readable
content of a page when looking at its layout. The point of using Lorem Ipsum is
that it has a more-or-less normal distribution of letters, as opposed to using
'Content here, content here', making it look like readable English. Many desktop
ublishing packages and web page editors now use Lorem Ipsum as their default model
text, and a search for 'lorem ipsum' will uncover many web sites still in their infancy.
Various versions have evolved over the years, sometimes by accident, sometimes on purpose
injected humour and the like).

Lorem Ipsum is simply dummy text of the printing and typesetting industry.
Lorem Ipsum has been the industry's standard dummy text ever since the 1500s,
when an unknown printer took a galley of type and scrambled it to make a type
specimen book. It has survived not only five centuries, but also the leap into
electronic typesetting, remaining essentially unchanged. It was popularised in
the 1960s with the release of Letraset sheets containing Lorem Ipsum passages,
nd more recently with desktop publishing software like Aldus PageMaker including
versions of Lorem Ipsum.

It is a long established fact that a reader will be distracted by the readable
content of a page when looking at its layout. The point of using Lorem Ipsum is
that it has a more-or-less normal distribution of letters, as opposed to using
'Content here, content here', making it look like readable English. Many desktop
ublishing packages and web page editors now use Lorem Ipsum as their default model
text, and a search for 'lorem ipsum' will uncover many web sites still in their infancy.
Various versions have evolved over the years, sometimes by accident, sometimes on purpose
injected humour and the like).
"""


class Content(object):
    """
    A class with location and content_type members
    """
    def __init__(self, location, content_type):
        self.location = location
        self.content_type = content_type


class FakeGridFsItem(object):
    """
    This class provides the basic methods to get data from a GridFS item
    """
    def __init__(self, string_data):
        self.cursor = 0
        self.data = string_data
        self.length = len(string_data)

    def seek(self, position):
        """
        Set the cursor at "position"
        """
        self.cursor = position

    def read(self, chunk_size):
        """
        Read "chunk_size" bytes of data at position cursor and move the cursor
        """
        chunk = self.data[self.cursor:(self.cursor + chunk_size)]
        self.cursor += chunk_size
        return chunk


@ddt.ddt
class ContentTest(unittest.TestCase):
    def test_thumbnail_none(self):
        # We had a bug where a thumbnail location of None was getting transformed into a Location tuple, with
        # all elements being None. It is important that the location be just None for rendering.
        content = StaticContent('loc', 'name', 'content_type', 'data', None, None, None)
        self.assertIsNone(content.thumbnail_location)

        content = StaticContent('loc', 'name', 'content_type', 'data')
        self.assertIsNone(content.thumbnail_location)

    def test_static_url_generation_from_courseid(self):
        course_key = SlashSeparatedCourseKey('foo', 'bar', 'bz')
        url = StaticContent.convert_legacy_static_url_with_course_id('images_course_image.jpg', course_key)
        self.assertEqual(url, '/c4x/foo/bar/asset/images_course_image.jpg')

    @ddt.data(
        (u"monsters__.jpg", u"monsters__.jpg"),
        (u"monsters__.png", u"monsters__-png.jpg"),
        (u"dots.in.name.jpg", u"dots.in.name.jpg"),
        (u"dots.in.name.png", u"dots.in.name-png.jpg"),
    )
    @ddt.unpack
    def test_generate_thumbnail_image(self, original_filename, thumbnail_filename):
        contentStore = ContentStore()
        content = Content(AssetLocation(u'mitX', u'800', u'ignore_run', u'asset', original_filename), None)
        (thumbnail_content, thumbnail_file_location) = contentStore.generate_thumbnail(content)
        self.assertIsNone(thumbnail_content)
        self.assertEqual(AssetLocation(u'mitX', u'800', u'ignore_run', u'thumbnail', thumbnail_filename), thumbnail_file_location)

    def test_compute_location(self):
        # We had a bug that __ got converted into a single _. Make sure that substitution of INVALID_CHARS (like space)
        # still happen.
        asset_location = StaticContent.compute_location(
            SlashSeparatedCourseKey('mitX', '400', 'ignore'), 'subs__1eo_jXvZnE .srt.sjson'
        )
        self.assertEqual(AssetLocation(u'mitX', u'400', u'ignore', u'asset', u'subs__1eo_jXvZnE_.srt.sjson', None), asset_location)

    def test_get_location_from_path(self):
        asset_location = StaticContent.get_location_from_path(u'/c4x/foo/bar/asset/images_course_image.jpg')
        self.assertEqual(
            AssetLocation(u'foo', u'bar', None, u'asset', u'images_course_image.jpg', None),
            asset_location
        )

    def test_static_content_stream_stream_data(self):
        """
        Test StaticContentStream stream_data function, asserts that we get all the bytes
        """
        data = SAMPLE_STRING
        item = FakeGridFsItem(data)
        static_content_stream = StaticContentStream('loc', 'name', 'type', item, length=item.length)

        total_length = 0
        stream = static_content_stream.stream_data()
        for chunck in stream:
            total_length += len(chunck)

        self.assertEqual(total_length, static_content_stream.length)

    def test_static_content_stream_stream_data_in_range(self):
        """
        Test StaticContentStream stream_data_in_range function,
        asserts that we get the requested number of bytes
        first_byte and last_byte are chosen to be simple but non trivial values
        and to have total_length > STREAM_DATA_CHUNK_SIZE (1024)
        """
        data = SAMPLE_STRING
        item = FakeGridFsItem(data)
        static_content_stream = StaticContentStream('loc', 'name', 'type', item, length=item.length)

        first_byte = 100
        last_byte = 1500

        total_length = 0
        stream = static_content_stream.stream_data_in_range(first_byte, last_byte)
        for chunck in stream:
            total_length += len(chunck)

        self.assertEqual(total_length, last_byte - first_byte + 1)

    def test_static_content_write_js(self):
        """
        Test that only one filename starts with 000.
        """
        output_root = path(u'common/static/xmodule/descriptors/js')
        js_file_paths = _write_js(output_root, _list_descriptors())
        js_file_paths = [file_path for file_path in js_file_paths if os.path.basename(file_path).startswith('000-')]
        self.assertEqual(len(js_file_paths), 1)
        self.assertIn("XModule.Descriptor = (function () {", open(js_file_paths[0]).read())
