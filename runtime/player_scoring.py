"""MafiaNights player scoring rules.

Base rating is 50. Per-game rating rows store the delta and its exact
components so the profile can explain every point gained or lost.
"""
from __future__ import annotations

import html
import logging
from typing import Any

from repositories.rating_repository import RatingRepository
import runtime.game_end as game_end

BASE_SCORE=50
WIN_POINTS=20
CHALLENGE_MAX_POINTS=10
KICK_PENALTY=20
WARNING_PENALTIES=(1,2,3,4,5)

def warning_penalty(count:int)->int:
    count=max(0,int(count))
    if count<=len(WARNING_PENALTIES):return sum(WARNING_PENALTIES[:count])
    return sum(WARNING_PENALTIES)+sum(range(len(WARNING_PENALTIES)+1,count+1))

def _challenge_stats(app:Any,game:dict[str,Any],user_id:int)->tuple[int,int]:
    try:
        state=dict(game.get("state") or {})
        stats=dict(state.get("challenge_score_stats") or {})
        eligible=max(0,int(stats.get("eligible_turns") or 0))
        rows=app.runtime.state.challenges.list_challenges(game["id"])
        executed=sum(1 for row in rows if int(row.get("target_id") or 0)==int(user_id) and str(row.get("status") or "").lower() in {"active","executed"})
        return eligible,executed
    except Exception:
        logging.exception("failed to count challenge score game=%s user=%s",game.get("id"),user_id)
        return 0,0

def _challenge_points(eligible:int,executed:int)->int:
    if eligible<=0 or executed<=0:return 0
    return min(CHALLENGE_MAX_POINTS,int((CHALLENGE_MAX_POINTS*executed/eligible)+0.5))

def _warning_count(row,state):
    value=(state.get("warnings") or {}).get(str(int(row.get("player_id") or 0)),row.get("warning_count",0))
    try:return max(0,int(value))
    except (TypeError,ValueError):return 0

def _is_kicked(row,state):
    return bool((state.get("kicked_players") or {}).get(str(int(row.get("player_id") or 0)))) or str(row.get("status") or "")=="kicked"

def score_game(app:Any,game:dict[str,Any],rows:list[dict[str,Any]],winner:str)->None:
    if str(game.get("status") or "")!="finished":
        logging.info("rating deferred because game is not finalized: game=%s status=%s",game.get("id"),game.get("status"));return
    repo=RatingRepository();state=dict(game.get("state") or {});recorded={str(x) for x in (state.get("rating_recorded_players") or [])}
    for row in rows:
        uid=int(row["player_id"]);key=str(uid)
        if key in recorded:continue
        side=game_end._role_side(row,state);win_bonus=WIN_POINTS if winner!="draw" and side==winner else 0
        eligible_turns,executed_challenges=_challenge_stats(app,game,uid)
        challenge_bonus=_challenge_points(eligible_turns,executed_challenges)
        warning_total=warning_penalty(_warning_count(row,state));kick_penalty=KICK_PENALTY if _is_kicked(row,state) else 0
        delta=win_bonus+challenge_bonus-warning_total-kick_penalty;result="draw" if winner=="draw" else ("win" if side==winner else "loss")
        try:
            repo.record(uid,game["id"],int(delta),result,str(row.get("role") or ""),win_bonus=win_bonus,challenge_bonus=challenge_bonus,warning_penalty=warning_total,kick_penalty=kick_penalty);recorded.add(key)
            engine=getattr(app,"_achievement_engine",None)
            if engine is not None:engine.sync_achievements(uid)
        except Exception:logging.exception("failed to record rating/achievement game=%s user=%s",game.get("id"),uid)
    state["rating_recorded_players"]=sorted(recorded);app.runtime.state.games.update_game(game["id"],state=state)

def _patch_final_report():
    if getattr(game_end,"_score_final_report_patched",False):return
    original=game_end._final_text
    def final_text(game,rows):
        text=original(game,rows);state=dict(game.get("state") or {});kicked={str(k) for k,v in (state.get("kicked_players") or {}).items() if v}
        for row in rows:
            if str(int(row.get("player_id") or 0)) not in kicked:continue
            seat=int(row.get("seat") or 0);name=str(row.get("nickname") or row.get("first_name") or row.get("username") or row.get("player_id") or "👤");text=text.replace(f"{seat:02d} {html.escape(name)}",f"{seat:02d} 🚫 {html.escape(name)}",1)
        return text
    game_end._final_text=final_text;game_end._score_final_report_patched=True

def _install_final_score_hook(app):
    if getattr(game_end,"_final_score_hook_installed",False):return
    table=getattr(getattr(app.dp,"callback_query_handlers",None),"handlers",[]);original=None;kept=[]
    for item in table:
        fn=getattr(item,"callback",None)
        if getattr(fn,"__module__","")==game_end.__name__ and getattr(fn,"__name__","")=="game_end":original=fn;continue
        kept.append(item)
    table[:]=kept
    if original is None:return
    async def finalized_game_end(callback):
        await original(callback);data=str(callback.data or "").split(":")
        if len(data)<3 or data[0]!="game_end" or data[2]!="confirm_final":return
        try:
            game=app.runtime.state.games.get_game(int(data[1]))
            if not game or str(game.get("status") or "")!="finished":return
            winner=str((game.get("state") or {}).get("game_result") or "")
            if not winner:return
            score_game(app,game,app.runtime.state.games.list_players(game["id"]),winner)
        except Exception:logging.exception("final score hook failed game=%s",data[1] if len(data)>1 else "?")
    app.dp.register_callback_query_handler(finalized_game_end,lambda c:str(c.data or "").startswith("game_end:"),state="*");game_end._final_score_hook_installed=True

def install(app:Any)->bool:
    game_end._score_players=lambda app_,game_,rows_,winner_:score_game(app_,game_,rows_,winner_)
    app._score_finished_game=lambda game_, rows_, winner_: score_game(app, game_, rows_, winner_)
    _patch_final_report()
    _install_final_score_hook(app)
    app.player_scoring={"base":BASE_SCORE,"win":WIN_POINTS,"challenge_max":CHALLENGE_MAX_POINTS,"kick":KICK_PENALTY,"warnings":WARNING_PENALTIES}
    return True
