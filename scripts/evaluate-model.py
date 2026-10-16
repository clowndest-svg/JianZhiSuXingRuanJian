"""Exercise the real server model with synthetic material, without accounts or service changes."""
import importlib.util,json,os,sys,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root));(root/'_audit_sandbox').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir=root/'_audit_sandbox') as temp:
    for kind in ('DB','UPLOAD','WEB'):os.environ['QINGSU_'+kind+'_DIR']=temp+'/'+kind
    spec=importlib.util.spec_from_file_location('model_review',root/'server.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    output=m.llm_chat('只输出两个字：已连接',max_tokens=16,temperature=0)
    if not output:raise RuntimeError('Real model inference unavailable')
    items=[{'title':'合成测试资料','snippet':'测试产品每100克含407 kcal。此资料不涉及个人健康情况。','host':'fixture.invalid','url':'https://fixture.invalid/data'}]
    answer,how=m.synthesize('测试产品每100克多少热量？',items,[],['测试产品'])
    assert '407' in answer and '999' not in answer
    m.llm_chat=lambda *a,**k:'含999 kcal，保证瘦'
    rejected,kind=m.synthesize('同一问题',items,[],['测试产品']);assert kind!='model' and '999' not in rejected
    m.llm_chat=lambda *a,**k:None
    fallback,kind=m.synthesize('同一问题',items,[],['测试产品']);assert kind=='extract' and '407' in fallback
    print(json.dumps({'real_inference':'passed','grounded_answer':'passed','real_summary_mode':how,'unsupported_number_rejected':True,'offline_model_extract':'passed'}))
