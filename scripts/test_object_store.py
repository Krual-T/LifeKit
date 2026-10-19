"""Direct reads preserve bytes/versions and fail on incomplete responses."""
import io
import unittest
from unittest.mock import Mock

from botocore.response import StreamingBody
from botocore.exceptions import IncompleteReadError

import object_store as storage


class DirectReadTests(unittest.TestCase):
    def test_read_binary_version_without_creating_files(self):
        data = b"\x00\xffraw evidence\n"
        body = StreamingBody(io.BytesIO(data), len(data))
        s3 = Mock()
        s3.get_object.return_value = {"Body": body, "ContentLength": len(data), "VersionId": "v1"}
        output = io.BytesIO()
        result = storage.read(s3, "lifekernel", "data/original", output, "v1")
        self.assertEqual(output.getvalue(), data)
        self.assertEqual(result["version_id"], "v1")
        self.assertTrue(body._raw_stream.closed)
        s3.get_object.assert_called_once_with(Bucket="lifekernel", Key="data/original", VersionId="v1")

    def test_truncated_response_is_an_error_and_closes_body(self):
        body = StreamingBody(io.BytesIO(b"short"), 20)
        s3 = Mock()
        s3.get_object.return_value = {"Body": body, "ContentLength": 20}
        with self.assertRaises(IncompleteReadError):
            storage.read(s3, "lifekernel", "data/original", io.BytesIO())
        self.assertTrue(body._raw_stream.closed)

    def test_uri_round_trip_reserved_characters_and_version(self):
        key = "data/wiki/原文 + %2F #?.pdf"
        uri = storage.object_uri("lifekernel", key, "version+/=")
        self.assertEqual(storage.key_path(uri, "lifekernel"), (key, "version+/="))
        self.assertEqual(storage.key_path("s3://lifekernel/data/原文+1.md", "lifekernel"),
                         ("data/原文+1.md", None))
        with self.assertRaises(ValueError):
            storage.key_path("s3://lifekernel/data/%2E%2E/file", "lifekernel")


if __name__ == "__main__":
    unittest.main()
