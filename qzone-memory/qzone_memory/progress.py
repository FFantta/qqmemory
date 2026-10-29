"""Stage-specific progress. A scan plan percentage is not recovery coverage."""
import time

STAGES={'login':'扫码确认','visible':'备份当前说说','mobile':'补充互动与多图',
        'history':'查找历史线索','deep':'深度扫描历史分段','media':'保存图片','export':'生成离线档案'}


class TaskProgress:
    def __init__(self,clock=time.monotonic):
        self.clock=clock
        self.reset()

    def reset(self):
        self.ended=None
        self.started=self.clock();self.stage_started=self.started
        self.stage='login';self.done=0;self.total=None;self.baseline=0

    def update(self,value):
        stage=value['stage'];done=max(0,int(value.get('done',0)));total=value.get('total')
        if stage!=self.stage or done<self.done or total!=self.total:
            self.stage_started=self.clock();self.baseline=done
        self.stage,self.done,self.total=stage,done,int(total) if total else None

    def finish(self):
        self.ended=self.clock()

    def snapshot(self,active,phase):
        now=self.ended if self.ended is not None else self.clock();elapsed=max(0,int(now-self.started))
        percent=min(100,round(100*self.done/self.total,1)) if self.total else None
        eta=None
        # Pages per segment differ, so expose a deliberately broad range.
        units=self.done-self.baseline;duration=now-self.stage_started
        if active and self.total and units>=5 and duration>=10 and self.done<self.total:
            estimate=duration/units*(self.total-self.done)
            eta=[max(1,round(estimate*.5)),max(2,round(estimate*2))]
        return dict(stage=self.stage,label=STAGES.get(self.stage,self.stage),done=self.done,total=self.total,
                    percent=percent,elapsed=elapsed,eta=eta,
                    state='stopping' if phase=='stopping' else 'running' if active else 'idle')
