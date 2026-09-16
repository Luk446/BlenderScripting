import copy
import json
from pathlib import Path
import tempfile
import unittest

from acceptance_policy import critical_reasons
from approve_audited_job import approve_job, release_plan
from qa_yolo_obb import scan
from review_yolo_obb import qa_items
from test_qa_yolo_obb import fixture


class DefaultAcceptanceTests(unittest.TestCase):
    def test_publish_retries_transient_smb_denial_and_preserves_existing_destination(self):
        from unittest.mock import patch
        from approve_audited_job import publish_staged_dataset
        with tempfile.TemporaryDirectory() as folder:
            stage=Path(folder)/'staging';stage.mkdir()
            (stage/'approval.json').write_text('{}')
            output=Path(folder)/'approved'
            rename=Path.rename
            attempts=[]
            def delayed(path,destination):
                attempts.append(path)
                if len(attempts)==1:
                    raise PermissionError('SMB handle still open')
                return rename(path,destination)
            with patch.object(Path,'rename',delayed), patch('approve_audited_job.time.sleep'):
                publish_staged_dataset(stage,output)
            self.assertEqual(len(attempts),2)
            self.assertTrue((output/'approval.json').exists())
            stage.mkdir()
            with self.assertRaises(FileExistsError):
                publish_staged_dataset(stage,output)
            self.assertTrue(stage.exists())

    def test_default_accept_preserves_rejections_and_explicit_keeps(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            fixture(root)
            qa=scan(root, 2)
            state=dict(dataset=qa['dataset'], qa_fingerprint=qa['fingerprint'], decisions={})
            state['decisions'][qa['items'][0]['id']]='reject'
            state['decisions'][qa['items'][1]['id']]='keep'
            plan=release_plan(qa,state)
            self.assertEqual(list(plan.values()).count('default_accept'),18)
            self.assertEqual(plan[qa['items'][0]['id']],'excluded')
            self.assertEqual(plan[qa['items'][1]['id']],'individual_review')
            # Unlike strict mode, a rejected sample does not block other ordinary images.
            sample=next(i for i in qa['items'] if i['selection']=='random_sample')
            state['decisions'][sample['id']]='reject'
            release_plan(qa,state)

    def test_very_high_risk_gates_and_integrity_cannot_be_kept(self):
        ordinary=dict(errors=[],flags=['render_viewport_visibility_mismatch'],reasons=[],
                      metrics=dict(labels=3,brightness=70,contrast=20,padding_fraction=.1))
        self.assertFalse(critical_reasons(ordinary))
        for field,value in [('labels',0),('brightness',9),('contrast',4),('padding_fraction',.51)]:
            item=copy.deepcopy(ordinary);item['metrics'][field]=value
            self.assertTrue(critical_reasons(item))
        item=copy.deepcopy(ordinary);item['reasons']=['unresolved_candidate_boxes']
        self.assertTrue(critical_reasons(item))
        item=copy.deepcopy(ordinary);item['flags']=['compositor_requires_alignment_review']
        self.assertTrue(critical_reasons(item))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);fixture(root,1);qa=scan(root,1)
            qa['items'][0]['reasons'].append('unresolved_candidate_boxes')
            state=dict(dataset=qa['dataset'],qa_fingerprint=qa['fingerprint'],decisions={})
            with self.assertRaisesRegex(ValueError,'Very-high-risk'):
                release_plan(qa,state)
            state['decisions'][qa['items'][0]['id']]='keep'
            self.assertIn('individual_review',release_plan(qa,state).values())
            qa['items'][0]['errors']=['broken']
            with self.assertRaisesRegex(ValueError,'integrity failure'):
                release_plan(qa,state)

    def test_default_export_and_optional_review_have_accurate_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);root=folder/'job';fixture(root,3)
            qa=scan(root,1);qp=folder/'qa.json';qp.write_text(json.dumps(qa))
            state=dict(dataset=str(root),decisions={})
            self.assertEqual(qa_items(root,qp,state),[])
            optional=qa_items(root,qp,state,review_all=True)
            self.assertTrue(all(i['default_accept'] for i in optional))
            dp=folder/'review.json';dp.write_text(json.dumps(state))
            output=approve_job(qp,dp,folder/'approved')
            receipt=json.loads((output/'approval.json').read_text())
            self.assertEqual(receipt['counts']['default_accept'],3)
            for item in qa['items']:
                report=json.loads((output/item['run']/'annotations'/Path(item['report']).name).read_text())
                self.assertEqual(report['approval'],'default_accept_not_individually_reviewed')
                self.assertEqual((root/item['image']).read_bytes(),(output/item['run']/report['image_path']).read_bytes())
                self.assertEqual((root/item['label']).read_bytes(),(output/item['run']/report['label_path']).read_bytes())


if __name__=='__main__':
    unittest.main()
