import unittest
from model_viewer.filtering import path_filter


class FilterTests(unittest.TestCase):
    def test_plain_fragment_and_empty(self):
        self.assertTrue(path_filter('DEER')('Win32/Characters/Deer/M_Deer.nif'))
        self.assertTrue(path_filter('')('anything'))
        self.assertFalse(path_filter('rock')('Deer.nif'))

    def test_wildcards_on_filename_and_path(self):
        path = 'Win32/Characters/Deer/M_Deer.nif'
        for query in ('*.nif','M_*eer.nif','M_?eer.nif','*Deer/*.nif',r'WIN32\Characters\*\*.NIF'):
            self.assertTrue(path_filter(query)(path),query)
        for query in ('*.cat','M_?.nif','Deer*.nif'):
            self.assertFalse(path_filter(query)(path),query)

    def test_literal_regex_characters(self):
        self.assertTrue(path_filter('a+b(1)')('a+b(1).nif'))
        self.assertFalse(path_filter('a+b(1)')('ab1.nif'))
        self.assertTrue(path_filter('[')('mesh[.nif'))
