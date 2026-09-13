import unittest
from types import SimpleNamespace
from unittest.mock import patch
from model_viewer.workflow import texture_proposals,apply_textures,target_diagnostics
from model_viewer.normal_maps import decode_normal,preview_rgba,suggest_mode


class WorkflowTests(unittest.TestCase):
    def preview(self):
        model=SimpleNamespace(texture_references={1:dict(filename='x.tga',external=True),2:dict(filename='y.tga',external=True)})
        corpus=SimpleNamespace(texture_candidates=lambda name:('a','b') if name=='x.tga' else (),
                               read=lambda occurrence:SimpleNamespace(payload=occurrence),check=lambda:None)
        return SimpleNamespace(model=model,corpus=corpus,texture_sources={1:'old'},images={1:'old image'})

    def test_batch_does_not_choose_ambiguous_or_missing_sources(self):
        p=self.preview(); proposals=texture_proposals(p)
        self.assertEqual(proposals[0]['candidates'],('a','b'))
        self.assertEqual(proposals[1]['candidates'],())
        self.assertEqual(p.texture_sources,{1:'old'})

    def test_batch_transactional_decode_failure(self):
        p=self.preview()
        with patch('model_viewer.workflow.decode_image',side_effect=['decoded',ValueError('bad texture')]):
            with self.assertRaises(ValueError): apply_textures(p,{1:'a',2:'b'})
        self.assertEqual(p.texture_sources,{1:'old'}); self.assertEqual(p.images,{1:'old image'})
        with patch('model_viewer.workflow.decode_image',return_value='decoded'):
            self.assertEqual(apply_textures(p,{2:'b'}),1)
        self.assertEqual(p.images,{1:'old image',2:'decoded'})

    def test_target_diagnostics_collect_all(self):
        doc=SimpleNamespace(roots=(0,1)); nodes={1:dict(name='duplicate'),2:dict(name='duplicate')}
        with patch('model_viewer.workflow.animation.sequence',return_value=dict(controlled=[dict(node_name=n) for n in ('missing1','duplicate','missing2')])):
            report=target_diagnostics(doc,nodes)
        self.assertEqual(report['missing'],['missing1','missing2']); self.assertEqual(report['ambiguous'],['duplicate'])

    def test_batch_corpus_drift_leaves_bindings_unchanged(self):
        p=self.preview()
        def drift(): raise ValueError('corpus changed')
        p.corpus.check=drift
        with patch('model_viewer.workflow.decode_image',return_value='decoded'):
            with self.assertRaises(ValueError): apply_textures(p,{1:'a',2:'b'})
        self.assertEqual(p.texture_sources,{1:'old'}); self.assertEqual(p.images,{1:'old image'})

    def test_embedded_targets_use_declared_animation_roots(self):
        doc=SimpleNamespace(roots=(0,))
        with patch('model_viewer.workflow.animation.sequence',return_value=dict(controlled=[])) as decode:
            report=target_diagnostics(doc,{},roots=(7,9))
        self.assertEqual([call.args[1] for call in decode.call_args_list],[7,9])
        self.assertEqual(report,dict(missing=[],ambiguous=[],parse_errors=[]))

    def test_normal_modes_and_y(self):
        self.assertEqual(decode_normal(.5,.5,1,0,'RGB'),(0,0,1))
        self.assertEqual(decode_normal(0,.5,1,.5,'AGB'),(0,0,1))
        self.assertEqual(decode_normal(0,.5,0,.5,'AG'),(0,0,1))
        a=decode_normal(.5,1,1,0,'RGB'); b=decode_normal(.5,1,1,0,'RGB',True)
        self.assertEqual(a[0],b[0]); self.assertEqual(a[1],-b[1]); self.assertEqual(a[2],b[2])
        raw=bytes((0,128,255,128))*3
        self.assertEqual(suggest_mode(raw),'AGB'); self.assertEqual(preview_rgba(raw),bytes((128,128,255,255))*3)
        self.assertEqual(raw,bytes((0,128,255,128))*3)

if __name__=='__main__': unittest.main()
