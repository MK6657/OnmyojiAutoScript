import os
import unittest

# adbutils 0.11.0 imports the legacy pkg_resources name.  Importing the
# product package first exercises the same bootstrap used by production code.
import module.device.pkg_resources  # noqa: F401
import adbutils

from module.device.connection_attr import ConnectionAttr


class AdbBinaryResolutionTest(unittest.TestCase):
    def test_resolves_adb_from_imported_adbutils_package(self):
        connection = object.__new__(ConnectionAttr)
        expected = os.path.abspath(
            os.path.join(os.path.dirname(adbutils.__file__), 'binaries', 'adb.exe')
        ).replace('\\', '/')

        self.assertTrue(os.path.isfile(expected))
        self.assertEqual(connection.adb_binary, expected)


if __name__ == '__main__':
    unittest.main()
