import csv, json, subprocess, tempfile, unittest
from pathlib import Path
SCRIPT = Path(__file__).resolve().parents[1]/'skills/cmo-manga-name/scripts/storyboard.py'
class ExportTest(unittest.TestCase):
 def run_case(self, data, ok=True, existing=False):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp); src=p/'input.json'; dest=p/'name.tsv'
   src.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
   if existing: dest.write_text('do not overwrite',encoding='utf-8')
   result=subprocess.run(['python3',str(SCRIPT),str(src),'--output',str(dest)],capture_output=True,text=True)
   self.assertEqual(result.returncode==0,ok,result.stdout+result.stderr)
   if ok:
    with dest.open(newline='',encoding='utf-8') as f: cells=list(csv.reader(f,delimiter='\t'))
    self.assertEqual(cells[1:],data['rows'])
    self.assertEqual(len(cells[0]),4)
   elif existing: self.assertEqual(dest.read_text(),'do not overwrite')
   else: self.assertFalse(dest.exists())
 def base(self):
  return {'media':'article','characters':['澪'], 'rows':[['縦長','澪','澪「確認します」\n澪（"今度こそ"）','段構成：1コマ。手元へ視線。']], 'panels':[{'count':1,'text_map':[[1,2]]}]}
 def test_roundtrip(self): self.run_case(self.base())
 def test_silent(self):
  d=self.base(); d['rows'][0][1:3]=['','']; d['panels'][0]['text_map']=[[]]; self.run_case(d)
 def test_unknown_person(self):
  d=self.base(); d['rows'][0][1]='葵'; self.run_case(d,False)
 def test_bad_script(self):
  d=self.base(); d['rows'][0][2]='澪：これは未対応'; self.run_case(d,False)
 def test_columns(self):
  d=self.base(); d['rows'][0].append('余分'); self.run_case(d,False)
 def test_missing_text_map(self):
  d=self.base(); d['panels'][0]['text_map']=[[1]]; self.run_case(d,False)
 def test_no_overwrite(self): self.run_case(self.base(),False,True)
 def test_bad_size(self):
  d=self.base(); d['rows'][0][0]='9:16'; self.run_case(d,False)
 def test_formula(self):
  d=self.base(); d['rows'][0][3]='=IMPORTXML("a","b")'; self.run_case(d,False)
 def test_timing(self):
  d=self.base(); d['media']='short_video'; d['duration_seconds']=60; d['cuts']=[{'image':1,'start':0,'end':60}]; self.run_case(d)
 def test_timing_gap(self):
  d=self.base(); d['media']='short_video'; d['duration_seconds']=60; d['cuts']=[{'image':1,'start':1,'end':60}]; self.run_case(d,False)
 def test_annotation(self):
  d=self.base(); d['rows'][0][2]='澪「※確認します」\n注釈：※補足'; d['panels'][0]['annotation_map']=[{'note_line':2,'target_lines':[1]}]; self.run_case(d)
 def test_annotation_missing(self):
  d=self.base(); d['rows'][0][2]='澪「※確認します」\n注釈：補足'; self.run_case(d,False)
 def test_offscreen(self):
  d=self.base(); d['rows'][0][1]=''; d['panels'][0]['offscreen_speakers']=['澪']; self.run_case(d)
 def test_duplicate_text(self):
  d=self.base(); d['panels'][0]['text_map']=[[1,1,2]]; self.run_case(d,False)
 def test_readback(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp); src=p/'input.json'; actual=p/'cells.json'; out=p/'name.tsv'
   src.write_text(json.dumps(self.base()))
   r=subprocess.run(['python3',str(SCRIPT),str(src),'--output',str(out)],capture_output=True)
   self.assertEqual(r.returncode,0)
   with out.open(newline='') as f: cells=list(csv.reader(f,delimiter='\t'))
   actual.write_text(json.dumps(cells))
   r=subprocess.run(['python3',str(SCRIPT),str(src),'--compare-cells',str(actual)],capture_output=True)
   self.assertEqual(r.returncode,0,r.stderr)
   cells[1][2]='changed'; actual.write_text(json.dumps(cells))
   r=subprocess.run(['python3',str(SCRIPT),str(src),'--compare-cells',str(actual)],capture_output=True)
   self.assertNotEqual(r.returncode,0)
 def test_long_speaker(self):
  d=self.base(); name='あ'*21; d['characters']=[name]; d['rows'][0][1]=name; d['rows'][0][2]=name+'「確認」'; d['panels'][0]['text_map']=[[1]]; self.run_case(d,False)
 def test_note_marker_mismatch(self):
  d=self.base(); d['rows'][0][2]='澪「※1確認します」\n注釈：※2補足'; d['panels'][0]['annotation_map']=[{'note_line':2,'target_lines':[1]}]; self.run_case(d,False)
 def test_na_leading_bracket(self):
  d=self.base(); d['rows'][0][2]='澪「確認します」\nNA：「学ぶ」より「遊ぶ」'; d['panels'][0]['text_map']=[[1,2]]; self.run_case(d,False)
 def test_na_corner_bracket_ok(self):
  d=self.base(); d['rows'][0][2]='澪「確認します」\nNA：『学ぶ』より『遊ぶ』'; d['panels'][0]['text_map']=[[1,2]]; self.run_case(d)
 def test_video_missing_timing(self):
  d=self.base(); d['media']='short_video'; self.run_case(d,False)
 def test_readback_used_range(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp); src=p/'input.json'; actual=p/'cells.json'; out=p/'name.tsv'
   src.write_text(json.dumps(self.base()))
   r=subprocess.run(['python3',str(SCRIPT),str(src),'--output',str(out)],capture_output=True)
   self.assertEqual(r.returncode,0)
   with out.open(newline='') as f: cells=list(csv.reader(f,delimiter='\t'))
   cells.extend([[],['','','','']]); actual.write_text(json.dumps(cells))
   r=subprocess.run(['python3',str(SCRIPT),str(src),'--compare-cells',str(actual)],capture_output=True)
   self.assertEqual(r.returncode,0,r.stderr)
   cells[-1]=['古い例文']; actual.write_text(json.dumps(cells))
   r=subprocess.run(['python3',str(SCRIPT),str(src),'--compare-cells',str(actual)],capture_output=True)
   self.assertNotEqual(r.returncode,0)
if __name__=='__main__': unittest.main()
