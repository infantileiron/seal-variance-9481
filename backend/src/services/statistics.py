import math,json,hashlib
from scipy.stats import f

def anova(snapshot):
    groups=snapshot['groups']
    if len(groups)<2:raise ValueError('至少选择两种工艺方案')
    if any(len(g['samples'])<2 for g in groups):raise ValueError('每个方案至少需要2条拉力样本；不会静默移除小样本组')
    n=sum(len(g['samples']) for g in groups);k=len(groups)
    grand=sum(s['force'] for g in groups for s in g['samples'])/n
    summaries=[];between=0.;within=0.
    for g in groups:
        values=[s['force'] for s in g['samples']];mean=sum(values)/len(values)
        ss=sum((v-mean)**2 for v in values)
        between+=len(values)*(mean-grand)**2;within+=ss
        summaries.append({'id':g['id'],'code':g['code'],'name':g['name'],'n':len(values),'mean':mean,'sd':math.sqrt(ss/(len(values)-1)),'min':min(values),'max':max(values),'flagged':sum(s['flagged'] for s in g['samples'])})
    if within<=1e-12:raise ValueError('组内方差为零，F检验不成立；补充有实际测量差异的独立样本')
    df_between=k-1;df_within=n-k
    ms_between=between/df_between;ms_within=within/df_within
    statistic=ms_between/ms_within;p=float(f.sf(statistic,df_between,df_within))
    return {'n':n,'groups':summaries,'grand_mean':grand,'ss_between':between,'ss_within':within,'ss_total':between+within,'df_between':df_between,'df_within':df_within,'ms_between':ms_between,'ms_within':ms_within,'f':statistic,'p':p,'eta_squared':between/(between+within),'significant':p<.05,'flagged':sum(g['flagged'] for g in summaries),'checksum':hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),'method':'单因素独立样本 ANOVA；α=0.05；异常标记样本全部保留；要求独立、组内近似正态与方差齐性。显著F不说明哪一组更优，也不替代工艺合格判定。'}
