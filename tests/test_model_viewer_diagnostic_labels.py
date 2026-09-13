from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from model_viewer.normalization import diagnostics


class DiagnosticLabels(TestCase):
    def test_no_model(self):
        self.assertEqual(diagnostics(None), [('No model loaded', 'Open a model')])

    def test_rules_and_unsupported(self):
        preview = SimpleNamespace(primary=SimpleNamespace(payload=b''),
            model=SimpleNamespace(components={1:{'geometry':{'div2_floats':[1.]}}}),
            container={'animation_preview_error':'missing'})
        with patch('model_viewer.normalization.normalize', return_value=(b'', ['player-dragon-root-names/1','player-dragon-div2-removal/1'])):
            self.assertEqual(diagnostics(preview), [('Animation target name mismatch','Align node names with animation targets'),('DIV2 table','Remove table')])
        with patch('model_viewer.normalization.normalize', return_value=(b'', [])):
            self.assertEqual(diagnostics(preview), [('DIV2 table','No supported normalization rule'),('Animation mismatch','No supported normalization rule')])
            preview.model.components = {}; preview.container = None
            self.assertEqual(diagnostics(preview), [('No normalization required','No changes')])
