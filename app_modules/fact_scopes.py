"""Keep historical questions from silently receiving today's numbers."""
import re
from datetime import date,timedelta
def answer(question,data,get_db,deficit_rows):
    week=any(s in question for s in ('本周','这周','最近7天','近七天','最近几天','平均缺口'))
    if week and any(s in question for s in ('缺口','赤字','体重','多重')):
        today=date.today();start=today-timedelta(days=today.weekday() if any(s in question for s in ('本周','这周')) else 6)
        c=get_db()
        try:
            if '缺口' in question or '赤字' in question:
                rows=[r for r in deficit_rows(c,data['user']['id'],data['metrics'],7) if r['date']>=start.isoformat() and r['record_status']=='complete']
                if not rows:return '这个时间范围尚无已确认完整的日期，不能把部分记录算成全天平均缺口。'
                average=round(sum(r['deficit'] for r in rows)/len(rows))
                return f"该时间范围有 {len(rows)} 个已确认完整日，平均估算缺口为 {average} kcal；不包含未确认的日期。"
            rows=c.execute('SELECT log_date,weight_jin FROM weight_logs WHERE user_id=? AND log_date>=? AND log_date<=? ORDER BY log_date,id DESC',(data['user']['id'],start.isoformat(),today.isoformat())).fetchall()
            latest={}
            for row in rows:latest.setdefault(row['log_date'],row['weight_jin'])
            values=list(latest.values())
            if len(values)<2:return '这个时间范围缺少至少两个不同日期的体重记录，暂不能计算变化。'
            return f"该时间范围首末体重记录相差 {round(values[-1]-values[0],1)} 斤；采用每天最后一笔，不是脂肪变化的实测。"
        finally:c.close()
    if any(s in question for s in ('昨天','前天','上周','上个月')) or re.search(r'\d{4}-\d{1,2}-\d{1,2}',question):
        return '这个问题涉及历史日期，请在「历史与补录」选择对应日期查看；我不会用今天的数据冒充那天的记录。'
    return None
