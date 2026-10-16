"""Conservative output checks for summaries of retrieved material."""
import re
def grounded_summary(text,items):
    material=' '.join(str(r.get('title',''))+' '+str(r.get('snippet','')) for r in items)
    numbers=set(re.findall(r'\d+(?:\.\d+)?',material))
    if any(n not in numbers for n in re.findall(r'\d+(?:\.\d+)?',text)):return False
    if re.search(r'保证瘦|包瘦|根治|立即停药|自行停药|加倍用药',text):return False
    return True
