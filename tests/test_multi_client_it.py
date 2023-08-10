import unittest

from tests.test_client_it import ClientTestCase
from installer.install import ModuleInstaller


class MultiClientTestCase(ClientTestCase):
    options2 = {
        'webdav_hostname': 'https://wrong.url.ru',
        'webdav_login': 'webdavclient.test2',
        'webdav_password': 'Qwerty123!',
        'webdav_override_methods': {
            'check': 'FAKE',
            'download': 'FAKE',
            'upload': 'FAKE',
            'clean': 'FAKE',
        }
    }

    def setUp(self):
        super(ClientTestCase, self).setUp()
        self.second_client = ModuleInstaller(self.options2)


if __name__ == '__main__':
    unittest.main()
