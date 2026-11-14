import unittest
from visual_learning import QUESTIONS, grade, image_for

class VisualLearningTests(unittest.TestCase):
    def test_each_question_has_one_correct_choice(self):
        for q in QUESTIONS:
            outcomes=[grade(q['id'], c)['correct'] for c,_ in q['choices']]
            self.assertEqual(sum(outcomes),1,q['id'])
    def test_all_images_are_real_png(self):
        for q in QUESTIONS:
            for _, smiles in q['choices']:
                self.assertTrue(image_for(smiles).startswith(b'\x89PNG\r\n\x1a\n'))
    def test_wrong_answer_has_explanation(self):
        result=grade('H01','B')
        self.assertFalse(result['correct'])
        self.assertIn('Ethanol',result['message'])
    def test_unknown_option_rejected(self):
        with self.assertRaises(ValueError): grade('H01','Z')
