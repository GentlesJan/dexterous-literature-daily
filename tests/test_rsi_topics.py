from omegaconf import OmegaConf
from zotero_arxiv_daily.digest_state import matches_research

def test_rsi_is_independent_robotics_topic():
    research = OmegaConf.load('config/robotics.yaml').research
    assert matches_research('Self-improving robots through autonomous practice', research)
    assert matches_research('Continual learning for robotic locomotion', research)
    assert matches_research('Robot RSI with policy improvement', research)
    assert matches_research('Multi-fingered grasp synthesis', research)
    assert not matches_research('Recursive self-improvement for code generation', research)
    assert not matches_research('Online learning for stock price forecasting', research)
    assert not matches_research('Robot vision with recursive image pyramids', research)
